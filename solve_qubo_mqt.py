"""
solve_qubo_mqt.py  --  STEP 1: build the QUBO and check it (no solver yet)
Contested Network Allocation: Zurich Morning Peak Corridor

Written against MQT ProblemSolver 0.5.0, following Pathfinder_Introduction.ipynb.
"""
import inspect
import itertools
import json
from pathlib import Path

import numpy as np

import mqt.problemsolver.qubo_tools.pathfinder as pf

# =====================================================================
# 1. CONFIG -- every decision we have made lives here
# =====================================================================
ROOT = Path("/Users/koustav/Documents/QST hackathon/")
GRAPH_FILE = ROOT / "corridor_graph.json"

# Vertex IDs exactly as they appear in mqt_macro_graph (asserted against the file below).
START_NAME, END_NAME = "1", "5"
N_POSITIONS = 3                         # start, one route node, end

VEHICLES = {1: "Ambulance", 2: "Tram", 3: "Dialysis", 4: "Van"}   # path id -> name
N_PATHS = len(VEHICLES)
TRAM = 2

# Plan 2 (recommended). Plans 1 and 3 will only change these numbers.
# A vehicle's travel time is multiplied by its priority (must be >= 1).
PRIORITY = {1: 30.0, 2: 1.0, 3: 8.0, 4: 1.0}   # ambulance 10 -> 30
DEADLINE_MIN = {3: 6.5}          # dialysis must arrive within 6.5 min
DEADLINE_PENALTY = 50.0
# Pairs that should NOT share a route. OUR MODELLING DECISION: justify in the Decision Log.
# Charged as CONFLICT_WEIGHT once per pair that picks the same route (see add_conflict_terms).
CONFLICT_PAIRS = [(1, 3), (3, 4), (4, 2), (4, 1)]
CONFLICT_WEIGHT = 40.0                          # 20 -> 40


PROBE = False   # set True to print the real signatures of the pf.* classes we use


def print_signatures():
    names = ["Graph", "PathFindingQuboGeneratorSettings", "PathFindingQuboGenerator",
             "MinimizePathLength", "PathIsValid", "PathPositionIs", "PathStartsAt"]
    for name in names:
        obj = getattr(pf, name, None)
        print(f"{name}: {inspect.signature(obj) if obj else 'NOT FOUND'}")


# =====================================================================
# 2. LOAD corridor_graph.json  ->  pf.Graph
# =====================================================================
def load_macro_edges(path):
    """Return [(from_name, to_name, minutes), ...] from the 'mqt_macro_graph' entry."""
    data = json.loads(path.read_text())
    print("Top-level keys:", list(data.keys()))
    macro = data["mqt_macro_graph"]
    print("mqt_macro_graph keys:", list(macro))
    print("start_vertex:", macro["start_vertex"], "| end_vertex:", macro["end_vertex"])
    print("vertex_names:", macro["vertex_names"])
    print("route_summary:", macro["route_summary"])
    assert str(macro["start_vertex"]) == START_NAME and str(macro["end_vertex"]) == END_NAME, \
        "START_NAME / END_NAME in the config do not match the JSON"
    vertex_names = macro["vertex_names"]
    raw = macro["edges"]
    edges = []
    for e in raw:
        if isinstance(e, dict):   # tolerate a few common key spellings
            u = e.get("source", e.get("from", e.get("u")))
            v = e.get("target", e.get("to", e.get("v")))
            w = e.get("weight", e.get("minutes", e.get("time", e.get("w"))))
        else:                     # or plain [u, v, w] rows
            u, v, w = e
        edges.append((str(u), str(v), float(w)))
    print("Edges read:", edges)
    return edges, vertex_names


def label_for(vertex_names, raw_id):
    """Human-readable name for a file vertex ID (display only)."""
    try:
        if isinstance(vertex_names, dict):
            return str(vertex_names.get(str(raw_id), raw_id))
        if isinstance(vertex_names, list):
            return str(vertex_names[int(raw_id) - 1])   # assumes list is in vertex order 1..n
    except (IndexError, ValueError):
        pass
    return str(raw_id)


def build_graph(named_edges, vertex_names):
    """Give vertices Pathfinder IDs: 1 = start, 2..4 = route nodes (fastest first), 5 = end.

    NOTE: this renumbers the middle vertices. In the file, vertex 2 is the 6.5-min route and
    vertex 3 is the 5.1-min route; in Pathfinder they become 3 and 2 respectively.
    """
    minutes = {(u, v): m for u, v, m in named_edges}
    middles = sorted({v for (u, v) in minutes if u == START_NAME})
    assert len(middles) == 3, f"Expected 3 route nodes after {START_NAME}, found {middles}"
    total = {m: minutes[(START_NAME, m)] + minutes[(m, END_NAME)] for m in middles}
    ordered = sorted(middles, key=total.get)                  # Main, North, South
    ids = {START_NAME: 1}
    ids.update({m: i + 2 for i, m in enumerate(ordered)})
    ids[END_NAME] = len(ordered) + 2
    edges = [(ids[u], ids[v], m) for (u, v), m in minutes.items()]
    graph = pf.Graph(len(ids), edges)
    route_minutes = {ids[m]: total[m] for m in ordered}       # route node id -> total minutes
    labels = {ids[n]: label_for(vertex_names, n) for n in ids}   # Pathfinder ID -> display name
    print("file ID -> Pathfinder ID:", ids)
    for n in ordered:
        print(f"  file vertex {n} ({labels[ids[n]]}) -> Pathfinder vertex {ids[n]}, "
              f"route total {route_minutes[ids[n]]:g} min")
    return graph, ids, route_minutes, labels


# =====================================================================
# 3. BUILD the generator (objective + every rule)
# =====================================================================
def build_generator(graph, ids, route_minutes, penalty):
    start, end = ids[START_NAME], ids[END_NAME]
    main_id = min(route_minutes, key=route_minutes.get)       # fastest route = Main Spine
    assert all(k >= 1 for k in PRIORITY.values()), "Priorities must be >= 1"

    settings = pf.PathFindingQuboGeneratorSettings(
        encoding_type=pf.EncodingType.ONE_HOT,
        n_paths=N_PATHS,
        max_path_length=N_POSITIONS,
        loops=False,
    )
    # Objective: every vehicle pays its own travel time once.
    gen = pf.PathFindingQuboGenerator(
        objective_function=pf.MinimizePathLength(path_ids=list(VEHICLES)),
        graph=graph,
        settings=settings,
    )

    # (a) Structural validity: copied from the notebook, once per vehicle.
    gen.add_constraint(pf.PathIsValid(path_ids=list(VEHICLES)), weight=penalty)
    for p in VEHICLES:
        for position in range(1, N_POSITIONS + 1):
            gen.add_constraint(
                pf.PathPositionIs(position=position, vertex_ids=graph.all_vertices, path=p),
                weight=penalty)
        gen.add_constraint(pf.PathStartsAt(vertex_ids=[start], path=p), weight=penalty)
        gen.add_constraint(
            pf.PathPositionIs(position=N_POSITIONS, vertex_ids=[end], path=p), weight=penalty)

    # (b) Priority: extra weight on top of the unit travel cost above.
    for p, k in PRIORITY.items():
        if k > 1:
            gen.add_constraint(pf.MinimizePathLength(path_ids=[p]), weight=k - 1)

    # (c) Tram is rail-bound: its middle node must be the Main Spine (hard-ish, weight = penalty).
    gen.add_constraint(
        pf.PathPositionIs(position=2, vertex_ids=[main_id], path=TRAM), weight=penalty)

    # (d) Deadline: middle node must be one whose route fits inside the limit (soft).
    for p, limit in DEADLINE_MIN.items():
        fast_nodes = [n for n, t in route_minutes.items() if t <= limit + 1e-9]
        gen.add_constraint(
            pf.PathPositionIs(position=2, vertex_ids=fast_nodes, path=p),
            weight=DEADLINE_PENALTY)

    return gen




# ---------------------------------------------------------------------
# Conflicts, added by hand.
# pf.PathsShareNoEdges adds ~29 helper variables per call (it is a 4-variable product),
# which breaks the 60-variable layout. In our hub-and-spoke network, two vehicles share
# edges exactly when they choose the same route node at position 2, so the rule is just
# the quadratic term  x[a, pos 2, v] * x[b, pos 2, v]  for each route node v.
# ---------------------------------------------------------------------
def var_index(path, position, vertex, n_vertices):
    """Flat index of x[path, position, vertex]; all arguments 1-based. Layout: path, position, vertex."""
    return ((path - 1) * N_POSITIONS + (position - 1)) * n_vertices + (vertex - 1)


def add_conflict_terms(Q, ids, route_minutes):
    n_v = len(ids)
    Q = Q.copy()
    for a, b in CONFLICT_PAIRS:
        for node in route_minutes:                      # the three route-node IDs
            i = var_index(a, 2, node, n_v)
            j = var_index(b, 2, node, n_v)
            Q[min(i, j), max(i, j)] += CONFLICT_WEIGHT  # keep Q upper-triangular
    return Q

# =====================================================================
# 4. CHECK the QUBO against a formula we wrote ourselves
#    2^60 bitstrings is too many to enumerate, but only 3^4 = 81 combinations
#    of "which route does each vehicle take" are structurally valid.
# =====================================================================
def check_feasible_assignments(gen, Q_lib, Q, offset, ids, route_minutes, penalty, labels):
    n_v = len(ids)
    start, end = ids[START_NAME], ids[END_NAME]
    main_id = min(route_minutes, key=route_minutes.get)
    rows = []
    for nodes in itertools.product(sorted(route_minutes), repeat=N_PATHS):
        choice = dict(zip(VEHICLES, nodes))                   # vehicle id -> route node id
        routes = [[start, choice[p], end] for p in VEHICLES]
        bits = np.zeros(N_PATHS * N_POSITIONS * n_v, dtype=int)
        for p in VEHICLES:
            for position, v in enumerate(routes[p - 1], start=1):
                bits[var_index(p, position, v, n_v)] = 1
        decoded = gen.decode_bit_array(bits.tolist())
        assert decoded == routes, (
            f"Bit layout assumption is wrong.\nI built {routes}\nlibrary decoded {decoded}")

        # (1) our reading of Q must agree with the library's own cost function
        lib_energy = float(gen.get_cost(bits.tolist()))
        assert np.isclose(bits @ Q_lib @ bits + offset, lib_energy), \
            f"x.T Q x + offset != get_cost for {choice}"

        # (2) the full QUBO (library part + our conflict terms) must match a plain formula
        energy = float(bits @ Q @ bits + offset)
        expected = sum(PRIORITY[p] * route_minutes[choice[p]] for p in VEHICLES)
        if choice[TRAM] != main_id:
            expected += penalty
        for p, limit in DEADLINE_MIN.items():
            if route_minutes[choice[p]] > limit + 1e-9:
                expected += DEADLINE_PENALTY
        n_shared = sum(choice[a] == choice[b] for a, b in CONFLICT_PAIRS)
        expected += CONFLICT_WEIGHT * n_shared
        assert np.isclose(energy, expected), (
            f"QUBO energy {energy:g} != formula {expected:g} for {choice} "
            f"(library part {lib_energy:g}, conflicts {n_shared})")
        rows.append((energy, n_shared, choice))
    print(f"Checked {len(rows)} valid assignments: the QUBO matches our formula.")

    print("\nLowest-energy valid assignments (sanity check, NOT the solver):")
    for energy, n_shared, choice in sorted(rows, key=lambda r: r[0])[:5]:
        label = ", ".join(f"{VEHICLES[p]}->{labels[n]}({route_minutes[n]:g}m)"
                          for p, n in choice.items())
        print(f"  {energy:8.2f}  conflicts={n_shared}  {label}")


# =====================================================================
# 5. RUN
# =====================================================================
if __name__ == "__main__":
    if PROBE:
        print_signatures()

    named_edges, vertex_names = load_macro_edges(GRAPH_FILE)
    graph, ids, route_minutes, labels = build_graph(named_edges, vertex_names)

    # Penalty must beat the most a vehicle could "save" by breaking a structural rule.
    PENALTY = max(PRIORITY.values()) * max(route_minutes.values()) + 1
    print(f"\nPENALTY = {PENALTY:g}")

    gen = build_generator(graph, ids, route_minutes, PENALTY)
    Q_lib = np.asarray(gen.construct_qubo_matrix(), dtype=float)
    n_vars = gen.get_encoding_variable_count()
    expected_vars = N_PATHS * N_POSITIONS * len(ids)
    assert Q_lib.shape == (expected_vars, expected_vars) and n_vars == expected_vars, \
        f"Unexpected size {Q_lib.shape} (expected {expected_vars}); a constraint is adding helper variables"
    assert np.allclose(Q_lib, np.triu(Q_lib)), "Expected upper-triangular MQT convention"
    offset = float(gen.get_cost([0] * n_vars))

    Q = add_conflict_terms(Q_lib, ids, route_minutes)
    print(f"QUBO: {n_vars} variables, {np.count_nonzero(Q)} non-zero entries, offset {offset:g}")
    print("Energy convention: H(x) = x.T @ Q @ x + offset (upper-triangular Q, no doubling)")

    check_feasible_assignments(gen, Q_lib, Q, offset, ids, route_minutes, PENALTY, labels)
    np.savez(ROOT / "qubo_plan2.npz", Q=Q, offset=offset)
    print("\nSaved qubo_plan2.npz")