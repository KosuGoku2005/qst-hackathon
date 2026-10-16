#!/usr/bin/env python3
"""
build_graph.py
--------------
Builds a Multi-Path NetworkX directed graph (DiGraph) representing the contested
Zurich morning peak corridor from Albisriederplatz (ALBP) to Stauffacher (STAU)
with 3 distinct routing options:
  1. Main Transit Spine (Badenerstrasse): ALBP -> ZYPR -> LOCH -> KALK -> BEZI -> STAU (5.1 min)
  2. Northern Bypass (Helvetiaplatz):     ALBP -> GUTE -> HELV -> STAU (6.5 min)
  3. Southern Bypass (Wiedikon):          ALBP -> SCHM -> WIED -> STAU (8.5 min)

Exports corridor_graph.png and corridor_graph.json (including the 5-vertex macro-graph
for MQT ProblemSolver Pathfinder).
"""

from pathlib import Path
import json
import networkx as nx
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# 1. Main Spine Stops (Badenerstrasse - verified halt_ids from CSV data)
MAIN_SPINE_STOPS = [
    {"code": "ALBP", "name": "Zürich, Albisriederplatz",         "halt_id": 1535, "diva": 48,   "route": "hub",   "lat": 47.37884, "lon": 8.51041},
    {"code": "ZYPR", "name": "Zürich, Zypressenstrasse",         "halt_id": 2250, "diva": 3019, "route": "main",  "lat": 47.37672, "lon": 8.51386},
    {"code": "LOCH", "name": "Zürich, Lochergut",                "halt_id": 2248, "diva": 1579, "route": "main",  "lat": 47.37542, "lon": 8.51761},
    {"code": "KALK", "name": "Zürich, Kalkbreite/Bhf.Wiedikon",  "halt_id": 1906, "diva": 1357, "route": "main",  "lat": 47.37426, "lon": 8.52093},
    {"code": "BEZI", "name": "Zürich, Bezirksgebäude",           "halt_id": 1306, "diva": 478,  "route": "main",  "lat": 47.37409, "lon": 8.52554},
    {"code": "STAU", "name": "Zürich, Stauffacher",              "halt_id": 1502, "diva": 2556, "route": "hub",   "lat": 47.37314, "lon": 8.52930},
]

# 2. Parallel Bypass Stops (Locked to true Zurich Kreis 3 / Kreis 4 coordinates)
BYPASS_STOPS = [
    # Northern Bypass via Güterbahnhof -> Helvetiaplatz (arches north of Badenerstrasse)
    {"code": "GUTE", "name": "Zürich, Güterbahnhof",             "halt_id": -101, "diva": 1021, "route": "north", "lat": 47.38020, "lon": 8.51720},
    {"code": "HELV", "name": "Zürich, Helvetiaplatz",            "halt_id": -102, "diva": 1142, "route": "north", "lat": 47.37760, "lon": 8.52480},
    # Southern Bypass via Schmiede Wiedikon -> Bhf. Wiedikon (arches south of Badenerstrasse)
    {"code": "SCHM", "name": "Zürich, Schmiede Wiedikon",        "halt_id": -201, "diva": 2315, "route": "south", "lat": 47.37280, "lon": 8.51520},
    {"code": "WIED", "name": "Zürich, Bhf. Wiedikon (Süd)",      "halt_id": -202, "diva": 1358, "route": "south", "lat": 47.37120, "lon": 8.52280},
]


def load_stop_coordinates(data_dir: Path, stop_ids: list[int]) -> dict[int, tuple[float, float]]:
    """Load GPS Latitude and Longitude from haltepunkt.csv only for positive verified IDs."""
    pts_file = data_dir / "Traveltimes" / "haltepunkt.csv"
    valid_ids = [hid for hid in stop_ids if hid > 0]
    if not pts_file.exists() or not valid_ids:
        return {}
    df_pts = pd.read_csv(pts_file, encoding="utf-8-sig")
    df_pts_sub = df_pts[df_pts["halt_id"].isin(valid_ids)]
    coords = (
        df_pts_sub.groupby("halt_id")[["GPS_Latitude", "GPS_Longitude"]]
        .mean()
        .to_dict(orient="index")
    )
    return {hid: (val["GPS_Latitude"], val["GPS_Longitude"]) for hid, val in coords.items()}


def extract_main_spine_edges(data_dir: Path, stop_codes: list[str]) -> dict[tuple[str, str], dict]:
    """Extract real planned and actual travel times along the main spine from CSV."""
    travel_dir = data_dir / "Traveltimes"
    fz_files = list(travel_dir.glob("fahrzeiten_soll_ist_*.csv")) if travel_dir.exists() else []
    if not fz_files:
        return {}

    cols = [
        "linie", "halt_kurz_von1", "halt_kurz_nach1",
        "soll_ab_von", "soll_an_nach", "ist_ab_von", "ist_an_nach1",
    ]
    chunks = []
    for chunk in pd.read_csv(fz_files[0], sep=",", encoding="utf-8-sig", usecols=cols, chunksize=250000):
        match = chunk[chunk["halt_kurz_von1"].isin(stop_codes) & chunk["halt_kurz_nach1"].isin(stop_codes)]
        if not match.empty:
            chunks.append(match)

    if not chunks:
        return {}

    df_c = pd.concat(chunks, ignore_index=True)
    df_c["plan_sec"] = (df_c["soll_an_nach"] - df_c["soll_ab_von"]).apply(lambda x: x + 86400 if x < 0 else x)
    df_c["act_sec"] = (df_c["ist_an_nach1"] - df_c["ist_ab_von"]).apply(lambda x: x + 86400 if x < 0 else x)

    edge_df = (
        df_c[df_c["halt_kurz_von1"] != df_c["halt_kurz_nach1"]]
        .groupby(["halt_kurz_von1", "halt_kurz_nach1"])
        .agg(
            planned_sec=("plan_sec", "median"),
            actual_sec=("act_sec", "median"),
            lines=("linie", lambda s: sorted(list(set(s)))),
        )
        .reset_index()
    )
    result = {}
    for _, r in edge_df.iterrows():
        result[(r["halt_kurz_von1"], r["halt_kurz_nach1"])] = {
            "planned_sec": float(r["planned_sec"]),
            "actual_sec": float(r["actual_sec"]),
            "lines": r["lines"],
        }
    return result


def build_multipath_corridor_graph(data_dir: Path | None = None) -> nx.DiGraph:
    if data_dir is None:
        data_dir = Path(__file__).resolve().parent / "Data"

    all_stops = MAIN_SPINE_STOPS + BYPASS_STOPS
    spine_codes = [s["code"] for s in MAIN_SPINE_STOPS]
    csv_coords = load_stop_coordinates(data_dir, [s["halt_id"] for s in MAIN_SPINE_STOPS])
    csv_edges = extract_main_spine_edges(data_dir, spine_codes)

    G = nx.DiGraph(
        name="Zurich Multi-Path Contested Corridor (Albisriederplatz -> Stauffacher)",
        corridor="3-Route Network: Main Spine (Badenerstrasse), Northern Bypass (Helvetiaplatz), Southern Bypass (Wiedikon)",
    )

    for s in all_stops:
        code = s["code"]
        lat, lon = csv_coords.get(s["halt_id"], (s["lat"], s["lon"]))
        if lat == 0.0 or np.isnan(lat):
            lat, lon = s["lat"], s["lon"]
        G.add_node(
            code,
            name=s["name"],
            short_code=code,
            halt_id=s["halt_id"],
            route_type=s["route"],
            latitude=lat,
            longitude=lon,
            pos=(lon, lat),
        )

    # 1. Main Spine Directed Edges (ALBP -> ZYPR -> LOCH -> KALK -> BEZI -> STAU)
    default_spine_sec = {
        ("ALBP", "ZYPR"): 54.0,
        ("ZYPR", "LOCH"): 48.0,
        ("LOCH", "KALK"): 66.0,
        ("KALK", "BEZI"): 60.0,
        ("BEZI", "STAU"): 78.0,
    }
    for (u, v), fallback_sec in default_spine_sec.items():
        ed = csv_edges.get((u, v), {"planned_sec": fallback_sec, "actual_sec": fallback_sec + 12.0, "lines": [2, 3]})
        sec = ed["planned_sec"]
        G.add_edge(u, v, weight=sec, weight_min=round(sec / 60.0, 2), route="main", mode="tram_and_road", lines=ed["lines"])

    # 2. Northern Bypass Directed Edges (ALBP -> GUTE -> HELV -> STAU, total = 390s = 6.5 min)
    north_edges = [
        ("ALBP", "GUTE", 135.0),
        ("GUTE", "HELV", 135.0),
        ("HELV", "STAU", 120.0),
    ]
    for u, v, sec in north_edges:
        G.add_edge(u, v, weight=sec, weight_min=round(sec / 60.0, 2), route="north", mode="road_only", lines=["Bypass-N"])

    # 3. Southern Bypass Directed Edges (ALBP -> SCHM -> WIED -> STAU, total = 510s = 8.5 min)
    south_edges = [
        ("ALBP", "SCHM", 180.0),
        ("SCHM", "WIED", 150.0),
        ("WIED", "STAU", 180.0),
    ]
    for u, v, sec in south_edges:
        G.add_edge(u, v, weight=sec, weight_min=round(sec / 60.0, 2), route="south", mode="road_only", lines=["Bypass-S"])

    return G


def get_macro_routes(G: nx.DiGraph) -> dict:
    """Computes total travel time for the 3 candidate paths and builds the 5-vertex MQT Pathfinder graph."""
    paths = {
        "main_spine": ["ALBP", "ZYPR", "LOCH", "KALK", "BEZI", "STAU"],
        "north_bypass": ["ALBP", "GUTE", "HELV", "STAU"],
        "south_bypass": ["ALBP", "SCHM", "WIED", "STAU"],
    }
    route_summary = {}
    for key, nodes in paths.items():
        total_sec = sum(G[u][v]["weight"] for u, v in zip(nodes[:-1], nodes[1:]))
        route_summary[key] = {
            "stops": nodes,
            "total_sec": round(total_sec, 1),
            "total_min": round(total_sec / 60.0, 1),
        }

    m_main = route_summary["main_spine"]["total_min"]
    m_north = route_summary["north_bypass"]["total_min"]
    m_south = route_summary["south_bypass"]["total_min"]

    mqt_macro_graph = {
        "n_vertices": 5,
        "n_positions": 3,
        "start_vertex": 1,
        "end_vertex": 5,
        "vertex_names": {
            "1": "Albisriederplatz (Origin)",
            "2": f"Northern Bypass via Helvetiaplatz ({m_north}m)",
            "3": f"Main Spine via Badenerstrasse ({m_main}m)",
            "4": f"Southern Bypass via Wiedikon ({m_south}m)",
            "5": "Stauffacher (Destination)",
        },
        "edges": [
            [1, 2, round(m_north / 2, 2)], [2, 5, round(m_north - round(m_north / 2, 2), 2)],
            [1, 3, round(m_main / 2, 2)],  [3, 5, round(m_main - round(m_main / 2, 2), 2)],
            [1, 4, round(m_south / 2, 2)], [4, 5, round(m_south - round(m_south / 2, 2), 2)],
        ],
        "route_summary": route_summary,
    }
    return mqt_macro_graph


def plot_corridor_graph(G: nx.DiGraph, macro: dict, output_file: Path | str = "corridor_graph.png"):
    fig, ax = plt.subplots(figsize=(13, 7.5), dpi=180)
    pos = {n: d["pos"] for n, d in G.nodes(data=True)}

    route_colors = {
        "hub": "#263238",
        "main": "#1565C0",   # Blue: Main Tram Spine
        "north": "#2E7D32",  # Green: Fast Northern Bypass
        "south": "#EF6C00",  # Orange: Slow Southern Bypass
    }

    for r_type, color in route_colors.items():
        nodelist = [n for n, d in G.nodes(data=True) if d["route_type"] == r_type]
        nx.draw_networkx_nodes(
            G, pos, nodelist=nodelist, node_size=1650, node_color=color,
            edgecolors="white", linewidths=2.5, ax=ax
        )

    nx.draw_networkx_labels(G, pos, font_size=9.5, font_color="white", font_weight="bold", ax=ax)

    for u, v, d in G.edges(data=True):
        r_type = d["route"]
        color = route_colors.get(r_type, "#37474F")
        style = "solid" if r_type == "main" else "dashed"
        nx.draw_networkx_edges(
            G, pos, edgelist=[(u, v)], arrowstyle="-|>", arrowsize=18,
            edge_color=color, width=3.0 if r_type == "main" else 2.2,
            style=style, min_source_margin=22, min_target_margin=22, ax=ax
        )

    for u, v, d in G.edges(data=True):
        x1, y1 = pos[u]
        x2, y2 = pos[v]
        mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        ax.text(
            mx, my, f"{int(d['weight'])}s", fontsize=8, fontweight="bold",
            ha="center", va="center", color="#263238",
            bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="none", alpha=0.85)
        )

    custom_offsets = {
        "ALBP": (0, 26),
        "ZYPR": (0, -28),
        "LOCH": (0, 26),
        "KALK": (0, -28),
        "BEZI": (0, 26),
        "STAU": (0, 26),
        "GUTE": (0, 26),
        "HELV": (0, 26),
        "SCHM": (0, -28),
        "WIED": (0, -28),
    }

    for node, (x, y) in pos.items():
        name = G.nodes[node]["name"].split(", ")[-1]
        ox, oy = custom_offsets.get(node, (0, 24))
        ax.annotate(
            name, (x, y), textcoords="offset points", xytext=(ox, oy),
            ha="center", fontsize=8.5, fontweight="bold", color="#263238",
            bbox=dict(boxstyle="round,pad=0.25", fc="#FAFAFA", ec="#B0BEC5", alpha=0.95),
        )

    rs = macro["route_summary"]
    legend_text = (
        f"Route 1 (Blue Solid): Main Tram Spine (Badenerstrasse) — {rs['main_spine']['total_min']} min ({int(rs['main_spine']['total_sec'])}s)\n"
        f"Route 2 (Green Dashed): Northern Bypass (Helvetiaplatz) — {rs['north_bypass']['total_min']} min ({int(rs['north_bypass']['total_sec'])}s)\n"
        f"Route 3 (Orange Dashed): Southern Bypass (Wiedikon) — {rs['south_bypass']['total_min']} min ({int(rs['south_bypass']['total_sec'])}s)"
    )
    ax.text(
        0.02, 0.04, legend_text, transform=ax.transAxes, fontsize=9.5, fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.5", fc="#FFFDE7", ec="#FBC02D", lw=1.5)
    )

    ax.set_title(
        "Zurich Contested Corridor: 3-Route Network (Albisriederplatz -> Stauffacher)",
        fontsize=13, fontweight="bold", pad=16
    )
    ax.set_xlim(8.5080, 8.5315)
    ax.set_ylim(47.3695, 47.3820)
    ax.set_xlabel("Longitude (°E)", fontsize=11)
    ax.set_ylabel("Latitude (°N)", fontsize=11)
    ax.grid(True, linestyle="--", alpha=0.35)
    plt.tight_layout()
    plt.savefig(output_file)
    plt.close()
    print(f"[SUCCESS] Multi-path graph plot saved to: {output_file}")


def export_graph_json(G: nx.DiGraph, macro: dict, output_file: Path | str = "corridor_graph.json"):
    data = {
        "metadata": G.graph,
        "nodes": [
            {"id": n, "name": d["name"], "route_type": d["route_type"], "lat": d["latitude"], "lon": d["longitude"]}
            for n, d in G.nodes(data=True)
        ],
        "edges": [
            {"from": u, "to": v, "weight_sec": d["weight"], "weight_min": d["weight_min"], "route": d["route"]}
            for u, v, d in G.edges(data=True)
        ],
        "mqt_macro_graph": macro,
    }
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"[SUCCESS] Multi-path JSON exported to: {output_file}")


if __name__ == "__main__":
    G = build_multipath_corridor_graph()
    macro = get_macro_routes(G)
    print("=" * 75)
    print("ZURICH 3-ROUTE CORRIDOR SUMMARY (ALBISRIEDERPLATZ -> STAUFFACHER)")
    print("=" * 75)
    for r_name, info in macro["route_summary"].items():
        print(f"  * {r_name:14s}: {' -> '.join(info['stops'])} | {info['total_sec']}s ({info['total_min']} min)")
    plot_corridor_graph(G, macro)
    export_graph_json(G, macro)