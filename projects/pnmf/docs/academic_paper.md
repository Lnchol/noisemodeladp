# HISTORICAL BASELINE — A Dual-Route Parametric Noise Modeling Framework for Future Aircraft Concept Screening in Regulatory Assessment Pipelines

> **Historical pre-integration artifact — not current PNMF documentation.**
> This paper describes the legacy 111-NPD-set v2.3 corpus, the former
> RandomForest/champion workflow, and validation figures measured before ANP
> v6.3 integration. Current PNMF trains on the combined v2.3+v6.3 corpus
> (122 NPD sets; 3,196 NPD rows), supports exactly Extra Trees (`et`, default)
> and Random Forest (`rf`), and treats `PhysicsNPDModel` as a separate
> component-source SEL/LAmax route. Anchor, semi-empirical regression, blend,
> evolve, and champion descriptions below are historical. No numerical result
> in this paper is a post-v6.3 accuracy claim; use current validation artifacts
> and `MIGRATION_PROGRESS_REPORT.md` for present status.

**Authors**: Acoustic Physics Expert, Data Science Metamodellist, Operational Flight Analyst
**Affiliation**: TU Darmstadt / Flight Systems and Automatic Control (FSR), Darmstadt, Germany
**Supervision**: Prof. Klingauf, L. Kempf

---

### Abstract
Conceptual aircraft design requires early-stage environmental impact assessments, yet traditional airport-noise modeling tools (e.g., ECAC Document 29 compliant tools like NIROS) rely on certified Noise-Power-Distance (NPD) tables from the EASA Aircraft Noise and Performance (ANP) database. This reliance creates an evaluation gap for futuristic concepts for which no certification data exists. This paper presents the **Parametric Noise Modeling Framework (PNMF)**, a unified tool designed to map basic parametric aircraft parameters (thrust, weight, engine count, bypass ratio) onto standard EASA ANP-style NPD tables. PNMF implements two fully independent prediction routes: a data-driven RandomForest surrogate trained on the ANP fleet, and a first-principles, pyNA-family physical acoustics model. The surrogate achieves a leave-one-aircraft-out cross-validation error of 4.2–5.4 dB RMSE across the fleet, while the physics model demonstrates a median out-of-sample RMSE of 2.82 dB over a wide bypass ratio (BPR) range (1.0 to 9.6). By integrating an SAE-AIR-1845 flight trajectory synthesizer, PNMF closes the loop from basic concept geometry to observer footprint footprint simulation. The framework is presented as a robust screening tool for conceptual design, and its predictions are validated against the EASA substitution baseline.

---

## I. Introduction
Environmental constraints, particularly airport-neighborhood noise exposure, are critical design drivers for future transport aircraft. The downstream assessment of airport noise is standardized globally by the European Civil Aviation Conference (ECAC) Document 29 and standard SAE International practices. These methodologies compute the single-event sound exposure level ($SEL$) or maximum sound level ($L_{A\text{max}}$) at ground observer locations by interpolating within certified Noise-Power-Distance (NPD) tables.

While this workflow is highly efficient for existing certificated aircraft, it presents a fundamental barrier during conceptual design. A new concept—such as an ultra-high bypass ratio (UHBR) twin-jet—has no certified measurement data. Consequently, designers must either perform expensive, high-fidelity aeroacoustic simulations or manually assign a legacy "proxy" aircraft from the database. The former is computationally prohibitive for multi-variable trade studies, while the latter lacks traceability, physical scaling, and uncertainty awareness.

To resolve this bottleneck, this paper introduces the **Parametric Noise Modeling Framework (PNMF)**. PNMF acts as a bridge, transforming a minimal set of design parameters into EASA-compliant NPD tables. By generating tables in the exact database layout, PNMF enables downstream tools to run conceptual assessments directly within the established regulatory pipeline.

```
ParametricAircraft (Input)
       │
       ├─────────────────────────────────┐
       ▼                                 ▼
[Data-Driven Surrogate]         [First-Principles Physics]
(RandomForest Regressor)         (Stone/Heidmann/Fink Model)
       │                                 │
       └────────────────┬────────────────┘
                        ▼
                     NPDTable (Strict ANP Layout: SEL, LAmax, EPNL, PNLTM)
                        │
                        ▼
           [Departure Trajectory Synthesizer] (SAE-AIR-1845)
                        │
                        ▼
           [Closest-Approach Distance Lookup] (Doc 29 convention)
                        │
                        ▼
           Sideline and Flyover Ground Observer Levels (dBA)
```

---

## II. Methodology

The framework processes a structured `ParametricAircraft` input defined by:
* Maximum Takeoff Weight (MTOW) ($W_{\text{MTOW}}$)
* Maximum Landing Weight (MLW) ($W_{\text{MLW}}$)
* Maximum Static Net Thrust per engine ($T_0$)
* Number of engines ($N$)
* Engine bypass ratio (BPR)
* Regulatory noise chapter (e.g., Chapter 3, 4, or 14)

### A. Route A: Data-Driven RandomForest Surrogate
The data-driven surrogate learns non-linear relationships directly from the real ANP database fleet.

#### 1) Power Feature Normalization
A major data-hygiene issue in the EASA database is the mixing of power units. Power settings ($P$) are recorded in absolute force (lbf), throttle percentage ($\%$), or low-pressure spool speed (RPM) depending on the engine model. Feeding these raw parameters directly into a regression model contaminates the thrust axis.

PNMF implements a power feature formatter that maps these mixed units into a standardized thrust fraction:
$$\overline{P} = \frac{P}{T_0}$$
For spool speed (RPM) settings, where the maximum absolute thrust is non-linear, a table-relative normalization is applied to scale the axis between $[0, 1]$.

#### 2) Isotonic Distance Projection
A physical requirement of any NPD curve is that sound level must decrease monotonically as the observer distance ($d$) increases. Because standard regression algorithms (like RandomForest) do not inherit this physical constraint, unphysical "bumps" can occur in extrapolation regions. To enforce this physical law, PNMF applies an isotonic projection to the predicted levels:
$$\min_{\tilde{\mathbf{L}}} \|\tilde{\mathbf{L}} - \mathbf{L}\|_2^2 \quad \text{subject to} \quad \tilde{L}_{d_i} \ge \tilde{L}_{d_{i+1}} \quad \forall i$$
where $\mathbf{L}$ is the raw surrogate prediction vector at the 10 standard ANP distances ($200$ to $25,000$ ft).

#### 3) Hyperparameter Tuning and Configuration Evolution
The surrogate configuration is optimized using an evolutionary search engine (`evolve.py`) that operates on a persistent trial registry. Configurations (comprising learner types, tree depths, and derived physical features like thrust-to-weight ratios) are mutated and evaluated using Grouped $K$-fold cross-validation. The fitness is scored strictly on measured ANP truth tables to avoid self-reinforcing loops. This optimization successfully evolved the production baseline to a champion configuration utilizing an ExtraTrees ensemble, achieving a cross-validation score of $4.69$ dB RMSE.

---

### B. Route B: First-Principles Physical Acoustics Model
The physical acoustics route operates independently of the surrogate model, serving as a first-principles cross-check. It implements a semi-empirical component-source formulation modeling three primary noise generation mechanisms:

#### 1) Jet Mixing Noise
Jet mixing noise is modeled using Stone's simplified Lighthill formulation. The overall sound pressure level at 1 meter scales with the eighth power of the jet exhaust velocity ($V_j$):
$$\text{OASPL}_{\text{jet}} \propto 10 \log_{10} \left( \frac{\rho_j}{\rho_0} \right)^\omega \left( \frac{V_j}{c_0} \right)^8 A_j$$
where $A_j$ is the nozzle area, $\rho$ represents density, and $c_0$ is the ambient speed of sound. The jet velocity $V_j$ is dynamically estimated from the design bypass ratio (BPR) and net thrust.

#### 2) Turbofan Noise
Turbofan noise is represented using a Heidmann-style fan formulation. The acoustic power scales with the fan mass flow rate ($\dot{m}$) and the fourth power of the fan tip Mach number ($M_{\text{tip}}$):
$$\text{OASPL}_{\text{fan}} \propto 10 \log_{10} \left( \dot{m} \cdot M_{\text{tip}}^4 \right) + f(\text{BPF})$$
where BPF is the blade-passing frequency, which dictates the spectral shape of the fan tone.

#### 3) Airframe Noise
Airframe noise represents the aerodynamic interactions of the wing trailing-edges, flaps/slats, and landing gear, modeled using Fink's correlations. Clean wing airframe noise scales as the fifth power of flight velocity ($V^5$), while flap deflection and landing gear exposure scale as $V^6$:
$$\text{OASPL}_{\text{airframe}} \propto 10 \log_{10} \left( V^5 \cdot b \cdot c \cdot \sin^2\theta \right) + \Delta \text{SPL}_{\text{gear}} + \Delta \text{SPL}_{\text{flaps}}$$
where $b$ is wing span, $c$ is mean aerodynamic chord, and $\theta$ is the emission angle.

#### 4) Atmospheric Propagation and Calibration
The frequency spectrum is synthesized across 24 one-third-octave bands (50 Hz to 10 kHz). Propagation accounts for spherical divergence ($1/r^2$) and frequency-dependent atmospheric absorption modeled per ISO 9613-1. Human auditory response is accounted for by applying standard A-weighting per IEC 61672:
$$L_A = 10 \log_{10} \sum_{i=1}^{24} 10^{0.1 (S_i + A_{\text{wt},i} - \alpha_i d)}$$
where $S_i$ is the source sound level, $A_{\text{wt},i}$ is the A-weighting correction, and $\alpha_i$ is the atmospheric absorption coefficient.

The model is calibrated using four additive component scaling constants ($C_{\text{jet}}$, $C_{\text{fan}}$, $C_{\text{wingflap}}$, $C_{\text{gear}}$). These constants are fitted **once** on a reference A320-211 layout and then frozen, making all subsequent concept evaluations completely out-of-sample.

---

### C. Trajectory Synthesis and Operational Footprint
To evaluate the operational impact of the generated NPD tables, the framework integrates an SAE-AIR-1845 compliant trajectory synthesizer.

#### 1) Flight Performance Equations
The aircraft's takeoff roll distance ($S_g$) is computed based on weight and thrust:
$$S_g = \frac{B \cdot W_{\text{MTOW}}^2}{N \cdot Fn}$$
where $B$ is a runway performance coefficient. The climb angle ($\gamma$) is governed by flight mechanics:
$$\gamma = \arcsin \left[ K \left( \frac{N \cdot Fn}{W} - R \right) \right]$$
where $K$ is the climb acceleration factor, and $R$ is the drag-to-weight ratio. Safe operational envelope guards are implemented, capping climb excess thrust at $80\%$ to prevent trajectory divergence on low-power configurations.

#### 2) Ground Observer Evaluation
For a given ground observer coordinate $(x, y, z)$, the synthesizer slides the aircraft along the trajectory segments. Rather than using segment midpoints (which underestimates noise levels for long segments), PNMF computes the exact analytic closest-approach point on each segment. The slant distance and thrust setting at this closest point are used to query the generated NPD tables via standard Document 29 log-distance and linear-thrust interpolation.

---

## III. Results and Discussion

### A. Fleet-Wide Leave-One-Aircraft-Out Validation
The data-driven surrogate was validated using a leave-one-aircraft-out (LOO) test. In each iteration, a target aircraft was removed from the dataset, the surrogate was trained on the remaining 110 aircraft, and the target's NPD curves were predicted. This simulates the exact execution pattern of a future concept.

Table I summarizes the pooled Root Mean Squared Error ($RMSE$) and Mean Absolute Error ($MAE$) across all 8 metric:mode combinations.

| Metric / Mode | Surrogate RMSE (dB) | Semi-Empirical Baseline RMSE (dB) | Surrogate MAE (dB) |
| :--- | :---: | :---: | :---: |
| **SEL / Departure** | 5.09 | 6.31 | 3.52 |
| **SEL / Approach** | 4.23 | 7.60 | 2.82 |
| **EPNL / Departure** | 5.26 | 6.67 | 3.70 |
| **EPNL / Approach** | 5.05 | 7.92 | 3.45 |
| **LAmax / Departure** | 5.04 | 6.96 | 3.60 |
| **LAmax / Approach** | 4.57 | 8.34 | 3.15 |
| **PNLTM / Departure** | 5.36 | 6.73 | 3.86 |
| **PNLTM / Approach** | 5.25 | 8.21 | 3.61 |

**Table I:** Fleet-wide leave-one-aircraft-out (LOO) validation errors.

---

### B. Case Study: Boeing 737-800 Held Out
A case study was conducted by excluding the Boeing 737-800 (CFM56-7B26 engine) from training. The aircraft parameters were fed into the RF surrogate, the Anchor (default production API), and the frozen physics route. Table II shows the resulting errors against the real certified curves.

| Metric / Mode | RF Surrogate Error (dB) | Anchor Model Error (dB) | Physics Model Error (dB) |
| :--- | :---: | :---: | :---: |
| **SEL / Departure** | 2.85 | 3.29 | **1.96** |
| **SEL / Approach** | 1.20 | **1.09** | 1.59 |
| **LAmax / Departure** | 3.75 | 4.11 | **3.34** |
| **LAmax / Approach** | 1.17 | **1.12** | 1.67 |
| **EPNL / Departure** | **3.86** | 4.16 | — |
| **EPNL / Approach** | 1.54 | **1.51** | — |

**Table II:** Boeing 737-800 validation errors (Approach errors are idle/airframe dominated and remain extremely low, while the physics model demonstrates excellent out-of-sample generalization on departure).

---

### C. Physics Route Out-of-Sample Performance
Table III outlines the validation of the frozen physics route across 12 fleet aircraft representing diverse technology generations and BPR values. The physics model achieved an overall out-of-sample median error of **2.82 dB**.

| Aircraft Type | Engine Model | Bypass Ratio (BPR) | Out-of-Sample RMSE (dB) |
| :--- | :--- | :---: | :---: |
| **A320-232** | V2527-A5 | 4.8 | 2.82 |
| **B737-800** | CFM56-7B26 | 5.1 | 2.25 |
| **B737-300** | CFM56-3B1 | 5.0 | 2.42 |
| **B757-PW** | PW2037 | 4.8 | 3.27 |
| **B757-RR** | RB211-535C | 4.3 | 1.77 |
| **B767-300** | JT9D-7R4D | 4.8 | 2.89 |
| **A330-343** | Trent 772B | 5.0 | 2.29 |
| **B777-300** | GE90-115B | 8.4 | 2.56 |
| **A350-941** | Trent XWB-84 | 9.6 | 4.64 |
| **MD82** | JT8D-217A | 1.7 | 2.82 |
| **B727-EM2** | JT8D-15 | 1.0 | 4.85 |
| **B747-200** | JT9D-7A | 5.0 | 3.55 |

**Table III:** Out-of-sample RMSE of the physics route across the validation fleet (median RMSE: 2.82 dB, mean: 3.01 dB).

---

### D. Practical Accuracy Ceiling (EASA Substitution Comparison)
EASA's official regulatory methodology for un-tabulated aircraft relies on manual substitution, where experts assign the new aircraft to a real ANP proxy. An evaluation of this EASA substitution table against certification truth across 19,565 aircraft reveals a baseline mismatch of **1.92 dB (departure)** and **1.35 dB (approach)**.

Since a hand-picked real-world proxy represents the theoretical limit of proxy-based accuracy, PNMF's parametric performance (LOO RMSE of 4.2–5.4 dB) represents an acceptable and highly traceable alternative for conceptual design trade studies.

---

### E. Futuristic Concept Assessment (UHBR Twin-Jet)
To demonstrate the framework's utility on futuristic designs, a twin-jet concept utilizing Ultra-High Bypass Ratio engines was evaluated: **FUTURE-UHBR-TWIN** ($2 \times 30,000$ lbf engines, BPR 15, MTOW $170,000$ lb, noise Chapter 14).
1. **Uncertainty Mapping**: The surrogate predicts the NPD tables with a mean cross-tree standard deviation ($\sigma$) of $2.14$ dB. This is higher than the typical in-fleet spread ($1.0-1.5$ dB), raising a `caution` flag to the designer indicating extrapolation.
2. **Dual-Route Agreement**: The independent physics route predicts a mean SEL difference of only $2.8$ dB against the evolved champion surrogate, indicating a high degree of convergence.
3. **Operational Assessment**: In a simulated sideline observer flight profile, the UHBR concept achieves a **$-1.3$ dB peak LAmax** reduction compared to a standard A320-211 baseline, validating the expected acoustic trend.

---

## IV. Scope Boundaries and Future Work

1. **Feature Set Expansion**: Currently, the surrogate relies on thrust, weight, engine count, and noise chapter. Integrating detailed wing geometry (span, wing area) and engine deck cycles from concept synthesis tools like CPACS, PrADO, or RCAIDE represents the highest-priority next step.
2. **Configuration Limitations**: Neither route is validated for non tube-and-wing concepts (e.g., blended-wing-body or distributed propulsion) due to their absence in the ANP database.
3. **Downstream Interface**: Ground reflections, lateral attenuation, and lateral duration corrections are intentionally omitted from PNMF and are left to the consuming Doc-29 calculation tool.

---

## V. Conclusions
The Parametric Noise Modeling Framework (PNMF) provides a robust, traceable, and physically-constrained method for generating ANP-layout NPD tables for early-stage conceptual aircraft. By offering two independent routes—a data-driven surrogate with built-in uncertainty quantification and a frozen first-principles physical acoustics model—PNMF allows concept designers to identify risk and evaluate future configurations directly within standard regulatory assessment pipelines.

---

## Appendix: Nomenclature

| Symbol | Description | Unit |
| :--- | :--- | :---: |
| **SEL** | Sound Exposure Level | dB |
| **LAmax** | Maximum A-weighted Sound Level | dBA |
| **EPNL** | Effective Perceived Noise Level | EPNdB |
| **PNLTM** | Maximum Tone-Corrected Perceived Noise Level | dB |
| **MTOW** | Maximum Takeoff Weight | lb |
| **MLW** | Maximum Landing Weight | lb |
| **BPR** | Engine Bypass Ratio | — |
| **Fn** | Net Thrust per Engine | lbf |
| **$S_g$** | Takeoff Ground Roll Distance | ft |
| **$\gamma$** | Flight Climb Angle | rad |
| **BPF** | Blade-Passing Frequency | Hz |
| **$M_{\text{tip}}$** | Fan Tip Mach Number | — |
| **$V_j$** | Jet Exhaust Velocity | m/s |
| **$d$** | Slant Distance to Ground Observer | ft |

---

## References
1. *ECAC Document 29*, "Report on Standard Method of Computing Noise Contours around Civil Airports", European Civil Aviation Conference, 3rd Edition, 2005.
2. *SAE AIR-1845*, "Procedure for the Calculation of Airplane Noise in the Vicinity of Airports", Aerospace Information Report, SAE International, 1986.
3. *ISO 9613-1*, "Acoustics — Attenuation of sound during propagation outdoors — Part 1: Calculation of the absorption of sound by the atmosphere", International Organization for Standardization, 1993.
4. Stone, J. R., "A simplified method for predicting jet noise in flight", NASA Technical Memorandum, 1979.
5. Heidmann, M. F., "Interim prediction method for fan and compressor source noise", NASA Technical Memorandum, 1979.
6. Fink, M. R., "Airframe noise prediction method", Federal Aviation Administration Report FAA-RD-77-29, 1977.
