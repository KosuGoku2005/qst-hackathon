#!/usr/bin/env python3
"""
plot_space_time.py
-------------------
Generates non-specialist visual artifacts for the Head of Planning (Format A deliverable):
  1. Space-Time Diagram (Marey Chart): Visualizes the trajectories of all 5 competing vehicles
     along the Zurich corridor over time for Plan 1 vs Plan 2.
  2. Winners & Losers Scorecard Dashboard: Bar chart showing delays by actor and total passenger impact.

Saves figures to:
  - space_time_comparison.png
  - winners_losers_scorecard.png
"""

from pathlib import Path
import json
import matplotlib.pyplot as plt
import numpy as np


def load_portfolio(base_dir: Path):
    with open(base_dir / "decision_portfolio.json", "r", encoding="utf-8") as f:
        return json.load(f)


def plot_space_time_diagrams(portfolio: dict, output_path: Path):
    """
    Plots side-by-side Space-Time (Marey) charts comparing:
    - Plan 1: Utilitarian Traffic Efficiency (Dialysis traded away)
    - Plan 2: Transit & Inviolable Equity (Council Recommendation)
    """
    stops = portfolio["metadata"]["corridor_stops"]
    num_stops = len(stops)

    fig, axes = plt.subplots(1, 2, figsize=(16, 7.5), sharey=True, dpi=200)

    plans_to_plot = [
        ("plan_1_utilitarian", axes[0], "Plan 1: Traffic Efficiency (Utilitarian)\n❌ Inviolable Dialysis Traded Away"),
        ("plan_2_equity", axes[1], "Plan 2: Transit & Equity-First (Recommended)\n✅ All Inviolable Rights Protected"),
    ]

    # Style configuration
    styles = {
        "ambulance": {"label": "Ambulance (Life-Safety)", "color": "#D32F2F", "ls": "-", "lw": 3.2, "marker": "o"},
        "dialysis": {"label": "Dialysis Paratransit", "color": "#7B1FA2", "ls": "-", "lw": 3.0, "marker": "s"},
        "tram": {"label": "VBZ Tram (185 Pax)", "color": "#1976D2", "ls": "-", "lw": 3.0, "marker": "^"},
        "delivery": {"label": "Delivery Van", "color": "#F57C00", "ls": "--", "lw": 2.2, "marker": "D"},
        "car": {"label": "Commuter Cars", "color": "#616161", "ls": ":", "lw": 2.0, "marker": "v"},
    }

    for plan_key, ax, title in plans_to_plot:
        plan_data = portfolio["plans"][plan_key]
        sched = plan_data["schedule"]

        # Bottleneck corridor shading (Stops 2 to 4)
        ax.axhspan(2 - 0.25, 4 + 0.25, color="#FFF9C4", alpha=0.5, zorder=0, label="Bottleneck (Single Capacity)")

        # Dialysis deadline line at destination stop
        ax.axvline(11, color="#E91E63", linestyle="--", alpha=0.7, lw=1.5, zorder=1)
        ax.text(11.1, num_stops - 1.35, "Dialysis Deadline (08:11)", color="#C2185B", fontsize=9, fontweight="bold")

        # Plot each vehicle trajectory
        for k, style in styles.items():
            if k not in sched:
                continue
            v_data = sched[k]
            dep_t = v_data["dep_time"]
            arr_t = v_data["arr_time"]

            # Vehicle trajectory points
            if k == "dialysis":
                # Starts at pickup stop 2
                stop_indices = list(range(2, 7))
                times = [dep_t + (s - 2) for s in stop_indices]
            elif k == "delivery":
                # Operates stops 1 to 4
                stop_indices = list(range(1, 5))
                times = [dep_t + (s - 1) for s in stop_indices]
            elif k == "car":
                stop_indices = list(range(0, 6))
                times = [dep_t + s for s in stop_indices]
            else:
                # Full corridor (ambulance & tram)
                stop_indices = list(range(0, 7))
                times = [dep_t + s for s in stop_indices]

            # Mark late arrival for dialysis
            if k == "dialysis" and not v_data["met_deadline"]:
                line_color = "#E53935"
                line_label = f"{style['label']} (MISSED DEADLINE: 08:{arr_t:02d})"
            elif k == "dialysis":
                line_color = style["color"]
                line_label = f"{style['label']} (ARRIVED: 08:{arr_t:02d})"
            else:
                line_color = style["color"]
                line_label = f"{style['label']} (Delay: +{v_data['delay_min']}m)"

            ax.plot(
                times,
                stop_indices,
                label=line_label,
                color=line_color,
                linestyle=style["ls"],
                linewidth=style["lw"],
                marker=style["marker"],
                markersize=6,
                zorder=3,
            )

        ax.set_title(title, fontsize=12, fontweight="bold", pad=12)
        ax.set_xlabel("Time of Day (Minutes past 08:00)", fontsize=11)
        ax.set_xlim(1.5, 16.5)
        ax.set_xticks(range(2, 17))
        ax.set_xticklabels([f"08:{m:02d}" for m in range(2, 17)])
        ax.set_ylim(-0.5, num_stops - 0.5)
        ax.set_yticks(range(num_stops))
        ax.set_yticklabels([f"[{i}] {name}" for i, name in enumerate(stops)], fontsize=10)
        ax.grid(True, linestyle="--", alpha=0.45)
        ax.legend(loc="upper left", fontsize=8.5, framealpha=0.92)

    axes[0].set_ylabel("Zurich Corridor Stops", fontsize=11, fontweight="bold")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    print(f"[SUCCESS] Space-time comparison saved to: {output_path}")


def plot_scorecard(portfolio: dict, output_path: Path):
    """Generates an intuitive bar chart scorecard for city decision-makers."""
    plans = ["Plan 1: Traffic Efficiency", "Plan 2: Transit & Equity", "Plan 3: Commercial Compromise"]
    keys = ["plan_1_utilitarian", "plan_2_equity", "plan_3_commercial"]

    amb_delays = [portfolio["plans"][k]["ambulance_delay"] for k in keys]
    tram_delays = [portfolio["plans"][k]["tram_delay"] for k in keys]
    delivery_delays = [portfolio["plans"][k]["delivery_delay"] for k in keys]
    car_delays = [portfolio["plans"][k]["car_delay"] for k in keys]
    dialysis_met = [portfolio["plans"][k]["dialysis_met_deadline"] for k in keys]

    x = np.arange(len(plans))
    width = 0.18

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6), dpi=180, gridspec_kw={"width_ratios": [2.2, 1]})

    # Vehicle delays
    ax1.bar(x - 1.5 * width, amb_delays, width, label="Ambulance", color="#D32F2F")
    ax1.bar(x - 0.5 * width, tram_delays, width, label="Tram (185 Pax)", color="#1976D2")
    ax1.bar(x + 0.5 * width, delivery_delays, width, label="Delivery Van", color="#F57C00")
    ax1.bar(x + 1.5 * width, car_delays, width, label="Commuter Cars", color="#757575")

    ax1.set_title("Vehicle Delays by Allocation Plan (Minutes)", fontsize=13, fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels(plans, fontsize=10, fontweight="semibold")
    ax1.set_ylabel("Delay Incurred (Minutes)", fontsize=11)
    ax1.set_ylim(0, 5)
    ax1.grid(True, axis="y", linestyle="--", alpha=0.5)
    ax1.legend(loc="upper right", fontsize=9.5)

    # Dialysis status callouts
    for i, met in enumerate(dialysis_met):
        text = "Dialysis: ON TIME ✅" if met else "Dialysis: MISSED ❌"
        color = "#2E7D32" if met else "#C62828"
        ax1.text(x[i], 4.4, text, ha="center", fontsize=10, fontweight="bold", color=color,
                 bbox=dict(boxstyle="round,pad=0.3", fc="#FAFAFA", ec=color, lw=1.5))

    # Total Passenger-Minutes of Delay
    total_pax_delay = [portfolio["plans"][k]["total_pax_delay"] for k in keys]
    bars = ax2.bar(plans, total_pax_delay, color=["#E57373", "#81C784", "#64B5F6"], width=0.55, edgecolor="#37474F", lw=1.2)
    ax2.set_title("Total Passenger-Minutes of Delay\n(Equity Impact)", fontsize=12, fontweight="bold")
    ax2.set_ylabel("Total Person-Minutes", fontsize=11)
    ax2.set_xticks(x)
    ax2.set_xticklabels(["Plan 1", "Plan 2\n(Recommended)", "Plan 3"], fontsize=10)
    ax2.grid(True, axis="y", linestyle="--", alpha=0.5)

    for bar in bars:
        yval = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width() / 2, yval + 12, f"{int(yval)} p-min", ha="center", fontsize=10, fontweight="bold")

    ax2.set_ylim(0, max(total_pax_delay) * 1.25)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    print(f"[SUCCESS] Scorecard saved to: {output_path}")


def main():
    base_dir = Path(__file__).resolve().parent
    portfolio = load_portfolio(base_dir)

    plot_space_time_diagrams(portfolio, base_dir / "space_time_comparison.png")
    plot_scorecard(portfolio, base_dir / "winners_losers_scorecard.png")


if __name__ == "__main__":
    main()
