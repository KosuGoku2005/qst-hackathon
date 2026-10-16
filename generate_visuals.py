#!/usr/bin/env python3
"""
generate_visuals.py
-------------------
Produces publication-grade visual artifacts for the municipal Head of Planning
(Hackathon Format A - "Make the Case"):

1. Space-Time Diagram (Marey Chart): Side-by-side visualization of the 4 competing
   vehicles along the Zurich corridor for Plan 1 (Utilitarian Buy-Off Trap) vs.
   Plan 2 (Recommended Transit & Medical Equity), highlighting the 6.5 min dialysis deadline.
2. Winners & Losers Scorecard: Multi-panel dashboard contrasting vehicle travel times,
   cumulative citizen passenger-minutes of delay, and the policy decision matrix.

Saves figures to:
  - space_time_comparison.png
  - winners_losers_scorecard.png
"""

from pathlib import Path
import json
import matplotlib.pyplot as plt
import numpy as np

# Set matplotlib parameters for clean, publication-ready typography
plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Helvetica", "Arial"]
plt.rcParams["axes.edgecolor"] = "#37474F"
plt.rcParams["axes.linewidth"] = 1.2


def load_portfolio(base_dir: Path) -> dict:
    json_path = base_dir / "decision_portfolio.json"
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def plot_space_time_diagrams(portfolio: dict, output_path: Path):
    """
    Plots side-by-side Space-Time (Marey) charts comparing:
      - Plan 1: Utilitarian Speed (Inviolable Dialysis Deadline Traded Away)
      - Plan 2: Inviolable Equity (Recommended: Dialysis Arrives on Time)
    """
    fig, axes = plt.subplots(1, 2, figsize=(16, 8.5), dpi=200, sharey=True)

    # Waypoints with approximate cumulative distance from ALBP (km)
    # Origin: ALBP (0.0 km), Destination: STAU (2.2 km)
    route_checkpoints = {
        "Main": [
            ("ALBP", 0.0, 0.0),
            ("ZYPR", 0.35, 0.9),
            ("LOCH", 0.70, 1.7),
            ("KALK", 1.15, 2.8),
            ("BEZI", 1.65, 3.8),
            ("STAU", 2.15, 5.1),
        ],
        "North": [
            ("ALBP", 0.0, 0.0),
            ("GUTE", 0.90, 2.25),
            ("HELV", 1.65, 4.50),
            ("STAU", 2.20, 6.50),
        ],
        "South": [
            ("ALBP", 0.0, 0.0),
            ("SCHM", 1.00, 3.00),
            ("WIED", 1.85, 5.50),
            ("STAU", 2.25, 8.50),
        ],
    }

    # Visual styling for each vehicle claim
    styles = {
        "Ambulance": {
            "label": "Ambulance (Life-Safety, Priority 30)",
            "color": "#D32F2F",
            "ls": "-",
            "lw": 3.4,
            "marker": "o",
            "ms": 7,
            "zorder": 5,
        },
        "Tram": {
            "label": "VBZ Tram (185 Commuters, Rail-Bound)",
            "color": "#1565C0",
            "ls": "-",
            "lw": 3.2,
            "marker": "s",
            "ms": 7,
            "zorder": 4,
        },
        "Dialysis": {
            "label": "Dialysis Paratransit (Medical Deadline 6.5m)",
            "color": "#7B1FA2",
            "ls": "--",
            "lw": 3.0,
            "marker": "^",
            "ms": 8,
            "zorder": 6,
        },
        "Van": {
            "label": "Commercial Delivery Van (Logistics)",
            "color": "#E65100",
            "ls": ":",
            "lw": 2.4,
            "marker": "D",
            "ms": 6,
            "zorder": 3,
        },
    }

    plans_to_plot = [
        ("plan_1_utilitarian", axes[0], "PLAN 1: Utilitarian Speed (Buy-Off Trap)\n[VIOLATION] Inviolable Dialysis Traded for Van Commercial Speed"),
        ("plan_2_recommended", axes[1], "PLAN 2: Medical & Transit Equity (Recommended)\n[PROTECTED] Dialysis Protected on North Bypass — Van Takes Detour"),
    ]

    for plan_key, ax, title in plans_to_plot:
        plan_data = portfolio["plans"][plan_key]
        vehicles_sched = plan_data["vehicles"]

        # 1. Shaded regions: Deadline breached zone (t > 6.5 min)
        ax.axvspan(6.5, 10.0, color="#FFEBEE" if plan_key == "plan_1_utilitarian" else "#F1F8E9", alpha=0.55, zorder=0)

        # 2. Inviolable Medical Deadline marker (vertical dashed line at t = 6.5 min)
        ax.axvline(6.5, color="#C2185B", linestyle="--", linewidth=2.0, alpha=0.9, zorder=2)
        ax.text(
            6.55,
            0.15,
            "Inviolable Medical\nDeadline (6.5 min)",
            color="#AD1457",
            fontsize=9.5,
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.25", fc="#FFF0F5", ec="#C2185B", alpha=0.95),
            zorder=7,
        )

        # 3. Horizontal corridor reference guidelines (Origin and Destination)
        ax.axhline(0.0, color="#78909C", linestyle="-", linewidth=1.0, alpha=0.4)
        ax.axhline(2.2, color="#78909C", linestyle="-", linewidth=1.0, alpha=0.4)

        # 4. Plot each vehicle trajectory
        for v_name, style in styles.items():
            if v_name not in vehicles_sched:
                continue
            v_info = vehicles_sched[v_name]
            r_key = v_info["route_key"]
            checkpoints = route_checkpoints[r_key]

            times = [cp[2] for cp in checkpoints]
            dists = [cp[1] for cp in checkpoints]

            # Label customization for Dialysis
            if v_name == "Dialysis":
                if plan_key == "plan_1_utilitarian":
                    line_color = "#D50000"
                    lbl = f"{style['label']} [LATE: 8.5m > 6.5m]"
                else:
                    line_color = "#2E7D32"
                    lbl = f"{style['label']} [ON TIME: 6.5m]"
            elif v_name == "Van":
                lbl = f"{style['label']} ({v_info['travel_min']}m via {r_key})"
            else:
                lbl = f"{style['label']} ({v_info['travel_min']}m via {r_key})"

            ax.plot(
                times,
                dists,
                label=lbl,
                color=line_color if v_name == "Dialysis" else style["color"],
                linestyle=style["ls"],
                linewidth=style["lw"],
                marker=style["marker"],
                markersize=style["ms"],
                zorder=style["zorder"],
            )

        # Annotations for key outcomes
        if plan_key == "plan_1_utilitarian":
            ax.annotate(
                "CRITICAL VIOLATION:\nDialysis arrives +2.0m LATE\n(Bypassed for Van speed)",
                xy=(8.5, 2.2),
                xytext=(6.9, 1.45),
                arrowprops=dict(facecolor="#D50000", edgecolor="#B71C1C", width=2, headwidth=8),
                fontsize=9.5,
                fontweight="bold",
                color="#B71C1C",
                bbox=dict(boxstyle="round,pad=0.4", fc="#FFCDD2", ec="#D32F2F", lw=1.5),
                zorder=10,
            )
            ax.annotate(
                "Van gets fast North Bypass\n(6.5m vs 8.5m)",
                xy=(6.5, 2.2),
                xytext=(4.3, 1.7),
                arrowprops=dict(facecolor="#E65100", edgecolor="#BF360C", width=1.5, headwidth=6),
                fontsize=8.5,
                fontweight="bold",
                color="#E65100",
                bbox=dict(boxstyle="round,pad=0.3", fc="#FFE0B2", ec="#FB8C00", lw=1),
                zorder=10,
            )
        else:
            ax.annotate(
                "EQUITY PRESERVED:\nDialysis arrives ON TIME\n(6.5m deadline satisfied)",
                xy=(6.5, 2.2),
                xytext=(4.2, 1.55),
                arrowprops=dict(facecolor="#2E7D32", edgecolor="#1B5E20", width=2, headwidth=8),
                fontsize=9.5,
                fontweight="bold",
                color="#1B5E20",
                bbox=dict(boxstyle="round,pad=0.4", fc="#C8E6C9", ec="#388E3C", lw=1.5),
                zorder=10,
            )
            ax.annotate(
                "Van absorbs 8.5m South Detour\n(+2.0m parcel delay, no human harm)",
                xy=(8.5, 2.2),
                xytext=(6.8, 1.0),
                arrowprops=dict(facecolor="#E65100", edgecolor="#BF360C", width=1.5, headwidth=6),
                fontsize=8.5,
                fontweight="bold",
                color="#E65100",
                bbox=dict(boxstyle="round,pad=0.3", fc="#FFE0B2", ec="#FB8C00", lw=1),
                zorder=10,
            )

        ax.set_title(title, fontsize=12, fontweight="bold", pad=15)
        ax.set_xlabel("Elapsed Time from Corridor Entry (Minutes)", fontsize=11, fontweight="bold")
        ax.set_xlim(0, 10)
        ax.set_xticks(range(0, 11))
        ax.set_ylim(-0.15, 2.45)
        ax.grid(True, linestyle="--", alpha=0.45)
        ax.legend(loc="upper left", fontsize=8.5, framealpha=0.95, edgecolor="#B0BEC5")

    # Y-axis ticks and labels on left panel
    axes[0].set_ylabel("Corridor Progression (Distance / Key Hubs)", fontsize=11, fontweight="bold")
    y_ticks = [0.0, 0.35, 0.70, 0.90, 1.15, 1.65, 2.20]
    y_labels = [
        "Albisriederplatz (ALBP, 0.0 km)",
        "Zypressenstr (Main, 0.35 km)",
        "Lochergut (Main, 0.70 km)",
        "Güterbahnhof (North, 0.90 km)",
        "Kalkbreite (Main, 1.15 km)",
        "Helvetiaplatz / Bezirksgeb. (1.65 km)",
        "Stauffacher (STAU, 2.20 km)",
    ]
    axes[0].set_yticks(y_ticks)
    axes[0].set_yticklabels(y_labels, fontsize=9.5)

    fig.suptitle(
        "Zurich Contested Corridor — Space-Time Trajectory Comparison (Format A Deliverable)",
        fontsize=14,
        fontweight="bold",
        y=0.98,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.savefig(output_path, bbox_inches="tight")
    plt.close()
    print(f"[SUCCESS] Space-time Marey chart saved to: {output_path}")


def plot_scorecard(portfolio: dict, output_path: Path):
    """
    Generates a 3-panel executive scorecard for municipal leadership:
      - Panel A: Vehicle Travel Time & Detour Delay (Minutes)
      - Panel B: Cumulative Person-Minutes of Delay (Mass Transit Protection)
      - Panel C: Ethical & Legal Decision Matrix
    """
    fig = plt.figure(figsize=(16, 8.5), dpi=200)
    gs = fig.add_gridspec(2, 2, height_ratios=[1.3, 1.0], width_ratios=[1.4, 1.0], hspace=0.35, wspace=0.25)

    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])
    ax3 = fig.add_subplot(gs[1, :])

    plans_keys = ["plan_1_utilitarian", "plan_2_recommended", "plan_3_strict_spine"]
    plan_names = ["Plan 1\n(Utilitarian Trap)", "Plan 2\n(Recommended)", "Plan 3\n(Strict Spine)"]

    # -------------------------------------------------------------
    # PANEL A: Vehicle Travel Times by Plan
    # -------------------------------------------------------------
    v_keys = ["Ambulance", "Tram", "Dialysis", "Van"]
    v_labels = ["Ambulance", "Tram (185p)", "Dialysis Paratransit", "Delivery Van"]
    colors = ["#D32F2F", "#1565C0", "#7B1FA2", "#E65100"]

    x = np.arange(len(plans_keys))
    bar_w = 0.18

    for i, (vk, vl, col) in enumerate(zip(v_keys, v_labels, colors)):
        times = [portfolio["plans"][pk]["vehicles"][vk]["travel_min"] for pk in plans_keys]
        bars = ax1.bar(x + (i - 1.5) * bar_w, times, bar_w, label=vl, color=col, edgecolor="#37474F", lw=0.8)
        for b in bars:
            h = b.get_height()
            ax1.text(b.get_x() + b.get_width() / 2, h + 0.15, f"{h:g}m", ha="center", fontsize=8, fontweight="bold")

    # Medical deadline reference line
    ax1.axhline(6.5, color="#C2185B", linestyle="--", lw=1.5, alpha=0.85)
    ax1.text(-0.45, 6.75, "Medical Deadline: 6.5 min", color="#C2185B", fontsize=8.5, fontweight="bold", ha="left")

    ax1.set_title("A. Vehicle Travel Times Across Plans (Minutes)", fontsize=11.5, fontweight="bold", pad=10)
    ax1.set_xticks(x)
    ax1.set_xticklabels(plan_names, fontsize=10, fontweight="semibold")
    ax1.set_ylabel("Travel Time (Minutes)", fontsize=10.5)
    ax1.set_ylim(0, 10.2)
    ax1.grid(True, axis="y", linestyle="--", alpha=0.45)
    ax1.legend(loc="upper left", fontsize=8.2, framealpha=0.95, ncol=2)

    # -------------------------------------------------------------
    # PANEL B: Passenger-Minutes of Delay (Mass Transit vs Commercial)
    # -------------------------------------------------------------
    tram_pax_delays = [portfolio["plans"][pk]["vehicles"]["Tram"]["pax_delay_min"] for pk in plans_keys]
    other_pax_delays = [
        sum(portfolio["plans"][pk]["vehicles"][v]["pax_delay_min"] for v in ["Ambulance", "Dialysis", "Van"])
        for pk in plans_keys
    ]

    p1 = ax2.bar(x, tram_pax_delays, width=0.45, label="Tram Commuters (185 pax on Main Spine)", color="#1976D2", edgecolor="#37474F")
    p2 = ax2.bar(x, other_pax_delays, width=0.45, bottom=tram_pax_delays, label="Other Vehicles Detour Delay", color="#FFB300", edgecolor="#37474F")

    for i, (td, od) in enumerate(zip(tram_pax_delays, other_pax_delays)):
        tot = td + od
        ax2.text(x[i], tot + 0.25, f"{tot:.1f} p-min", ha="center", fontsize=9.5, fontweight="bold")

    ax2.set_title("B. Total Passenger-Minutes of Delay\n(Mass Transit Equity)", fontsize=11.5, fontweight="bold", pad=10)
    ax2.set_xticks(x)
    ax2.set_xticklabels(["Plan 1", "Plan 2\n(Recommended)", "Plan 3"], fontsize=10)
    ax2.set_ylabel("Person-Minutes of Delay", fontsize=10.5)
    ax2.set_ylim(0, 8.5)
    ax2.grid(True, axis="y", linestyle="--", alpha=0.45)
    ax2.legend(loc="upper right", fontsize=8.0, framealpha=0.95)

    ax2.text(
        0.5,
        -0.24,
        "Key Finding: Prioritizing Tram (185 pax) on the 5.1m Main Spine avoids 629 person-minutes of commuter delay.",
        transform=ax2.transAxes,
        ha="center",
        fontsize=8.2,
        fontstyle="italic",
        color="#0D47A1",
    )

    # -------------------------------------------------------------
    # PANEL C: Ethical, Legal & Operational Decision Matrix
    # -------------------------------------------------------------
    ax3.axis("off")
    table_data = [
        [
            "Policy Plan",
            "Inviolable Dialysis (<=6.5m)",
            "Tram Mobility (185 Commuters)",
            "Commercial Logistics (Van)",
            "Who Pays the Price?",
            "Legal & Municipal Feasibility",
        ],
        [
            "Plan 1: Utilitarian Speed\n(Weak Penalty P=10)",
            "[VIOLATED] (8.5 min)\nArrives +2.0m late for intake",
            "[PROTECTED] (5.1 min)\nZero commuter delay",
            "Fast Northern Bypass (6.5 min)\nCommercial deliveries prioritized",
            "Dialysis Patient bears critical delay;\nPrivate logistics subsidized.",
            "[DEFENSELESS]: Violates PBG § 4\nand UN CRPD Accessibility obligations.",
        ],
        [
            "Plan 2: Transit & Medical Equity\n(Recommended, Penalty P=50)",
            "[PROTECTED] (6.5 min)\nArrives on time at clinical limit",
            "[PROTECTED] (5.1 min)\nZero commuter delay",
            "Southern Detour (8.5 min)\nAbsorbs +2.0m delivery delay",
            "Commercial Van takes 2m detour;\nZero human rights violated.",
            "[FULLY DEFENSIBLE]: Legally sound,\npolitically robust, protects vulnerable citizens.",
        ],
        [
            "Plan 3: Strict Spine Exclusivity\n(High Conflict Penalty)",
            "[PROTECTED] (6.5 min)\nArrives on time",
            "[CONFLICT ON MAIN SPINE]\nSingle-lane tramway deadlock",
            "Southern Detour (8.5 min)\nAbsorbs +2.0m delivery delay",
            "Tram operations degraded by\nunnecessary single-vehicle exclusion.",
            "[SUBOPTIMAL]: Creates artificial transit\ndisruption when shared passage is feasible.",
        ],
    ]

    table = ax3.table(
        cellText=table_data,
        cellLoc="center",
        loc="center",
        colWidths=[0.18, 0.17, 0.16, 0.16, 0.17, 0.16],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    table.scale(1.0, 1.7)

    # Header styling
    for j in range(6):
        cell = table[0, j]
        cell.set_facecolor("#263238")
        cell.set_text_props(color="white", weight="bold")

    # Row highlight for Plan 2 (Green)
    for j in range(6):
        cell = table[2, j]
        cell.set_facecolor("#E8F5E9")
        cell.set_edgecolor("#388E3C")

    # Row highlight for Plan 1 (Red warning)
    for j in range(6):
        cell = table[1, j]
        cell.set_facecolor("#FFEBEE")

    fig.suptitle(
        "Zurich Contested Corridor — Municipal Head of Planning Decision Scorecard",
        fontsize=14,
        fontweight="bold",
        y=0.98,
    )
    plt.savefig(output_path, bbox_inches="tight")
    plt.close()
    print(f"[SUCCESS] Decision scorecard saved to: {output_path}")


def main():
    base_dir = Path(__file__).resolve().parent
    portfolio = load_portfolio(base_dir)

    plot_space_time_diagrams(portfolio, base_dir / "space_time_comparison.png")
    plot_scorecard(portfolio, base_dir / "winners_losers_scorecard.png")


if __name__ == "__main__":
    main()
