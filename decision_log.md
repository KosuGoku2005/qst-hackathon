# Zurich Contested Corridor: Decision Log
**Challenge Track:** Mobility & Public Network Allocation — Format A  
**Document Purpose:** Mandatory hackathon record of variants explored, discarded architectures, parameter adjustments, and explicit human interventions where AI tool proposals were evaluated and rejected.

---

## 1. Timeline of Explored Variants & Discarded Architectures

### Variant 0: Single-Track Corridor Stop Sequencing (DISCARDED)
* **Initial Concept:** We began by modeling individual stops along Zurich's central spine (Bahnhof Enge $\rightarrow$ Central, and later Freihofstrasse $\rightarrow$ Paradeplatz) as a classical Traveling Salesperson (TSP) / single-corridor sequence using `mqt.problemsolver.tsp`.
* **Why Discarded:** In a fixed public transit line, trams physically move in a single linear sequence determined by rails and switches ($A \rightarrow B \rightarrow C \rightarrow D$). Running a Pathfinder or TSP on a linear path yielded only 1 trivial degree of freedom. There were no alternative route choices or contested trade-offs between competing claims.
* **The Pivot:** We recognized that municipal network allocation only becomes non-trivial when multiple actors compete for **parallel physical routes**. We lifted the problem to the **Kreis 3 / Kreis 4 arterial network**, creating a 3-route macro graph:
  1. Main Transit Spine (Badenerstrasse, 5.1 min)
  2. Northern Bypass (Helvetiaplatz / Langstrasse corridor, 6.5 min)
  3. Southern Bypass (Wiedikon residential arterial, 8.5 min)

---

### Variant 1: Automated Edge Conflict via `pf.PathsShareNoEdges` (DISCARDED)
* **Concept:** Use the built-in MQT ProblemSolver constraint `PathsShareNoEdges(path_1, path_2)` to prevent vehicles from occupying the same route segment simultaneously.
* **Why Discarded:** When generating the QUBO matrix, calling `PathsShareNoEdges` injected **29 auxiliary variables per pair** of competing vehicles. For 4 vehicles ($\binom{4}{2} = 6$ pairs), this added over **174 auxiliary variables**, exploding our 60-variable problem to over 234 qubits. This exceeded local statevector simulation limits and introduced dense off-diagonal noise.
* **Our Solution:** In our hub-and-spoke macro graph, two vehicles share a bypass edge if and only if they select the **same middle vertex at Position 2**. We replaced the library's high-order constraint with a clean, hand-crafted quadratic penalty in the upper-triangular matrix $Q$:
  $$Q[i, j] \mathrel{+}= W_{\text{conflict}} \quad \text{where } i = \text{idx}(a, \text{pos}=2, v), \; j = \text{idx}(b, \text{pos}=2, v)$$
  This enforced exact conflict exclusion with **0 auxiliary variables**, preserving our strict 60-qubit budget.

---

### Variant 2: Binary Logarithmic Encoding (DISCARDED)
* **Concept:** Use `pf.EncodingType.BINARY` to minimize the number of state qubits by encoding vertex indices in binary ($\lceil \log_2 |V| \rceil$).
* **Why Discarded:** While Binary encoding reduced the base positional variables from 60 to 36, quadratizing the path validity and start/end constraints required **80 auxiliary slack variables**, expanding the final QUBO matrix to **116 dimensions**. In contrast, `ONE_HOT` maintained exactly 60 variables with zero slack variables.

---

## 2. Explicit Record of AI Tool Interaction (Where AI Suggestions Were Overruled)

AI coding and reasoning assistants were used throughout this hackathon for data parsing, script drafting, and initial mathematical formulations. Below are the key junctures where the human team explicitly evaluated and **overruled** the AI's recommendations:

### Juncture 1: Naive Penalty Sizing & The "Buy-Off Trap"
* **What the AI Suggested:** When asked to model the 6.5-minute medical deadline for the Dialysis Paratransit, the AI suggested setting the penalty proportional to the average corridor delay:
  ```python
  # AI's Initial Suggestion:
  DEADLINE_PENALTY = 10.0  # Scaled to average detour time (~2 min * 5.0)
  ```
* **Why We Overruled It:** When we analyzed the resulting ground state, the optimizer diverted the Dialysis patient to the 8.5-minute Southern Bypass so the commercial delivery van could take the 6.5-minute Northern Bypass. Because the van had commercial priority weight $k=15$, the optimizer made an algorithmic profit:
  $$\text{Gain} = 15.0 \times (8.5 - 6.5) - 10.0 = +20.0 \text{ energy units}$$
  The AI viewed this as an "optimal solution." We identified this as an unacceptable commodification of an inviolable human health right. We explicitly preserved this flawed AI configuration as **Plan 1 (Utilitarian Trap)** to educate the Head of Planning, and engineered **Plan 2 (Recommended)** with a priority-preserving penalty $P=50.0$, guaranteeing non-violation.

---

### Juncture 2: Enforcing Tram Exclusivity by Halting Road Traffic
* **What the AI Suggested:** The AI proposed adding conflict constraints between the Tram and all road vehicles on the Main Spine:
  ```python
  # AI Suggestion:
  CONFLICT_PAIRS = [(1, 2), (2, 3), (2, 4), (1, 3), (3, 4), (4, 1)]
  ```
* **Why We Overruled It:** On Badenerstrasse, trams run on dedicated center tracks separated from or sharing with emergency vehicles under siren preemption. Banning the Ambulance from sharing the Main Spine with a tram forced the emergency vehicle onto narrow residential bypasses. We restricted the conflict pairs to private road vehicles and paratransit, allowing emergency preemption alongside high-capacity transit. This became the basis of our critique of **Plan 3**.

---

### Juncture 3: Handling Midnight Rollover in VBZ Timestamp Records
* **What the AI Suggested:** Standard datetime subtraction using pandas:
  ```python
  # AI Suggestion:
  travel_time = df["soll_an_nach"] - df["soll_ab_von"]
  ```
* **Why We Overruled It:** In the VBZ Open Government Data, times are recorded as integer seconds past midnight ($0$ to $86,400\,\text{s}$). Trips crossing midnight yielded large negative travel times (e.g., $-86,328\,\text{s}$), which distorted route medians. We corrected the calculation with modulo day arithmetic:
  ```python
  # Human-Engineered Correction:
  tt = df["soll_an_nach"] - df["soll_ab_von"]
  tt = tt.apply(lambda x: x + 86400 if x < 0 else x)
  ```

---

## 3. Summary of Retained Assumptions & Parameters

| Parameter | Final Value | Justification |
| :--- | :---: | :--- |
| **Corridor Horizon** | 3 positions | Origin (ALBP) $\rightarrow$ Choice of 1 of 3 Arterial Routes $\rightarrow$ Destination (STAU) |
| **Ambulance Priority ($k_1$)** | $30.0$ | Life-safety emergency claim must dominate all commercial trade-offs |
| **Tram Priority ($k_2$)** | $1.0$ | Rail-bound constraint ($r_2 = \text{Main}$) handles path locking; avoids artificial distortion |
| **Dialysis Priority ($k_3$)** | $8.0$ | Vulnerable patient transit; high base priority |
| **Van Priority ($k_4$)** | $1.0$ (Plan 2) | Commercial cargo delay carries low societal cost during peak hours |
| **Dialysis Deadline Penalty ($P$)**| $50.0$ | Mathematically proves $P > \max(k) \cdot \Delta T_{\text{detour}}$, preventing algorithmic buy-offs |
| **Route Conflict Weight ($W$)** | $40.0$ | Penalizes shared bypass capacity during morning rush hour |
