# Zurich Contested Corridor: Findings Note
**Challenge Track:** Mobility & Public Network Allocation — Format A ("Make the Case")  
**Target Decision-Maker:** Municipal Head of Planning, City of Zurich (Verkehrsbetriebe Zürich / Tiefbauamt)  
**Authors:** Quantum Mobility Hackathon Team  
**Artifacts Generated:** `space_time_comparison.png`, `winners_losers_scorecard.png`, `decision_portfolio.json`

---

## Executive Summary: The Algorithmic Dilemma on Badenerstrasse
During the Zurich morning peak (07:30–08:30), the 2.2 km artery from **Albisriederplatz (ALBP)** to **Stauffacher (STAU)** experiences chronic congestion. Four legitimate claims compete for limited corridor capacity:
1. **Life-Safety Emergency (Ambulance):** Priority weight $k=30$, inviolable survival claim.
2. **High-Capacity Public Transit (VBZ Tram Line 2, 185 Commuters):** Rail-bound, working-class mobility backbone, high modal efficiency.
3. **Vulnerable Healthcare Access (Dialysis Paratransit):** Strict, non-negotiable **6.5-minute medical intake deadline** at Stauffacher clinic.
4. **Commercial Urban Logistics (Delivery Van):** Private e-commerce delivery claim, economic value.

When municipal traffic managers turn to mathematical optimization or Quantum Unconstrained Binary Optimization (QUBO), an immediate ethical vulnerability arises: **The Utilitarian "Buy-Off" Trap.** If an inviolable medical right is modeled as a linear cost or an inadequate soft penalty ($P \le 20$), standard optimizers trade away the vulnerable patient's health to shave trivial seconds off private commercial delivery.

This report presents a defensible, multi-objective formulation built with **MQT ProblemSolver** and solved via **Simulated Annealing (`dimod`)** that rigorously prevents this buy-off, proving that equity and throughput can be simultaneously achieved.

---

## 1. Network Formulation & Mathematical Architecture

### 1.1 The 3-Route Macro Corridor
From open VBZ travel time records (`fahrzeiten_soll_ist`) and Zurich GIS stop data, we abstracted the contested network into a 5-vertex, 3-route directed macro-graph:
* **Route 1 — Main Transit Spine (Badenerstrasse):** 5.1 min ($306\,\text{s}$). Direct tram tracks via *Zypressenstrasse, Lochergut, Kalkbreite, Bezirksgebäude*. Highest throughput.
* **Route 2 — Northern Bypass (Helvetiaplatz / Kreis 4):** 6.5 min ($390\,\text{s}$). Road bypass via *Güterbahnhof* and *Helvetiaplatz*. Matches the exact dialysis deadline limit.
* **Route 3 — Southern Bypass (Wiedikon / Kreis 3):** 8.5 min ($510\,\text{s}$). Longer arterial detour via *Schmiede Wiedikon* and *Bhf. Wiedikon Süd*.

### 1.2 QUBO Encoding & Variable Budget
Using **MQT ProblemSolver 0.5.0 Pathfinder** (`pf.PathFindingQuboGenerator`), each vehicle $p \in \{1, 2, 3, 4\}$ traverses $N_{\text{pos}}=3$ positions across $|V|=5$ vertices. Under **One-Hot Encoding**, this establishes a compact formulation:
$$\text{Variables} = N_{\text{vehicles}} \times N_{\text{positions}} \times |V| = 4 \times 3 \times 5 = 60 \text{ binary qubits}$$
This 60-variable layout maps onto NISQ quantum annealing hardware (D-Wave Advantage) and classical statevector simulators with zero auxiliary variable bloat.

The objective function balances travel time, vehicle priorities $k_p$, deadline penalties, and route conflicts:
$$H(x) = \sum_{p=1}^4 k_p \cdot T(r_p) + P_{\text{deadline}} \cdot \mathbb{I}(T(r_3) > 6.5) + \sum_{(a,b) \in \mathcal{C}} W_{\text{conflict}} \cdot \mathbb{I}(r_a = r_b) + H_{\text{validity}}(x)$$

---

## 2. Quantitative Comparison of the Decision Portfolio

We evaluated three policy configurations across all $3^4 = 81$ structurally valid allocations and validated them across 5 independent annealing seeds (250 reads, 1,000 sweeps):

| Metric / Outcome | Plan 1: Utilitarian Speed (Buy-Off Trap) | Plan 2: Transit & Medical Equity (**Recommended**) | Plan 3: Strict Spine Exclusivity |
| :--- | :---: | :---: | :---: |
| **Objective / Policy Thesis** | Maximize aggregate vehicle speed | Protect non-negotiable rights & transit | Disallow concurrent tram/car spine use |
| **Dialysis Penalty ($P$)** | $P = 10.0$ (Weak penalty) | $P = 50.0$ (Priority-preserving) | $P = 50.0$ (Priority-preserving) |
| **Ambulance Allocation** | Main Spine (5.1 min) | Main Spine (5.1 min) | Main Spine (5.1 min) |
| **Tram (185 Pax) Allocation** | Main Spine (5.1 min) | Main Spine (5.1 min) | Main Spine (5.1 min) [Conflict] |
| **Dialysis Paratransit** | **Southern Detour (8.5 min)** | **Northern Bypass (6.5 min)** | **Northern Bypass (6.5 min)** |
| **Delivery Van Allocation** | Northern Bypass (6.5 min) | Southern Detour (8.5 min) | Southern Detour (8.5 min) |
| **Dialysis Deadline Met?** | **FAILED (Arrives +2.0m LATE)** | **SATISFIED (On-Time at 6.5m)** | **SATISFIED (On-Time at 6.5m)** |
| **Total Commuter Delay** | **0.0 person-minutes** | **0.0 person-minutes** | **0.0 person-minutes** |
| **Commercial Logistics Delay** | +1.4 min detour | +3.4 min detour (+2.0m vs Plan 1) | +3.4 min detour |
| **QUBO Energy Gap ($\Delta E$)** | $+16.0$ to runner-up | **$+26.8$ to runner-up (Robust ground state)** | $+23.8$ to runner-up |
| **Annealing Hit Rate (5 seeds)** | 0/5 seeds hit ground state | **4/5 seeds hit optimal ground state** | 0/5 seeds hit ground state |

### The Core Finding: How Naive Optimization Sells Out Rights
In **Plan 1**, the commercial delivery van has an economic priority weight of $k_4 = 15.0$. If forced onto the 8.5-min Southern Bypass, the van incurs a penalty of $15.0 \times (8.5 - 6.5) = 30.0$. Because the planner set the dialysis penalty to a "reasonable" value of $P=10.0$, the optimizer calculates:
$$\Delta H_{\text{swap}} = \text{Penalty}_{\text{Dialysis}} + \text{Cost}_{\text{Dialysis}} - \text{Savings}_{\text{Van}} = 10.0 + 2.0 \times (8.5 - 6.5) - 30.0 = -16.0$$
The solver happily takes the **16.0 unit energy discount**, sacrificing the patient's clinical intake to let commercial packages arrive 2 minutes earlier.

In **Plan 2 (Recommended)**, setting $P_{\text{deadline}} = 50.0$ satisfies the priority condition $P > \max(k) \cdot \Delta T_{\text{detour}} = 15.0 \times 2.0 = 30.0$. The dialysis slot on the Northern Bypass becomes strictly inviolable. The van absorbs the 2-minute detour, preserving social equity with zero disruption to the 185 tram commuters.

---

## 3. Toolchain & Encoding Benchmark

We benchmarked three MQT ProblemSolver encoding strategies on this network:
1. **ONE_HOT (Our Choice):** Exactly 60 variables, 328 non-zero quadratic couplings. Transparent 1-to-1 physical mapping. Fast simulated annealing convergence.
2. **DOMAIN_WALL:** Exactly 60 variables, 196 non-zero couplings (tighter connectivity). Slightly reduced coupler density, but identical qubit footprint.
3. **BINARY (Logarithmic):** While base positional variables dropped to 36, the quadratization of 3-path and 4-path constraints required **80 auxiliary slack variables**, blowing the matrix dimension to **116 variables** with dense off-diagonal noise. **We explicitly rejected Binary encoding due to auxiliary bloat.**

---

## 4. Operational Breakdown & What We Would Do With Another Week
* **Where the model breaks down:** Our current model assumes static free-flow travel times per route. In actual morning peaks, detouring commercial vans onto Wiedikon can cause spillover congestion if arterial intersections lack adaptive signal priority.
* **Next Steps:** With an additional week, we would:
  1. Integrate open GTFS frequency data to model headway synchronization with cross-town lines (Trams 3, 4, 14 at Stauffacher).
  2. Implement stochastic queue dynamics at the Kalkbreite bottleneck using Qiskit Aer noise models.
  3. Deploy the 60-variable QUBO directly to physical quantum annealers (D-Wave Advantage) via the QDMI cloud stack.
