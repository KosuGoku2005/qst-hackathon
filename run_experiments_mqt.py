#!/usr/bin/env python3
"""
run_experiments_mqt.py  --  STEPS 2 & 3:
1. Runs Simulated Annealing (dimod) across 5 seeds on the 60-variable MQT Pathfinder QUBO.
2. Evaluates the 3 Decision Portfolio Plans (Plan 1: Buy-Off Trap, Plan 2: Recommended Equity,
   Plan 3: Strict Spine Conflict / Disruption).
3. Compares MQT ProblemSolver Encodings (ONE_HOT vs DOMAIN_WALL vs BINARY) for the Findings Note.
4. Exports results to decision_portfolio.json for Format A visualization.
"""

import itertools
import json
import random
import time
from pathlib import Path

import dimod
from dimod import SimulatedAnnealingSampler
import numpy as np
import pandas as pd
import mqt.problemsolver.qubo_tools.pathfinder as pf

ROOT = Path(__file__).resolve().parent
GRAPH_FILE = ROOT / "corridor_graph.json"

START_NAME, END_NAME = "1", "5"
N_POSITIONS = 3
VEHICLES = {1: "Ambulance", 2: "Tram (185 Pax)", 3: "Dialysis", 4: "Delivery Van"}
OCCUPANCY = {1: 2, 2: 185, 3: 1, 4: 1}
N_PATHS = len(VEHICLES)
TRAM = 2


# =====================================================================
# 1. LOAD MACRO GRAPH (with clean labels)
# =====================================================================
def load_and_build_graph(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    macro = data["mqt_macro_graph"]
    vertex_names = macro["vertex_names"]
    raw_edges = macro["edges"]

    minutes = {(str(u), str(v)): float(w) for u, v, w in raw_edges}
    middles = sorted({v for (u, v) in minutes if u == START_NAME})
    total = {m: minutes[(START_NAME, m)] + minutes[(m, END_NAME)] for m in middles}
    ordered = sorted(middles, key=total.get)  # Fastest first: Main (5.1m), North (6.5m), South (8.5m)

    ids = {START_NAME: 1}
    ids.update({m: i + 2 for i, m in enumerate(ordered)})
    ids[END_NAME] = len(ordered) + 2

    edges = [(ids[u], ids[v], m) for (u, v), m in minutes.items()]
    graph = pf.Graph(len(ids), edges)
    route_minutes = {ids[m]: round(total[m], 2) for m in ordered}

    # Strip duplicate "(5.1m)" suffix from display labels
    labels = {}
    for raw_id, pf_id in ids.items():
        raw_label = str(vertex_names.get(str(raw_id), raw_id))
        clean_label = raw_label.split(" (")[0]
        labels[pf_id] = clean_label

    return graph, ids, route_minutes, labels


# =====================================================================
# 2. BUILD QUBO FOR ANY PLAN CONFIGURATION
# =====================================================================
def var_index(path: int, position: int, vertex: int, n_vertices: int) -> int:
    return ((path - 1) * N_POSITIONS + (position - 1)) * n_vertices + (vertex - 1)


def build_plan_qubo(graph, ids, route_minutes, config: dict):
    start, end = ids[START_NAME], ids[END_NAME]
    main_id = min(route_minutes, key=route_minutes.get)
    priorities = config["priority"]
    deadline_min = config["deadline_min"]
    deadline_penalty = config["deadline_penalty"]
    conflict_pairs = config["conflict_pairs"]
    conflict_weight = config["conflict_weight"]
    blocked_nodes = config.get("blocked_nodes", [])

    penalty = max(priorities.values()) * max(route_minutes.values()) + 50.0

    settings = pf.PathFindingQuboGeneratorSettings(
        encoding_type=pf.EncodingType.ONE_HOT,
        n_paths=N_PATHS,
        max_path_length=N_POSITIONS,
        loops=False,
    )
    gen = pf.PathFindingQuboGenerator(
        objective_function=pf.MinimizePathLength(path_ids=list(VEHICLES)),
        graph=graph,
        settings=settings,
    )

    # (a) Structural route validity
    gen.add_constraint(pf.PathIsValid(path_ids=list(VEHICLES)), weight=penalty)
    for p in VEHICLES:
        for pos in range(1, N_POSITIONS + 1):
            gen.add_constraint(
                pf.PathPositionIs(position=pos, vertex_ids=graph.all_vertices, path=p),
                weight=penalty,
            )
        gen.add_constraint(pf.PathStartsAt(vertex_ids=[start], path=p), weight=penalty)
        gen.add_constraint(
            pf.PathPositionIs(position=N_POSITIONS, vertex_ids=[end], path=p), weight=penalty
        )

    # (b) Priority weights
    for p, k in priorities.items():
        if k > 1.0:
            gen.add_constraint(pf.MinimizePathLength(path_ids=[p]), weight=k - 1.0)

    # (c) Tram locked to Main Spine rails
    gen.add_constraint(
        pf.PathPositionIs(position=2, vertex_ids=[main_id], path=TRAM), weight=penalty
    )

    # (d) Medical deadline constraint
    for p, limit in deadline_min.items():
        fast_nodes = [
            n for n, t in route_minutes.items()
            if t <= limit + 1e-9 and n not in blocked_nodes
        ]
        if fast_nodes:
            gen.add_constraint(
                pf.PathPositionIs(position=2, vertex_ids=fast_nodes, path=p),
                weight=deadline_penalty,
            )

    # (e) Optional disruption: block a route node
    if blocked_nodes:
        allowed_nodes = [n for n in route_minutes if n not in blocked_nodes]
        for p in VEHICLES:
            gen.add_constraint(
                pf.PathPositionIs(position=2, vertex_ids=allowed_nodes, path=p),
                weight=penalty,
            )

    Q_lib = np.asarray(gen.construct_qubo_matrix(), dtype=float)
    n_vars = gen.get_encoding_variable_count()
    offset = float(gen.get_cost([0] * n_vars))

    # Add pairwise route conflict terms directly to upper-triangular Q
    n_v = len(ids)
    Q = Q_lib.copy()
    for a, b in conflict_pairs:
        for node in route_minutes:
            i = var_index(a, 2, node, n_v)
            j = var_index(b, 2, node, n_v)
            Q[min(i, j), max(i, j)] += conflict_weight

    # Convert to dimod BQM
    qubo_dict = {(i, j): float(Q[i, j]) for i in range(n_vars) for j in range(i, n_vars) if Q[i, j] != 0}
    bqm = dimod.BinaryQuadraticModel.from_qubo(qubo_dict, offset=offset)
    for i in range(n_vars):
        bqm.add_variable(i, 0.0)

    return gen, Q, offset, bqm, penalty


# =====================================================================
# 3. EXACT ENUMERATION OF 81 VALID ASSIGNMENTS & BITSTRING INSPECTOR
# =====================================================================
def evaluate_all_81_valid(Q, offset, ids, route_minutes, labels, config):
    n_v = len(ids)
    start, end = ids[START_NAME], ids[END_NAME]
    rows = []
    for nodes in itertools.product(sorted(route_minutes), repeat=N_PATHS):
        choice = dict(zip(VEHICLES, nodes))
        bits = np.zeros(N_PATHS * N_POSITIONS * n_v, dtype=int)
        for p in VEHICLES:
            for pos, v in enumerate([start, choice[p], end], start=1):
                bits[var_index(p, pos, v, n_v)] = 1
        energy = float(bits @ Q @ bits + offset)
        n_shared = sum(choice[a] == choice[b] for a, b in config["conflict_pairs"])
        dialysis_time = route_minutes[choice[3]]
        dialysis_ok = (dialysis_time <= config["deadline_min"][3] + 1e-9) and (
            choice[3] not in config.get("blocked_nodes", [])
        )
        rows.append({
            "energy": round(energy, 2),
            "conflicts": n_shared,
            "choice": choice,
            "dialysis_ok": dialysis_ok,
            "summary": ", ".join(
                f"{VEHICLES[p]}->{labels[n]} ({route_minutes[n]:g}m)" for p, n in choice.items()
            ),
        })
    rows.sort(key=lambda r: r["energy"])
    return rows


def inspect_multi_bits(bits, ids, route_minutes):
    """Checks if a 60-bit sample from Simulated Annealing is a valid 4-vehicle routing."""
    n_v = len(ids)
    start, end = ids[START_NAME], ids[END_NAME]
    main_id = min(route_minutes, key=route_minutes.get)
    arr = np.asarray(bits, dtype=int).reshape(N_PATHS, N_POSITIONS, n_v)

    # Every vehicle must pick exactly 1 vertex per position
    if not np.all(arr.sum(axis=2) == 1):
        return False, None
    choice = {}
    for p in VEHICLES:
        v_start = int(np.argmax(arr[p - 1, 0])) + 1
        v_mid = int(np.argmax(arr[p - 1, 1])) + 1
        v_end = int(np.argmax(arr[p - 1, 2])) + 1
        if v_start != start or v_end != end or v_mid not in route_minutes:
            return False, None
        choice[p] = v_mid
    # Tram must be on Main Spine
    if choice[TRAM] != main_id:
        return False, None
    return True, choice


# =====================================================================
# 4. SIMULATED ANNEALING ACROSS 5 SEEDS (Distribution & Feasibility)
# =====================================================================
def run_annealing_experiment(bqm, Q, offset, ids, route_minutes, labels, config, exact_best_energy):
    sampler = SimulatedAnnealingSampler()
    n_vars = len(Q)
    seed_rows = []
    dist_counter = {}

    for seed in [0, 1, 2, 3, 4]:
        state = random.getstate()
        started = time.perf_counter()
        try:
            random.seed(seed)
            sampleset = sampler.sample(bqm, num_reads=50, num_sweeps=1000, seed=seed)
        finally:
            random.setstate(state)
        elapsed = time.perf_counter() - started

        total_reads = 0
        feasible_reads = 0
        best_energy = np.inf
        best_choice = None

        for datum in sampleset.data(fields=["sample", "energy", "num_occurrences"]):
            bits = [int(datum.sample[i]) for i in range(n_vars)]
            occ = int(datum.num_occurrences)
            total_reads += occ
            ok, choice = inspect_multi_bits(bits, ids, route_minutes)
            if ok:
                feasible_reads += occ
                e = round(float(datum.energy), 2)
                key = tuple(choice[p] for p in VEHICLES)
                dist_counter[key] = dist_counter.get(key, 0) + occ
                if e < best_energy:
                    best_energy = e
                    best_choice = choice

        seed_rows.append({
            "seed": seed,
            "seconds": round(elapsed, 3),
            "best_energy": best_energy if best_choice else np.nan,
            "gap": round(best_energy - exact_best_energy, 2) if best_choice else np.nan,
            "feasible_fraction": round(feasible_reads / total_reads, 2),
            "found_optimum": bool(best_choice and np.isclose(best_energy, exact_best_energy)),
        })

    return pd.DataFrame(seed_rows), dist_counter


# =====================================================================
# 5. ENCODING COMPARISON (ONE_HOT vs DOMAIN_WALL vs BINARY)
# =====================================================================
def compare_encodings(graph, ids):
    start, end = ids[START_NAME], ids[END_NAME]
    rows = []
    for enc_name, enc_type in [
        ("ONE_HOT", pf.EncodingType.ONE_HOT),
        ("DOMAIN_WALL", pf.EncodingType.DOMAIN_WALL),
        ("BINARY", pf.EncodingType.BINARY),
    ]:
        settings = pf.PathFindingQuboGeneratorSettings(
            encoding_type=enc_type,
            n_paths=N_PATHS,
            max_path_length=N_POSITIONS,
            loops=False,
        )
        gen = pf.PathFindingQuboGenerator(
            objective_function=pf.MinimizePathLength(path_ids=list(VEHICLES)),
            graph=graph,
            settings=settings,
        )
        gen.add_constraint(pf.PathIsValid(path_ids=list(VEHICLES)), weight=256.0)
        for p in VEHICLES:
            gen.add_constraint(pf.PathStartsAt(vertex_ids=[start], path=p), weight=256.0)
            gen.add_constraint(
                pf.PathPositionIs(position=N_POSITIONS, vertex_ids=[end], path=p), weight=256.0
            )
        Q_mat = np.asarray(gen.construct_qubo_matrix(), dtype=float)
        rows.append({
            "encoding": enc_name,
            "encoding_vars": gen.get_encoding_variable_count(),
            "qubo_matrix_dim": Q_mat.shape[0],
            "auxiliary_vars_added": Q_mat.shape[0] - gen.get_encoding_variable_count(),
            "non_zero_couplings": int(np.count_nonzero(Q_mat)),
        })
    return pd.DataFrame(rows)


# =====================================================================
# 6. MAIN PORTFOLIO EXECUTION
# =====================================================================
def main():
    graph, ids, route_minutes, labels = load_and_build_graph(GRAPH_FILE)
    min_route = min(route_minutes.values())  # 5.1 min baseline

    PLANS = {
        "plan_1_utilitarian": {
            "title": "Plan 1: Commercial & Utilitarian Speed (Low Dialysis Penalty)",
            "description": "Prioritizes commercial van & aggregate speed with a weak medical penalty (P=10). The solver 'buys off' the dialysis patient onto the 8.5m Southern Detour.",
            "priority": {1: 30.0, 2: 1.0, 3: 2.0, 4: 15.0},
            "deadline_min": {3: 6.5},
            "deadline_penalty": 10.0,  # Too weak: Van saves 15*(8.5-6.5)=30 > 10+2*(8.5-6.5)=14!
            "conflict_pairs": [(1, 3), (3, 4), (4, 2), (4, 1)],
            "conflict_weight": 40.0,
        },
        "plan_2_recommended": {
            "title": "Plan 2: Inviolable Medical & Transit Equity (Recommended)",
            "description": "Enforces priority-preserving penalty (P=50) for Dialysis and Ambulance while keeping the 185-pax Tram on the fast spine. Delivery Van takes the Southern Bypass.",
            "priority": {1: 30.0, 2: 1.0, 3: 8.0, 4: 1.0},
            "deadline_min": {3: 6.5},
            "deadline_penalty": 50.0,  # Strong: Dialysis deadline cannot be bought off!
            "conflict_pairs": [(1, 3), (3, 4), (4, 2), (4, 1)],
            "conflict_weight": 40.0,
        },
        "plan_3_strict_spine": {
            "title": "Plan 3: Strict Single-Lane Spine (Ambulance vs. 185-Pax Tram Conflict)",
            "description": "Enforces conflict between Ambulance and Tram on the Main Spine ((1,2) added) with high mass-transit weight. Forces Ambulance or Dialysis to yield.",
            "priority": {1: 25.0, 2: 35.0, 3: 8.0, 4: 1.0},
            "deadline_min": {3: 6.5},
            "deadline_penalty": 50.0,
            "conflict_pairs": [(1, 2), (2, 3), (1, 3), (3, 4), (4, 2), (4, 1)],  # All 6 pairs conflict!
            "conflict_weight": 40.0,
        },
    }

    portfolio_out = {
        "metadata": {
            "route_minutes": {labels[k]: v for k, v in route_minutes.items()},
            "vehicles": VEHICLES,
        },
        "plans": {},
    }

    print("=" * 85)
    print("ZURICH CONTESTED CORRIDOR: MQT PROBLEMSOLVER + SIMULATED ANNEALING PORTFOLIO")
    print("=" * 85)

    for plan_key, cfg in PLANS.items():
        print(f"\n>>> {cfg['title']} <<<")
        gen, Q, offset, bqm, pen = build_plan_qubo(graph, ids, route_minutes, cfg)
        valid_81 = evaluate_all_81_valid(Q, offset, ids, route_minutes, labels, cfg)
        best = valid_81[0]
        runner_up = valid_81[1]
        gap_to_second = round(runner_up["energy"] - best["energy"], 2)

        print(f"  QUBO Variables: {len(Q)} | Energy Gap (Best vs 2nd Best): {gap_to_second:g}")
        print("  Top 3 Valid Allocations (Exact Check):")
        for rank, row in enumerate(valid_81[:3], start=1):
            d_tag = "ON TIME" if row["dialysis_ok"] else "MISSED DEADLINE [TRADED AWAY!]"
            print(f"    #{rank}: Energy={row['energy']:7.2f} | Conflicts={row['conflicts']} | Dialysis={d_tag}")
            print(f"        {row['summary']}")

        df_sa, dist_counter = run_annealing_experiment(
            bqm, Q, offset, ids, route_minutes, labels, cfg, best["energy"]
        )
        print("\n  Simulated Annealing (5 Seeds x 50 Reads = 250 Samples):")
        print(df_sa.to_string(index=False))

        # Build schedule details for JSON export
        sched = {}
        for p, v_name in VEHICLES.items():
            r_node = best["choice"][p]
            t_min = route_minutes[r_node]
            delay_vs_fastest = round(t_min - min_route, 2)
            sched[v_name] = {
                "route_node": int(r_node),
                "route_name": labels[r_node],
                "travel_min": t_min,
                "detour_delay_min": delay_vs_fastest,
                "pax_delay_min": round(delay_vs_fastest * OCCUPANCY[p], 1),
            }

        portfolio_out["plans"][plan_key] = {
            "title": cfg["title"],
            "description": cfg["description"],
            "best_energy": best["energy"],
            "runner_up_energy": runner_up["energy"],
            "energy_gap": gap_to_second,
            "dialysis_met_deadline": best["dialysis_ok"],
            "conflicts": best["conflicts"],
            "schedule": sched,
            "annealing_Optimum_Hit_Rate": f"{int(df_sa['found_optimum'].sum())}/5 seeds",
            "annealing_Mean_Feasible_Fraction": round(float(df_sa["feasible_fraction"].mean()), 2),
        }

    print("\n" + "=" * 85)
    print("VARIANT COMPARISON: MQT PROBLEMSOLVER ENCODINGS (ONE_HOT vs DOMAIN_WALL vs BINARY)")
    print("=" * 85)
    df_enc = compare_encodings(graph, ids)
    print(df_enc.to_string(index=False))
    portfolio_out["encoding_comparison"] = df_enc.to_dict(orient="records")

    out_path = ROOT / "decision_portfolio.json"
    out_path.write_text(json.dumps(portfolio_out, indent=2), encoding="utf-8")
    print(f"\n[SUCCESS] Exported complete portfolio & encoding metrics to: {out_path}")


if __name__ == "__main__":
    main()