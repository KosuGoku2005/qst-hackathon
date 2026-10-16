# Zurich Contested Corridor: Responsibility & Sustainability Note
**Challenge Track:** Mobility & Public Network Allocation — Format A  
**Focus Area:** Ethical Optimization, Human Rights in Algorithmic Governance, and Climate Sustainability  
**Statutory & Ethical Frameworks:** Canton of Zurich Planning & Building Act (PBG § 4), UN Convention on the Rights of Persons with Disabilities (CRPD), Swiss Federal Constitution (Art. 8, Equality before the Law).

---

## 1. What Our Allocation Plans Support

### 1.1 Inviolable Protection of Vulnerable Paratransit
In municipal traffic management, vulnerable road users and paratransit patients are routinely disadvantaged by utilitarian algorithms that optimize solely for aggregate vehicle speed or economic productivity. 
* **Plan 2 explicitly guarantees** that the Dialysis Paratransit patient reaches the Stauffacher clinic within the **6.5-minute medical threshold**, ensuring clinical intake without physiological decompensation.
* By enforcing a priority-preserving penalty ($P=50.0$), our model treats healthcare access not as a negotiable commodity with a price tag, but as an **inviolable right** protected under Swiss disability rights law.

### 1.2 Defense of High-Capacity Mass Transit & Climate Goals
A standard private-vehicle-centric optimizer might seek to divert the tram or restrict its right-of-way to relieve bottlenecks for mixed road traffic.
* Our formulation locks the **VBZ Tram Line 2 (185 commuters)** to the 5.1-minute Main Spine.
* As demonstrated in our decision scorecard, keeping the tram on its optimal schedule **saves 629 citizen-minutes of commuter delay** compared to a diversion scenario ($185 \text{ passengers} \times 3.4 \text{ min detour} = 629 \text{ person-minutes}$).
* This preserves public transit punctuality, prevents mode shift toward private automobiles, and directly upholds Zurich's municipal 2000-Watt Society climate commitments.

---

## 2. What the Model Leaves Out or Flattens

Responsible deployment of automated decision tools requires transparently acknowledging model abstractions:

1. **Hospital Bed & Clinical Triage Dynamics:** The model flattens the hospital intake process into a single binary deadline ($t \le 6.5\,\text{min}$). In reality, hospital intake capacity fluctuates dynamically. An emergency department on diversion status might require re-routing an ambulance to Triemli or Universitätsspital, altering the corridor boundary conditions.
2. **Pedestrian & Active Travel Modes:** Our current graph captures vehicular transit across three arterials. It flattens the heavy pedestrian and cycling volumes on *Helvetiaplatz* and *Langstrasse*. Routing a commercial delivery van or paratransit vehicle through the Northern Bypass increases vehicle-pedestrian conflict risks in dense urban neighborhood zones.
3. **Residential Environmental Externalities (Kreis 3 / Wiedikon):** Detouring commercial logistics onto the Southern Bypass shifts noise and particulate emissions ($\text{PM}_{2.5}$, $\text{NO}_x$) into residential side streets (*Schmiede Wiedikon*). The model currently captures travel time but does not assign an acoustic or air quality penalty to residential bypass corridors.
4. **Stochastic Incident Queuing:** The travel times are calibrated using historical median planned and actual travel times from VBZ open data. It does not model acute cascading queues caused by minor fender-benders or delivery double-parking along Badenerstrasse.

---

## 3. Whose Claims the Model Could Not Represent

* **Informal & Unregistered Deliveries:** While corporate parcel logistics (commercial vans) are explicitly modeled, gig-economy couriers (cargo e-bikes, food delivery riders) lack dedicated network representation in current municipal macro-models.
* **Non-Emergency Patient Transport:** Patients traveling via public transit or private car to outpatient appointments rather than dedicated paratransit are subsumed within general commuter counts, obscuring their specific accessibility hurdles.

---

## 4. Municipal Requirements Before Full-Scale City Deployment

Before the City of Zurich could rely on this quantum-assisted allocation system for automated morning peak traffic dispatch, the following three institutional safeguards must be established:

### 4.1 Legal & Democratic Non-Discrimination Audit
The City Council must conduct a formal administrative review certifying that the penalty functions and priority weights $k_p$ conform to **Canton of Zurich PBG § 4** and do not establish unconstitutional private subsidies. The algorithm must never permit a commercial delivery consortium to "buy out" priority slots reserved for emergency, paratransit, or mass transit operations.

### 4.2 Human-in-the-Loop Contestation Dashboard
Algorithmic network allocation must never be a black box. Dispatchers at VBZ Traffic Control (*Leitstelle*) and Zurich Protection & Rescue (*Schutz & Rettung Zürich*) must have real-time visibility into why specific detours were assigned. Paratransit operators must possess a **"Right of Contestation" button** on their vehicle dispatch terminal, allowing drivers to override an assigned detour if a patient presents acute medical distress.

### 4.3 Adaptive Signal Preemption Integration
The mathematical assignment of Route 2 (Northern Bypass) to the Dialysis vehicle assumes a 6.5-minute traversal. To guarantee this in real operations, the Tiefbauamt must interconnect this allocation model with Zurich's dynamic traffic signal controllers (LSA), granting automated green-wave priority at the *Kalkbreite* and *Helvetiaplatz* intersections.
