#!/usr/bin/env python3
"""
step3_portfolio_mqt.py  --  STEP 3: Generate the 3-Plan Decision Portfolio
Contested Network Allocation: Zurich Morning Peak Corridor

Runs the MQT ProblemSolver Pathfinder + dimod Simulated Annealing workflow
across 3 distinct policy configurations (Plan 1, Plan 2, Plan 3) and exports
decision_portfolio.json for Step 4 visualization.
"""
import contextlib
import io
import itertools
import json
import random
import time
from collections import Counter

import dimod
import numpy as np
import pandas as pd
from dimod import SimulatedAnnealingSampler
import mqt.problemsolver.qubo_tools.pathfinder as pf

import solve_qubo_mqt as s1

# =====================================================================
# 1. DEFINE THE 3 PORTFOLIO PLANS (Only numbers & conflict rules change)
# =====================================================================
PORTFOLIO_CONFIGS = {
    "plan_1_utilitarian": {
        "name": "Plan 1: Utilitarian & Commercial Speed",
        "subtitle": "Inviolable Dialysis Traded Away (Low Deadline Penalty)",
        "priority": {1: 30.0, 2: 1.0, 3: 2.0, 4: 15.0},
        "deadline_min": {3: 6.5},
        "deadline_penalty": 10.0,  # Weak penalty: Van buys off Dialysis slot on North Bypass!
        "conflict_pairs": [(1, 3), (3, 4), (4, 2), (4, 1)],
        "conflict_weight": 40.0,
    },
    "plan_2_recommended": {
        "name": "Plan 2: Inviolable Medical & Transit Equity (Recommended)",
        "subtitle": "All Inviolable Claims Protected (High Penalty Threshold)",
        "priority": {1: 30.0, 2: 1.0, 3: 8.0, 4: 1.0},
        "deadline_min": {3: 6.5},
        "deadline_penalty": 50.0,  # Priority-preserving penalty: Dialysis protected on North Bypass
        "conflict_pairs": [(1, 3), (3, 4), (4, 2), (4, 1)],
        "conflict_weight": 40.0,
    },
    "plan_3_strict_spine": {
        "name": "Plan 3: Strict Spine Exclusivity (Mass-Transit First)",
        "subtitle": "No Shared Spine Capacity — Ambulance Diverted for 185-Pax Tram",
        "priority": {1: 25.0, 2: 35.0, 3: 8.0, 4: 1.0},
        "deadline_min": {3: 6.5},
        "deadline_penalty": 50.0,
        # All 6 pairs conflict: Tram (2) cannot share Main Spine with Ambulance (1) or Dialysis (3)
        "conflict_pairs": [(1, 2), (2, 3), (1, 3), (3, 4), (4, 2), (4, 1)],
        "conflict_weight": 50.0,
    },
}

SEEDS = [0, 1, 2, 3, 4]
NUM_READS = 40
NUM_SWEEPS = 1000

# =====================================================================
# 2. LOAD GRAPH ONCE
# =====================================================================
with contextlib.redirect_stdout(io.StringIO()):
    _edges, _names = s1.load_macro_edges(s1.GRAPH_FILE)
    graph, ids, route_minutes, labels = s1.build_graph(_edges, _names)

N_V = len(ids)
START, END = ids[s1.START_NAME], ids[s1.END_NAME]
ROUTE_NODES = sorted(route_minutes)  # 2: Main (5.1m), 3: North (6.5m), 4: South (8.5m)
MAIN, NORTH, SOUTH = ROUTE_NODES[0], ROUTE_NODES[1], ROUTE_NODES[2]
SHORT = {
    MAIN: f"Main({route_minutes[MAIN]:g}m)",
    NORTH: f"North({route_minutes[NORTH]:g}m)",
    SOUTH: f"South({route_minutes[SOUTH]:g}m)",
}
OCCUPANCY = {1: 2, 2: 185, 3: 1, 4: 1}


# =====================================================================
# 3. BUILD QUBO & SOLVE FOR EACH PLAN
# =====================================================================
def build_qubo_for_config(cfg):
    priorities = cfg["priority"]
    penalty = max(priorities.values()) * max(route_minutes.values()) + 1.0

    settings = pf.PathFindingQuboGeneratorSettings(
        encoding_type=pf.EncodingType.ONE_HOT,
        n_paths=s1.N_PATHS,
        max_path_length=s1.N_POSITIONS,
        loops=False,
    )
    gen = pf.PathFindingQuboGenerator(
        objective_function=pf.MinimizePathLength(path_ids=list(s1.VEHICLES)),
        graph=graph,
        settings=settings,
    )

    gen.add_constraint(pf.PathIsValid(path_ids=list(s1.VEHICLES)), weight=penalty)
    for p in s1.VEHICLES:
        for pos in range(1, s1.N_POSITIONS + 1):
            gen.add_constraint(
                pf.PathPositionIs(position=pos, vertex_ids=graph.all_vertices, path=p),
                weight=penalty,
            )
        gen.add_constraint(pf.PathStartsAt(vertex_ids=[START], path=p), weight=penalty)
        gen.add_constraint(
            pf.PathPositionIs(position=s1.N_POSITIONS, vertex_ids=[END], path=p), weight=penalty
        )

    for p, k in priorities.items():
        if k > 1.0:
            gen.add_constraint(pf.MinimizePathLength(path_ids=[p]), weight=k - 1.0)

    gen.add_constraint(
        pf.PathPositionIs(position=2, vertex_ids=[MAIN], path=s1.TRAM), weight=penalty
    )

    for p, limit in cfg["deadline_min"].items():
        fast_nodes = [n for n, t in route_minutes.items() if t <= limit + 1e-9]
        gen.add_constraint(
            pf.PathPositionIs(position=2, vertex_ids=fast_nodes, path=p),
            weight=cfg["deadline_penalty"],
        )

    Q_lib = np.asarray(gen.construct_qubo_matrix(), dtype=float)
    n_vars = gen.get_encoding_variable_count()
    offset = float(gen.get_cost([0] * n_vars))

    Q = Q_lib.copy()
    for a, b in cfg["conflict_pairs"]:
        for node in route_minutes:
            i = s1.var_index(a, 2, node, N_V)
            j = s1.var_index(b, 2, node, N_V)
            Q[min(i, j), max(i, j)] += cfg["conflict_weight"]

    return Q, offset, penalty


def plan_bits(plan):
    n = s1.N_PATHS * s1.N_POSITIONS * N_V
    bits = np.zeros(n, dtype=int)
    for vehicle, node in zip(s1.VEHICLES, plan):
        for position, v in enumerate([START, node, END], start=1):
            bits[s1.var_index(vehicle, position, v, N_V)] = 1
    return bits


def inspect_bits(bits):
    slots = np.asarray(bits, dtype=int).reshape(s1.N_PATHS, s1.N_POSITIONS, N_V)
    if not np.all(slots.sum(axis=2) == 1):
        return None
    route = slots.argmax(axis=2) + 1
    if not (np.all(route[:, 0] == START) and np.all(route[:, -1] == END)):
        return None
    if not all(int(v) in route_minutes for v in route[:, 1]):
        return None
    if int(route[s1.TRAM - 1, 1]) != MAIN:
        return None
    return tuple(int(v) for v in route[:, 1])


def describe_plan(plan, cfg):
    choice = dict(zip(s1.VEHICLES, plan))
    deadline_ok = all(
        route_minutes[choice[p]] <= lim + 1e-9 for p, lim in cfg["deadline_min"].items()
    )
    conflicts = sum(choice[a] == choice[b] for a, b in cfg["conflict_pairs"])

    winners = [s1.VEHICLES[p] for p in s1.VEHICLES if choice[p] == MAIN]
    if choice[3] == NORTH and deadline_ok:
        winners.append("Dialysis(On Time)")
    if choice[4] == NORTH:
        winners.append("Van(Fast Bypass)")

    losers = []
    if not deadline_ok:
        losers.append(f"Dialysis(MISSED {cfg['deadline_min'][3]}m DEADLINE -> {route_minutes[choice[3]]}m)")
    if choice[1] != MAIN:
        losers.append(f"Ambulance(+{round(route_minutes[choice[1]] - route_minutes[MAIN], 1)}m Detour)")
    if choice[4] == SOUTH:
        losers.append(f"Van(+{round(route_minutes[SOUTH] - route_minutes[MAIN], 1)}m South Detour)")
    if conflicts > 0:
        losers.append(f"{conflicts} Shared-Route Conflict(s)")

    return {
        "text": ", ".join(f"{s1.VEHICLES[p]}:{SHORT[choice[p]]}" for p in s1.VEHICLES),
        "deadline_met": deadline_ok,
        "conflicts": conflicts,
        "winners": ", ".join(winners),
        "losers": ", ".join(losers) if losers else "None",
    }


def main():
    sampler = SimulatedAnnealingSampler()
    summary_rows = []
    portfolio_json = {
        "corridor": "Albisriederplatz (ALBP) -> Stauffacher (STAU)",
        "routes": {
            "Main": {"name": "Main Spine (Badenerstrasse)", "minutes": route_minutes[MAIN], "stops": ["ALBP", "ZYPR", "LOCH", "KALK", "BEZI", "STAU"]},
            "North": {"name": "Northern Bypass (Helvetiaplatz)", "minutes": route_minutes[NORTH], "stops": ["ALBP", "GUTE", "HELV", "STAU"]},
            "South": {"name": "Southern Bypass (Wiedikon)", "minutes": route_minutes[SOUTH], "stops": ["ALBP", "SCHM", "WIED", "STAU"]},
        },
        "plans": {},
    }

    print("=" * 100)
    print("STEP 3: DECISION PORTFOLIO COMPARISON ACROSS 3 POLICY CONFIGURATIONS")
    print("=" * 100)

    for key, cfg in PORTFOLIO_CONFIGS.items():
        Q, offset, pen = build_qubo_for_config(cfg)
        n = len(Q)

        # Exact check over all 81 valid plans (with Tram on Main)
        ref = {}
        for plan in itertools.product(ROUTE_NODES, repeat=s1.N_PATHS):
            if plan[s1.TRAM - 1] != MAIN:
                continue
            x = plan_bits(plan)
            ref[plan] = float(x @ Q @ x + offset)

        ranked_plans = sorted(ref.items(), key=lambda item: item[1])
        best_plan, best_e = ranked_plans[0]
        second_plan, second_e = ranked_plans[1]
        gap = round(second_e - best_e, 2)
        info = describe_plan(best_plan, cfg)

        # Run 5 seeds of Simulated Annealing
        qubo_dict = {(i, j): float(Q[i, j]) for i in range(n) for j in range(i, n) if Q[i, j] != 0}
        bqm = dimod.BinaryQuadraticModel.from_qubo(qubo_dict, offset=offset)
        for i in range(n):
            bqm.add_variable(i, 0.0)

        hits = 0
        feasible_count = 0
        total_reads = len(SEEDS) * NUM_READS
        sampled_counts = Counter()

        for seed in SEEDS:
            state = random.getstate()
            try:
                random.seed(seed)
                sampleset = sampler.sample(bqm, num_reads=NUM_READS, num_sweeps=NUM_SWEEPS)
            finally:
                random.setstate(state)

            seed_hit = False
            for d in sampleset.data(fields=["sample", "energy", "num_occurrences"]):
                k = int(d.num_occurrences)
                p_tuple = inspect_bits([int(d.sample[i]) for i in range(n)])
                if p_tuple is not None:
                    feasible_count += k
                    sampled_counts[p_tuple] += k
                    if np.isclose(float(d.energy), best_e):
                        seed_hit = True
            if seed_hit:
                hits += 1

        print(f"\n[{cfg['name']}]")
        print(f"  Best Allocation : {info['text']}")
        print(f"  Exact Energy    : {best_e:.2f} (Runner-up: {second_e:.2f}, Gap: +{gap:.2f})")
        print(f"  Dialysis Status : {'ON TIME (6.5m <= 6.5m)' if info['deadline_met'] else 'MISSED DEADLINE (8.5m > 6.5m) [BOUGHT OFF!]'}")
        print(f"  Who Wins        : {info['winners']}")
        print(f"  Who Pays Price  : {info['losers']}")
        print(f"  Annealing Check : Optimum found in {hits}/5 seeds (Feasible reads: {feasible_count}/{total_reads})")

        # Store vehicle details for Step 4 plotting
        choice_map = dict(zip(s1.VEHICLES, best_plan))
        v_details = {}
        for p, v_name in s1.VEHICLES.items():
            r_node = choice_map[p]
            r_key = "Main" if r_node == MAIN else ("North" if r_node == NORTH else "South")
            t_min = route_minutes[r_node]
            detour = round(t_min - route_minutes[MAIN], 1)
            v_details[v_name] = {
                "route_key": r_key,
                "travel_min": t_min,
                "detour_min": detour,
                "occupancy": OCCUPANCY[p],
                "pax_delay_min": round(detour * OCCUPANCY[p], 1),
            }

        portfolio_json["plans"][key] = {
            "name": cfg["name"],
            "subtitle": cfg["subtitle"],
            "best_energy": round(best_e, 2),
            "runner_up_energy": round(second_e, 2),
            "gap": gap,
            "allocation_text": info["text"],
            "deadline_met": info["deadline_met"],
            "conflicts": info["conflicts"],
            "winners": info["winners"],
            "losers": info["losers"],
            "annealing_seeds_hit": f"{hits}/5",
            "feasible_fraction": round(feasible_count / total_reads, 3),
            "vehicles": v_details,
        }

        summary_rows.append({
            "Plan": cfg["name"].split(":")[0],
            "Ambulance": SHORT[choice_map[1]],
            "Tram (185p)": SHORT[choice_map[2]],
            "Dialysis (<=6.5m)": SHORT[choice_map[3]] + (" [OK]" if info["deadline_met"] else " [LATE!]"),
            "Delivery Van": SHORT[choice_map[4]],
            "Conflicts": info["conflicts"],
            "SA Hit": f"{hits}/5",
            "Who Pays the Price": info["losers"],
        })

    df_sum = pd.DataFrame(summary_rows)
    pd.set_option("display.width", 240, "display.max_colwidth", 90)
    print("\n" + "=" * 100)
    print("HEAD OF PLANNING DECISION PORTFOLIO TABLE")
    print("=" * 100)
    print(df_sum.to_string(index=False))

    out_file = s1.ROOT / "decision_portfolio.json"
    out_file.write_text(json.dumps(portfolio_json, indent=2), encoding="utf-8")
    print(f"\n[SUCCESS] Saved complete portfolio to {out_file}")


if __name__ == "__main__":
    main()