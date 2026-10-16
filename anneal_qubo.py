#!/usr/bin/env python3
"""
anneal_qubo.py  --  STEP 2 (Improved): Simulated annealing on the Plan 2 QUBO
Contested Network Allocation: Zurich Morning Peak Corridor

Improvements over base Step 2:
1. Passes `seed=seed` directly to dimod's sampler for strict reproducibility.
2. Uses NUM_READS = 50 (250 total samples in ~2.5s) for a richer solution distribution.
3. Explicitly labels 'Who Wins' and 'Who Pays the Price' in the distribution table
   to test the hackathon's 'Solutions as a distribution' hypothesis for human planners.
4. Tracks whether the rail-bound Tram stayed on the Main Spine tracks.
"""
import contextlib
import io
import itertools
import random
import time
from collections import Counter

import dimod
import numpy as np
import pandas as pd
from dimod import SimulatedAnnealingSampler

import solve_qubo_mqt as s1  # Step 1: config, graph loading, var_index

# =====================================================================
# 1. CONFIG
# =====================================================================
SEEDS = [0, 1, 2, 3, 4]      # 5 independent batches
NUM_READS = 50               # 50 annealing reads per seed (250 total reads, ~2s total)
NUM_SWEEPS = 1000            # sweeps per read

# =====================================================================
# 2. LOAD the QUBO from Step 1 and rebuild the vertex bookkeeping
# =====================================================================
data = np.load(s1.ROOT / "qubo_plan2.npz")
Q, offset = data["Q"], float(data["offset"])
n = len(Q)

with contextlib.redirect_stdout(io.StringIO()):  # silence Step 1's printouts
    _edges, _names = s1.load_macro_edges(s1.GRAPH_FILE)
    graph, ids, route_minutes, labels = s1.build_graph(_edges, _names)

N_V = len(ids)
START, END = ids[s1.START_NAME], ids[s1.END_NAME]
ROUTE_NODES = sorted(route_minutes)  # Pathfinder IDs 2 (Main 5.1m), 3 (North 6.5m), 4 (South 8.5m)
MAIN, NORTH, SOUTH = ROUTE_NODES[0], ROUTE_NODES[1], ROUTE_NODES[2]
SHORT = {
    MAIN: f"Main({route_minutes[MAIN]:g}m)",
    NORTH: f"North({route_minutes[NORTH]:g}m)",
    SOUTH: f"South({route_minutes[SOUTH]:g}m)",
}

assert n == s1.N_PATHS * s1.N_POSITIONS * N_V, "QUBO size does not match the Step 1 config"
assert [route_minutes[v] for v in ROUTE_NODES] == sorted(route_minutes.values())


def plan_bits(plan):
    bits = np.zeros(n, dtype=int)
    for vehicle, node in zip(s1.VEHICLES, plan):
        for position, v in enumerate([START, node, END], start=1):
            bits[s1.var_index(vehicle, position, v, N_V)] = 1
    return bits


# =====================================================================
# 3. EXACT REFERENCE: energy of all 3^4 = 81 valid plans
# =====================================================================
REFERENCE = {}
for plan in itertools.product(ROUTE_NODES, repeat=s1.N_PATHS):
    x = plan_bits(plan)
    REFERENCE[plan] = float(x @ Q @ x + offset)
REF_OPT = min(REFERENCE.values())
REF_BEST_PLAN = min(REFERENCE, key=REFERENCE.get)


def describe(plan):
    choice = dict(zip(s1.VEHICLES, plan))
    tram_ok = (choice[s1.TRAM] == MAIN)
    deadline_ok = all(
        route_minutes[choice[p]] <= lim + 1e-9 for p, lim in s1.DEADLINE_MIN.items()
    )
    conflicts = sum(choice[a] == choice[b] for a, b in s1.CONFLICT_PAIRS)

    # Identify human winners (fastest route 5.1m) and losers (slow detour 8.5m or missed deadline)
    winners = [s1.VEHICLES[p] for p in s1.VEHICLES if choice[p] == MAIN]
    losers = []
    for p in s1.VEHICLES:
        if p in s1.DEADLINE_MIN and route_minutes[choice[p]] > s1.DEADLINE_MIN[p] + 1e-9:
            losers.append(f"{s1.VEHICLES[p]}(MISSED DEADLINE)")
        elif choice[p] == SOUTH:
            losers.append(f"{s1.VEHICLES[p]}(+3.4m South)")
        elif choice[p] == NORTH and p == 1:
            losers.append("Ambulance(+1.4m North)")
    if conflicts > 0:
        losers.append(f"{conflicts} Route Conflict(s)")

    return dict(
        plan_text=", ".join(f"{s1.VEHICLES[p]}:{SHORT[choice[p]]}" for p in s1.VEHICLES),
        tram_on_main=tram_ok,
        deadline_met=deadline_ok,
        conflicts=conflicts,
        who_wins=", ".join(winners) if winners else "None",
        who_pays=", ".join(losers) if losers else "None",
    )


# =====================================================================
# 4. INSPECT a bitstring without trusting the QUBO
# =====================================================================
def inspect_bits(bits):
    """Return (plan, 'OK') for a structurally valid sample, else (None, reason)."""
    slots = np.asarray(bits, dtype=int).reshape(s1.N_PATHS, s1.N_POSITIONS, N_V)
    if not np.all(slots.sum(axis=2) == 1):
        return None, "not one place per position"
    route = slots.argmax(axis=2) + 1  # shape (vehicles, positions)
    if not (np.all(route[:, 0] == START) and np.all(route[:, -1] == END)):
        return None, "wrong start or end"
    if not all(int(v) in route_minutes for v in route[:, 1]):
        return None, "missing edge (start/end used at pos 2)"
    if int(route[s1.TRAM - 1, 1]) != MAIN:
        return None, "tram off rails (left Main Spine)"
    return tuple(int(v) for v in route[:, 1]), "OK"


# =====================================================================
# 5. BUILD the dimod model and the sampling helpers
# =====================================================================
qubo = {(i, j): float(Q[i, j]) for i in range(n) for j in range(i, n) if Q[i, j] != 0}
bqm = dimod.BinaryQuadraticModel.from_qubo(qubo, offset=offset)
for i in range(n):
    bqm.add_variable(i, 0.0)


def sample_with_seed(sampler, bqm, seed, **settings):
    state = random.getstate()
    try:
        random.seed(seed)
        return sampler.sample(bqm, seed=seed, **settings)
    finally:
        random.setstate(state)


def summarise(sampleset, seconds, seed):
    plans, reasons = Counter(), Counter()
    total = feasible = optimal = 0
    best_energy, best_plan = np.inf, None
    for d in sampleset.data(fields=["sample", "energy", "num_occurrences"]):
        k = int(d.num_occurrences)
        total += k
        plan, reason = inspect_bits([int(d.sample[i]) for i in range(n)])
        if plan is None:
            reasons[reason] += k
            continue
        feasible += k
        assert np.isclose(float(d.energy), REFERENCE[plan]), (
            f"sampler energy {d.energy} != reference {REFERENCE[plan]} for plan {plan}"
        )
        plans[plan] += k
        if np.isclose(float(d.energy), REF_OPT):
            optimal += k
        if d.energy < best_energy:
            best_energy, best_plan = float(d.energy), plan

    row = dict(
        seed=seed,
        seconds=round(seconds, 3),
        best_energy=round(best_energy, 2) if best_plan else np.nan,
        gap=round(best_energy - REF_OPT, 2) if best_plan else np.nan,
        feasible_frac=round(feasible / total, 3) if total else 0.0,
        optimal_frac=round(optimal / total, 3) if total else 0.0,
        found_optimum=bool(optimal),
        best_plan=describe(best_plan)["plan_text"] if best_plan else None,
    )
    return row, plans, reasons


# =====================================================================
# 6. RUN
# =====================================================================
if __name__ == "__main__":
    print(f"QUBO: {n} variables, offset {offset:g}")
    print(
        f"Exact optimum over the 81 valid plans: {REF_OPT:.2f}  ->  "
        f"{describe(REF_BEST_PLAN)['plan_text']}"
    )
    ranked = sorted(REFERENCE.values())
    print(f"Runner-up energy: {ranked[1]:.2f} (gap +{ranked[1] - ranked[0]:.2f})\n")

    sampler = SimulatedAnnealingSampler()
    rows, all_plans, all_reasons = [], Counter(), Counter()
    for seed in SEEDS:
        started = time.perf_counter()
        sampleset = sample_with_seed(
            sampler, bqm, seed, num_reads=NUM_READS, num_sweeps=NUM_SWEEPS
        )
        elapsed = time.perf_counter() - started
        row, plans, reasons = summarise(sampleset, elapsed, seed)
        rows.append(row)
        all_plans.update(plans)
        all_reasons.update(reasons)
        print(
            f"seed {seed}: {elapsed:.2f}s | feasible {row['feasible_frac']:.0%} | "
            f"optimal {row['optimal_frac']:.0%} | gap {row['gap']:+.2f}",
            flush=True,
        )

    runs = pd.DataFrame(rows)
    pd.set_option("display.width", 220, "display.max_colwidth", 90)
    print("\n--- Per-seed results ---")
    print(runs.to_string(index=False))

    total_reads = NUM_READS * len(SEEDS)
    total_feasible = sum(all_plans.values())
    print("\n--- Summary ---")
    print(f"Batches that contain the exact optimum : {int(runs.found_optimum.sum())} of {len(runs)}")
    print(f"Mean share of reads that are valid     : {runs.feasible_frac.mean():.1%}")
    print(f"Mean share of reads at the optimum     : {runs.optimal_frac.mean():.1%}")
    if all_reasons:
        print("Why the other reads were invalid       :", dict(all_reasons))

    table = pd.DataFrame([
        dict(
            plan=describe(p)["plan_text"],
            energy=round(REFERENCE[p], 2),
            gap=round(REFERENCE[p] - REF_OPT, 2),
            reads=k,
            share_of_valid=round(k / total_feasible, 3),
            deadline_met=describe(p)["deadline_met"],
            conflicts=describe(p)["conflicts"],
            who_pays_the_price=describe(p)["who_pays"],
        )
        for p, k in all_plans.most_common(8)
    ])
    print(f"\n--- Distribution of Feasible Plans Returned ({total_feasible}/{total_reads} valid reads, top 8) ---")
    print(table.to_string(index=False) if len(table) else "No valid plan was found.")

    runs.to_csv(s1.ROOT / "anneal_plan2_runs.csv", index=False)
    table.to_csv(s1.ROOT / "anneal_plan2_plans.csv", index=False)
    print("\nSaved anneal_plan2_runs.csv and anneal_plan2_plans.csv")