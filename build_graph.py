#!/usr/bin/env python3
"""
build_graph.py
--------------
Builds a NetworkX directed graph (DiGraph) representing the heavily congested
Zurich transit corridor along Badenerstrasse (Freihofstrasse -> Paradeplatz route).

Assigns edge weights based on planned travel times (fahrzeiten) extracted from
Data/Traveltimes/fahrzeiten_soll_ist_*.csv.

Enriches the graph with:
  - Node metadata: Stop names, short codes, stop IDs, and GPS coordinates.
  - Edge metadata: Planned travel time (seconds & minutes), actual travel time,
    average departure delay, and transit lines operating on each segment.
  - Complete travel time matrix (for quantum TSP / QUBO formulations).

A selectable sub-network of 6 to 8 connected stops is supported, perfectly sized
for quantum solvers (e.g. 36 to 64 qubits in standard TSP QUBO / QAOA).
"""

from pathlib import Path
import argparse
import json
import networkx as nx
import pandas as pd
import numpy as np

# Ordered stops along the high-density Badenerstrasse transit corridor
# Ordered geographically from West (Freihofstrasse) to East (Paradeplatz):
CORRIDOR_STOPS_FULL = [
    {"code": "FREI", "name": "Zürich, Freihofstrasse",          "halt_id": 2253, "diva": 883},
    {"code": "LETG", "name": "Zürich, Letzigrund",              "halt_id": 2245, "diva": 1548},
    {"code": "ALBP", "name": "Zürich, Albisriederplatz",         "halt_id": 1535, "diva": 48},
    {"code": "ZYPR", "name": "Zürich, Zypressenstrasse",         "halt_id": 2250, "diva": 3019},
    {"code": "LOCH", "name": "Zürich, Lochergut",               "halt_id": 2248, "diva": 1579},
    {"code": "KALK", "name": "Zürich, Kalkbreite/Bhf.Wiedikon", "halt_id": 1906, "diva": 1357},
    {"code": "BEZI", "name": "Zürich, Bezirksgebäude",           "halt_id": 1306, "diva": 478},
    {"code": "STAU", "name": "Zürich, Stauffacher",             "halt_id": 1502, "diva": 2556},
    {"code": "SIHS", "name": "Zürich, Sihlstrasse",              "halt_id": 2657, "diva": 2396},
    {"code": "PARA", "name": "Zürich, Paradeplatz",            "halt_id": 1528, "diva": 1861},
]


def get_corridor_subset(num_stops: int = 8, segment: str = "freihof") -> list[dict]:
    """
    Select 6, 7, or 8 connected stops along the high-density corridor.

    Segments:
      - 'freihof' (default): Starts at Freihofstrasse and extends eastward along Badenerstrasse
        (e.g., 8 stops: FREI -> LETG -> ALBP -> ZYPR -> LOCH -> KALK -> BEZI -> STAU)
      - 'paradeplatz': Extends into the city center at Paradeplatz
        (e.g., 8 stops: ALBP -> ZYPR -> LOCH -> KALK -> BEZI -> STAU -> SIHS -> PARA)
    """
    if num_stops not in (6, 7, 8):
        raise ValueError("num_stops must be 6, 7, or 8 for quantum solver prototype sizing.")

    if segment == "freihof":
        # Window starting at Freihofstrasse
        return CORRIDOR_STOPS_FULL[0:num_stops]
    elif segment == "paradeplatz":
        # Window ending at Paradeplatz
        start_idx = len(CORRIDOR_STOPS_FULL) - num_stops
        return CORRIDOR_STOPS_FULL[start_idx:]
    else:
        raise ValueError(f"Unknown segment: {segment}. Choose 'freihof' or 'paradeplatz'.")


def load_stop_coordinates(data_dir: Path, stop_ids: list[int]) -> dict[int, tuple[float, float]]:
    """Load GPS Latitude and Longitude from haltepunkt.csv."""
    pts_file = data_dir / "Traveltimes" / "haltepunkt.csv"
    if not pts_file.exists():
        return {}

    df_pts = pd.read_csv(pts_file, encoding="utf-8-sig")
    df_pts_sub = df_pts[df_pts["halt_id"].isin(stop_ids)]
    coords = (
        df_pts_sub.groupby("halt_id")[["GPS_Latitude", "GPS_Longitude"]]
        .mean()
        .to_dict(orient="index")
    )
    return {hid: (val["GPS_Latitude"], val["GPS_Longitude"]) for hid, val in coords.items()}


def extract_corridor_edges(data_dir: Path, stop_codes: list[str]) -> pd.DataFrame:
    """
    Extract planned travel times, actual times, and operating lines
    between all adjacent corridor stops from fahrzeiten_soll_ist_*.csv.
    """
    travel_dir = data_dir / "Traveltimes"
    fz_files = list(travel_dir.glob("fahrzeiten_soll_ist_*.csv"))
    if not fz_files:
        raise FileNotFoundError(f"No fahrzeiten CSV found in {travel_dir}")

    cols = [
        "linie",
        "halt_kurz_von1",
        "halt_kurz_nach1",
        "soll_ab_von",
        "soll_an_nach",
        "ist_ab_von",
        "ist_an_nach1",
    ]

    chunks = []
    # Process in chunks for fast memory-efficient loading (~1s total)
    for chunk in pd.read_csv(
        fz_files[0], sep=",", encoding="utf-8-sig", usecols=cols, chunksize=250000
    ):
        match = chunk[
            chunk["halt_kurz_von1"].isin(stop_codes) & chunk["halt_kurz_nach1"].isin(stop_codes)
        ]
        if not match.empty:
            chunks.append(match)

    if not chunks:
        return pd.DataFrame()

    df_corridor = pd.concat(chunks, ignore_index=True)

    # Calculate planned travel time (with midnight rollover correction)
    tt_plan = df_corridor["soll_an_nach"] - df_corridor["soll_ab_von"]
    tt_plan = tt_plan.apply(lambda x: x + 86400 if x < 0 else x)
    df_corridor["plan_sec"] = tt_plan

    # Calculate actual travel time
    tt_act = df_corridor["ist_an_nach1"] - df_corridor["ist_ab_von"]
    tt_act = tt_act.apply(lambda x: x + 86400 if x < 0 else x)
    df_corridor["act_sec"] = tt_act

    # Calculate departure delay
    dep_delay = df_corridor["ist_ab_von"] - df_corridor["soll_ab_von"]
    dep_delay = dep_delay.apply(
        lambda x: x + 86400 if x < -43200 else (x - 86400 if x > 43200 else x)
    )
    df_corridor["dep_delay_sec"] = dep_delay

    # Filter out loops (same stop) and aggregate by edge
    edge_df = (
        df_corridor[df_corridor["halt_kurz_von1"] != df_corridor["halt_kurz_nach1"]]
        .groupby(["halt_kurz_von1", "halt_kurz_nach1"])
        .agg(
            lines=("linie", lambda s: sorted(list(set(s)))),
            planned_sec=("plan_sec", "median"),
            actual_sec=("act_sec", "median"),
            avg_delay_sec=("dep_delay_sec", "mean"),
            trip_count=("linie", "count"),
        )
        .reset_index()
    )

    return edge_df


def build_corridor_graph(
    num_stops: int = 8, segment: str = "freihof", data_dir: Path | None = None
) -> nx.DiGraph:
    """
    Builds and returns the NetworkX directed graph (DiGraph) for the Zurich corridor.

    Parameters:
        num_stops: Number of stops in the sub-network (6, 7, or 8). Default 8.
        segment: 'freihof' (Freihofstrasse -> Stauffacher) or 'paradeplatz' (Albisriederplatz -> Paradeplatz).
        data_dir: Path to the Data/ directory. Default: ./Data relative to script.

    Returns:
        nx.DiGraph: Directed graph with nodes (stops) and weighted edges (planned seconds).
    """
    if data_dir is None:
        data_dir = Path(__file__).resolve().parent / "Data"

    stops_meta = get_corridor_subset(num_stops, segment=segment)
    stop_codes = [s["code"] for s in stops_meta]
    stop_ids = [s["halt_id"] for s in stops_meta]

    # Load coordinates
    coords = load_stop_coordinates(data_dir, stop_ids)

    segment_desc = (
        "Freihofstrasse - Albisriederplatz - Stauffacher"
        if segment == "freihof"
        else "Albisriederplatz - Stauffacher - Paradeplatz"
    )

    # Initialize DiGraph
    G = nx.DiGraph(
        name=f"Zurich Congested Badenerstrasse Corridor ({num_stops} stops)",
        corridor=segment_desc,
        segment=segment,
        num_stops=num_stops,
    )

    # Add Nodes
    for s in stops_meta:
        code = s["code"]
        hid = s["halt_id"]
        lat, lon = coords.get(hid, (0.0, 0.0))
        G.add_node(
            code,
            name=s["name"],
            short_code=code,
            halt_id=hid,
            halt_diva=s["diva"],
            latitude=lat,
            longitude=lon,
            pos=(lon, lat),  # (x, y) for spatial plotting
        )

    # Extract & Add Edges
    edge_df = extract_corridor_edges(data_dir, stop_codes)
    for _, r in edge_df.iterrows():
        u = r["halt_kurz_von1"]
        v = r["halt_kurz_nach1"]
        planned_sec = float(r["planned_sec"])
        actual_sec = float(r["actual_sec"])
        delay_sec = float(r["avg_delay_sec"])
        lines = r["lines"]
        trip_count = int(r["trip_count"])

        # weight is the primary metric for shortest path / TSP / Pathfinder
        G.add_edge(
            u,
            v,
            weight=planned_sec,
            weight_min=round(planned_sec / 60.0, 2),
            planned_sec=planned_sec,
            actual_sec=actual_sec,
            delay_sec=round(delay_sec, 2),
            lines=lines,
            lines_str=", ".join(map(str, lines)),
            trip_count=trip_count,
        )

    return G


def get_travel_time_matrix(G: nx.DiGraph) -> pd.DataFrame:
    """
    Computes the all-pairs planned travel time matrix (in seconds) using
    Dijkstra's algorithm on the directed graph G.
    Direct edges use the planned fahrzeit; multi-hop paths use the shortest path.
    Returns a symmetric/asymmetric Pandas DataFrame (stops x stops).
    """
    nodes = list(G.nodes)
    lengths = dict(nx.all_pairs_dijkstra_path_length(G, weight="weight"))
    matrix = np.zeros((len(nodes), len(nodes)))

    for i, u in enumerate(nodes):
        for j, v in enumerate(nodes):
            if u == v:
                matrix[i, j] = 0.0
            else:
                matrix[i, j] = lengths.get(u, {}).get(v, np.nan)

    return pd.DataFrame(matrix, index=nodes, columns=nodes)


def plot_corridor_graph(G: nx.DiGraph, output_file: Path | str = "corridor_graph.png"):
    """Visualizes the corridor network using matplotlib and saves to file."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12, 8), dpi=180)
    pos = {node: data["pos"] for node, data in G.nodes(data=True)}

    # Fallback to spring layout if coordinates missing
    if any(p == (0.0, 0.0) for p in pos.values()):
        pos = nx.spring_layout(G, seed=42)

    # Draw Nodes
    nx.draw_networkx_nodes(
        G, pos, node_size=1700, node_color="#0D47A1", alpha=0.95, edgecolors="#E3F2FD", linewidths=2.5, ax=ax
    )
    # Node Code (bold text inside node circle)
    node_codes = {n: n for n in G.nodes}
    nx.draw_networkx_labels(G, pos, labels=node_codes, font_size=10, font_color="white", font_weight="bold", ax=ax)

    # Stop names as offset annotations (alternating above/below to prevent overlap)
    for idx, (node, (x, y)) in enumerate(pos.items()):
        name = G.nodes[node]["name"].split(", ")[-1]
        y_offset = 22 if idx % 2 == 0 else -28
        ax.annotate(
            name,
            (x, y),
            textcoords="offset points",
            xytext=(0, y_offset),
            ha="center",
            fontsize=8.5,
            fontweight="bold",
            color="#263238",
            bbox=dict(boxstyle="round,pad=0.28", fc="#ECEFF1", ec="#90A4AE", alpha=0.9),
        )

    # Draw Edges with curved arrows for bidirectional readability
    nx.draw_networkx_edges(
        G,
        pos,
        arrowstyle="-|>",
        arrowsize=18,
        edge_color="#37474F",
        width=2.2,
        connectionstyle="arc3,rad=0.15",
        ax=ax,
    )

    # Edge labels (planned seconds)
    edge_labels = {(u, v): f"{int(d['weight'])}s" for u, v, d in G.edges(data=True)}
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=7.5, label_pos=0.6, ax=ax)

    ax.set_title(
        f"{G.graph.get('name', 'Zurich Congested Corridor')} - Planned Travel Times (seconds)",
        fontsize=13,
        fontweight="bold",
        pad=28,
    )
    ax.set_xlabel("Longitude (°E)", fontsize=11, labelpad=8)
    ax.set_ylabel("Latitude (°N)", fontsize=11, labelpad=8)
    ax.grid(True, linestyle="--", alpha=0.35)
    plt.tight_layout()

    plt.savefig(output_file)
    plt.close()
    print(f"Graph plot saved to: {output_file}")


def export_graph_json(G: nx.DiGraph, output_file: Path | str = "corridor_graph.json"):
    """Export graph structure and travel time matrix to JSON for solvers."""
    data = {
        "metadata": G.graph,
        "nodes": [
            {
                "id": n,
                "name": d["name"],
                "lat": d["latitude"],
                "lon": d["longitude"],
                "halt_id": d["halt_id"],
            }
            for n, d in G.nodes(data=True)
        ],
        "edges": [
            {
                "from": u,
                "to": v,
                "planned_sec": d["planned_sec"],
                "actual_sec": d["actual_sec"],
                "delay_sec": d["delay_sec"],
                "lines": d["lines"],
                "trip_count": d["trip_count"],
            }
            for u, v, d in G.edges(data=True)
        ],
        "travel_time_matrix_sec": get_travel_time_matrix(G).to_dict(),
    }
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Graph JSON exported to: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Build NetworkX directed graph for high-density Zurich transit corridor."
    )
    parser.add_argument(
        "--num-stops",
        type=int,
        choices=[6, 7, 8],
        default=8,
        help="Number of stops in the sub-network (6-8, default: 8)",
    )
    parser.add_argument(
        "--segment",
        type=str,
        choices=["freihof", "paradeplatz"],
        default="freihof",
        help="Segment along Badenerstrasse: 'freihof' (Freihofstrasse -> Stauffacher) or 'paradeplatz' (Albisriederplatz -> Paradeplatz)",
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        default=True,
        help="Generate and save matplotlib diagram of corridor network",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        default=True,
        help="Export graph JSON and travel time matrix",
    )
    args = parser.parse_args()

    print("=" * 80)
    print(f"BUILDING ZURICH CONGESTED CORRIDOR GRAPH ({args.num_stops} STOPS, SEGMENT: {args.segment.upper()})")
    print("=" * 80)

    # 1. Build NetworkX DiGraph
    G = build_corridor_graph(num_stops=args.num_stops, segment=args.segment)

    # 2. Display Nodes
    print(f"\n[1] Nodes ({G.number_of_nodes()} stops):")
    for n, d in G.nodes(data=True):
        print(f"  - {n:4s} | ID: {d['halt_id']:4d} | {d['name']:30s} | GPS: ({d['latitude']:.5f}, {d['longitude']:.5f})")

    # 3. Display Edges
    print(f"\n[2] Directed Edges ({G.number_of_edges()} corridor connections):")
    for u, v, d in sorted(G.edges(data=True)):
        print(
            f"  {u:4s} -> {v:4s} | Planned: {d['planned_sec']:5.1f}s ({d['weight_min']:.1f} min) | "
            f"Actual: {d['actual_sec']:5.1f}s | Delay: {d['delay_sec']:+5.1f}s | "
            f"Lines: [{d['lines_str']}] | Trips: {d['trip_count']:,}"
        )

    # 4. Display Travel Time Matrix
    tt_matrix = get_travel_time_matrix(G)
    print("\n[3] Planned Travel Time Matrix (all-pairs shortest paths in seconds):")
    print(tt_matrix.round(1).to_string())

    # 5. Quantum Resource Estimation
    n = G.number_of_nodes()
    qubo_qubits = n * n
    print("\n[4] Quantum Solver Prototype Resource Estimate:")
    print(f"  - Graph Order (N): {n} vertices")
    print(f"  - Standard TSP QUBO requirement (N²): {qubo_qubits} qubits")
    print(f"  - Pathfinder (2-path vertex-disjoint): ~{n * 4} to ~{n * 6} qubits")
    print("  -> Perfectly fits within local statevector simulators (e.g. Qiskit Aer / StatevectorSampler <= 64 qubits)")

    # 6. Save Plot and JSON
    if args.plot:
        plot_corridor_graph(G, "corridor_graph.png")
    if args.export:
        export_graph_json(G, "corridor_graph.json")


if __name__ == "__main__":
    main()
