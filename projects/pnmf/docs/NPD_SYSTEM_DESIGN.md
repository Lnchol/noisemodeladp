# PNMF — NPD System Design Reference

> Core formulas and invariants are implementation-grounded. The supported
> learned models are exactly ET and RF. Component physics is the separate
> `PhysicsNPDModel` workflow.

**Parametric Noise Modeling Framework** · TU Darmstadt / FSR Advanced Design
Project (Prof. Klingauf, supervised by L. Kempf)

*This is the system design reference: the current public API surface, formulas
and assumptions, grounded in the code as of 2026-07-28.
Companion documents: `README.md` (narrative, fault log, validation writeup),
`docs/HOW_IT_WORKS.md` (plain-language walkthrough),
`docs/MODEL_TRAINING_REPORT.md` (current learned-model evidence), and
`docs/PNMF_COMPONENT_PHYSICS_TECHNICAL_PAPER.pdf` (physics equations,
architecture and research gaps).*

---

## 1. Purpose & scope

PNMF maps a **parametric aircraft definition** (thrust, weights, engine
count/type, optionally geometry and bypass ratio) onto an **NPD-equivalent
noise table** in the exact layout of the EASA ANP database: a grid of
single-event levels (SEL, LAmax, EPNL, PNLTM) over engine power settings and
the ten standard slant distances, per operational mode (Approach/Departure).
Future aircraft concepts have no certification data and therefore no NPD
entry; PNMF generates one so that such concepts can be assessed inside the
established ANP/Doc-29 noise pipeline (FSR/NIROS or any Doc-29 consumer)
without modifying that pipeline.

Two fully independent prediction routes are implemented and cross-check each
other: a data-driven surrogate trained on the ANP fleet (`pnmf/models.py`)
and a from-scratch physics model (`pnmf/physics.py`) calibrated once and then
frozen. The division of labor follows the Doc-29 split: PNMF delivers the NPD
table and an operational profile; lateral attenuation, ground effect and
energy-fraction/duration corrections remain the consumer tool's job.

---

## 2. Data layer (`pnmf/anp.py`)

`ANPDatabase(root)` loads and joins the EASA ANP v2.3 data. The central join
is Aircraft ↔ NPD_data on `NPD_ID`, which gives every NPD curve a parametric
descriptor row.

**Storage precedence — sqlite first, CSVs fallback.** If `anp_data.sqlite`
exists in `root` (or `root` itself ends in `.sqlite`), all tables are read
from it; otherwise the loader falls back to the nine loose,
semicolon-delimited `ANP2_3_*.csv` files, matched by **exact filename**
(`os.path.join(root, name)` — no globbing, no fuzzy matching). Both paths
yield identical DataFrames (verified: the LOO validation table reproduces
from either source).

**CSV → table map** (`CSV_TABLES`; the first three are required, the rest
optional):

| CSV file | sqlite table | required |
|---|---|---|
| `ANP2_3_Aircraft.csv` | `anp_aircraft` | yes |
| `ANP2_3_NPD_data.csv` | `anp_npd_data` | yes |
| `ANP2_3_Jet_engine_coefficients.csv` | `anp_jet_engine_coefficients` | yes |
| `ANP2_3_Propeller_engine_coefficients.csv` | `anp_propeller_engine_coefficients` | no |
| `ANP2_3_Aerodynamic_coefficients.csv` | `anp_aerodynamic_coefficients` | no |
| `ANP2_3_Default_departure_procedural_steps.csv` | `anp_default_departure_procedural_steps` | no |
| `ANP2_3_Default_approach_procedural_steps.csv` | `anp_default_approach_procedural_steps` | no |
| `ANP2_3_Default_fixed_point_profiles.csv` | `anp_default_fixed_point_profiles` | no |
| `ANP2_3_Default_weights.csv` | `anp_default_weights` | no |

**Data hygiene** (`_clean()`): the raw ANP CSVs carry trailing whitespace in
string cells (e.g. `Flap_ID 'T_05  '`) that silently breaks joins — all
string columns and column names in every loaded table are stripped centrally
at load. Numeric coercion (`pd.to_numeric(errors='coerce')`) is applied to
the aircraft weight/thrust/engine-count columns and to `Power Setting` plus
the ten level columns (`DIST_COLS = L_200ft … L_25000ft`).

**Key methods:**

- `param_table()` — one parametric descriptor row per `NPD_ID` (the model's
  X features). Where several aircraft share an `NPD_ID`, the heaviest (by
  MTOW) is kept as representative.
- `curve(npd_id, metric, op_mode)` — the NPD rows (power settings × 10
  distances) for one curve set, sorted by power setting.
- `list_curve_sets(metric, op_mode)` — all `NPD_ID`s that have a curve set
  for the given metric/mode *and* a descriptor row in `param_table()`.
- `nearest_aircraft(mtow_lb, engine_type=None, n_engines=None, n=3,
  restrict_to=None)` — the n closest ANP aircraft by |Δ log10(MTOW)|, plus a
  `0.15 · |Δ n_engines|` penalty when an engine count is given, restricted to
  the same engine type when ≥ n candidates of that type exist. Mirrors the
  criteria of EASA's own substitution methodology; used to borrow a
  representative default procedure for a future aircraft.
- `nearest_npd_ids(mtow_lb, engine_type=None, n_engines=None, n=3)` — thin
  helper over `nearest_aircraft`: maps the candidate `ACFT_ID` rows to their
  `NPD_ID`s and de-duplicates, preserving distance order. Added for the
  real-vs-future report (§10), where curve lookups are keyed by `NPD_ID`.
- `aircraft_with_profile(op_type)` — `ACFT_ID`s with a usable fixed-point
  profile (the ANP fixed-point table only covers a small subset).
- `load_substitution_table(path)` — the "by aircraft configuration" sheet of
  the published ANP substitution workbook: ~19.5k certificated aircraft with
  measured lateral/flyover/approach EPNL and each record's mismatch vs its
  assigned ANP proxy. Independent of the NPD-curve fleet; used only for
  external validation (§11).

---

## 3. Truth/prediction separation invariant

One sqlite file (`anp_data.sqlite`) holds both the ANP ground truth and the
framework's own predictions, kept apart by a hard write-path invariant:

1. **`anp_*` truth tables are written by exactly one function** —
   `build_datastore(root)` in `pnmf/anp.py`, which converts the staged CSVs
   verbatim (`pd.read_csv(sep=';')` → `to_sql(if_exists="replace")`) and
   records provenance in `anp_meta`. The CLI wrapper (`pnmf_cli.py
   datastore`) verifies the conversion lossless cell-by-cell. Rebuilding the
   truth tables never touches `predicted_*` tables.
2. **Model output goes only into `predicted_aircraft` / `predicted_npd`**,
   and only through `PredictionStore` (`pnmf/anp.py`), which creates exactly
   those two tables (its writes are limited to their DDLs) and gates every
   table through `qa_check` (§8). `predicted_aircraft` has
   `PRIMARY KEY (name, model)`; `predicted_npd` carries one row per (name,
   model, metric, op_mode, power_setting) with the ten level columns, ten
   `std_*` uncertainty columns, `qa_status`, `qa_notes` and a UTC timestamp.
   `PredictionStore.add(..., replace=True)` (the default) first deletes all
   rows for that (name, model) pair in both tables, then appends — i.e.
   re-predicting an aircraft with the same model replaces its record rather
   than accumulating duplicates. The aircraft row records the worst QA status
   of its stored tables and the physics cross-check as JSON.
3. **`model_trials` / `model_screen` are written only by `pnmf/evolve.py`**
   (the self-improvement registry, §5).

Why the invariant exists: a framework that generates data must never train
on its own output. Fitness in `evolve.py` and all fits in `models.py` read
exclusively from the ANP truth tables; stored predictions are read-only
downstream products. This is the "no false data" rule stated in the module
docstrings.

---

## 4. Core objects (`pnmf/core.py`)

### 4.1 `ParametricAircraft` — the input

Dataclass fields (defaults in parentheses):

| group | fields |
|---|---|
| identity | `name` ("GENERIC") |
| propulsion | `engine_type` ("Jet" / "Turboprop" / "Piston"), `n_engines` (2), `max_static_thrust_lb` (30,000; per engine, sea-level static) |
| optional propulsion | `bypass_ratio`, `fan_diameter_m`, `fan_tip_mach` (all `None`) |
| weights | `mtow_lb` (155,000), `mlw_lb` (137,000) |
| optional geometry | `wing_area_m2`, `wing_span_m`, `n_main_gear_wheels` (all `None`; the future-concept extension a synthesis tool would populate) |
| certification | `noise_chapter` (4) |

`feature_vector()` returns the 10 numeric features consumed by the
data-driven models — deliberately limited to quantities every ANP aircraft
has, so LOO validation on the real fleet is possible:

`is_jet`, `is_turboprop`, `is_piston` (one-hot), `n_engines`,
`log_mtow`, `log_mlw`, `mlw_mtow` (ratio),
`log_thrust_per_eng`, `log_total_thrust` (log10, floored at 1 lbf),
`noise_chapter`.

`from_anp_row(npd_id, row)` builds the object from a `param_table()` row
(missing noise chapter defaults to 4). The optional propulsion/geometry
fields feed the physics route and the semi-empirical layer when supplied;
the surrogate's feature vector does not use them (a documented limitation).

### 4.2 `NPDTable` — the output

Stores a `(P,)` power grid and `(P, 10)` level matrix at
`STANDARD_DISTANCES_FT = [200, 400, 630, 1000, 2000, 4000, 6300, 10000,
16000, 25000]`, plus metric, op mode, `npd_id` and `power_param`
(default `"CNT (lb)"`). Rows are sorted by power on construction.

`level(power, distance_ft)` implements the Doc-29 lookup rule:

- **distance axis:** interpolation is linear in **log10(distance)** within
  each power row; outside 200–25,000 ft the end slope in log-distance is
  extended linearly (explicit `_extrap_low`/`_extrap_high`);
- **power axis:** linear interpolation between the row results, with linear
  extrapolation beyond the tabulated power range (`_interp_extrap`); a
  single-row table returns its one row directly.

---

## 5. Surrogate route (`pnmf/models.py`)

### 5.1 Design matrix and unit handling

One multi-output regressor is trained per (metric, op_mode). Each training
row is `[10 aircraft features, log_power_lb, throttle_frac] → 10 levels`,
with one row per tabulated NPD power setting, grouped by `NPD_ID`
(`_design_matrix`).

**`power_features(P, power_parameter, static_thrust_lb)`** resolves fault F1
(the ANP `Power Setting` column mixes units across aircraft: corrected net
thrust in lb ×134 aircraft, % of max static thrust ×17, RPM ×4). It returns
two unit-consistent features:

- `'CNT (lb)'` (and anything unrecognised, the documented default):
  `P_lb = P`, `throttle = P / static_thrust`;
- `'% of Max Static Thrust'`: `P_lb = P/100 · static_thrust`,
  `throttle = P/100`;
- `'RPM'`: no exact conversion exists; `throttle = P / max(P)` within the
  set and `P_lb = throttle · static_thrust` (crude but consistent).

Output is `(log10(max(P_lb, 1)), clip(throttle, 0, 2))`. Confirmed LOO
improvement from this fix: SEL/A RMSE 4.82 → 4.23 dB.

### 5.2 Physicality and uncertainty

- **Monotonicity (fault F2):** all 2,776 truth rows decrease with distance;
  `enforce_distance_monotone` projects every predicted row onto
  "non-increasing in log-distance" via isotonic regression
  (`IsotonicRegression(increasing=False)` on log10 distance). Rows already
  monotone are unchanged. On by default in every model.
- **Uncertainty:** `predict_table(..., return_std=True)` returns a `(P, 10)`
  array of **cross-tree standard deviations** over the selected ET or RF
  ensemble. It is an uncalibrated disagreement heuristic, not a prediction
  interval. Queries
  far from the training population show systematically wider spread, which
  is how extrapolation can be flagged to the QA gate (§8).

### 5.3 The model family

The two supported models share the interface
`.fit(db, metric, op_mode, exclude_ids=())`,
`.fit_all(db, metrics, op_modes)`, `.predict_table(aircraft, metric,
op_mode, power_settings, power_parameter=...)`:

- **`SurrogateNPDModel(learner="et")`** — Extra Trees with 500 trees,
  `min_samples_leaf=1`, `max_depth=24`, and `max_features=0.5`. This is the
  production default.
- **`SurrogateNPDModel(learner="rf")`** — Random Forest with 200 trees and
  `min_samples_leaf=2`. This is the supported comparison model.

Historical semi-empirical, anchor, blend, ARIMA, gradient-boosting and
evolution experiments remain in source history or internal modules for
reproducibility. They are not accepted by the public API, CLI, or UI and must
not be described as current model choices.

### 5.4 LOO harness

`loo_validate(db, model_factory, metric, op_mode)` retrains a fresh model
excluding each `NPD_ID` in turn, predicts the held-out aircraft's curve at
its true tabulated power settings (passing the aircraft's *actual* power
parameter unit through), and compares cell-by-cell. Returns a pooled summary
(RMSE, MAE, bias, p90 |err|) and a per-aircraft DataFrame.

---

## 6. Physics route (`pnmf/physics.py`)

A from-scratch pyNA/ANOPP-family model: literature scaling laws with free
additive anchor constants. Works in SI units (m, N, m/s) internally and
converts at the model-layer boundary (`FT2M = 0.3048`, `LBF2N = 4.44822`);
the ANP reference airspeed is 160 kt.

### 6.1 Acoustics foundation

- **Bands:** the 24 standard 1/3-octave centre frequencies, 50 Hz–10 kHz
  (identical to the ANP spectral-class bands).
- **A-weighting** per IEC 61672, exact analytic form (0 dB at 1 kHz).
- **Atmospheric absorption** α(f) [dB/m] per ISO 9613-1 (the physics behind
  SAE ARP 866A), including the O₂/N₂ relaxation frequencies, evaluated at
  the ANP/Doc-29 reference atmosphere 15 °C / 70 % RH / 101.325 kPa.
- **Propagation:** free-field spherical spreading + absorption,
  `L(r) = L(1 m) − 20·log10(r) − α(f)·r`. Ground effects, lateral
  attenuation and installation are deliberately excluded — NPD tables are
  defined for this idealised geometry; the consumer tool applies the rest.

### 6.2 Physical-input and flight-state contracts

The component route exposes typed SI contracts before source evaluation:

- `PhysicalInput[T]` carries the value and the literal evidence state
  `supplied`, `estimated`, or `unavailable`. `EnginePhysicalInputs` covers
  thrust, BPR, flow, nozzle exit area/velocity/temperature/pressure, fan
  diameter, RPM/N1, blade/stator counts, rotor-stator spacing, fan temperature
  rise, and core/combustor state. `AirframePhysicalInputs` covers wing,
  flap/slat, wheel, and strut geometry/configuration.
  `AtmosphericPhysicalInputs` and `FlightTrajectoryInputs` cover temperature,
  humidity, pressure, position, TAS/Mach, altitude, attitude, thrust, and
  configuration.
- The legacy `PhysicsDesign` constructor remains valid. Its
  `input_status` diagnostics mark direct constructor quantities as supplied,
  weight-derived wing geometry as estimated, and absent engine-deck/core data
  as unavailable. Typed nozzle quantities override the low-fidelity
  mixed-nozzle state; a complete typed fan set creates the Heidmann input
  deck; typed airframe geometry drives the six airframe components; and typed
  atmosphere values are used for that event's absorption. Estimates are never
  promoted silently to supplied data.
- `FlightStateSource` is the instantaneous source-evaluation boundary.
  `Reference160KtFlightPath` adapts the existing Doc-29 NPD event to that
  interface. `FlightTrajectoryInputs.to_flight_state()` validates a complete
  trajectory sample before converting it to this boundary. The reference
  adapter is a steady, level 160 kt flyover; it is not an airport trajectory
  or contour model.

### 6.3 Legacy low-fidelity engine state (`EngineState.from_design`)

A deliberately simple, documented mapping from (thrust setting, design) to
gas-path quantities:

- `v_jet_max = 700 / (1+BPR)^0.44` m/s (anchored on JT8D and CFM56;
  reproduces GE90 ≈ 260 m/s); fixed nozzle ⇒ `v_j = v_max·sqrt(F/Fmax)`;
- `mdot = F / v_j`; `A_jet = mdot / (ρ_j v_j)` with ρ_j ≈ 0.64·ρ₀;
- `M_tip_max = 1.6 / (1+BPR)^0.15`; `M_tip = M_tip_max · (F/Fmax)^0.45`
  (N1-thrust lapse);
- blade-passing frequency `BPF = M_tip·c₀/(π·D_fan)·n_blades` (24 blades
  default); `D_fan` from max mass flow at a Mach-0.45 fan face unless given.

These quantities are an **estimated low-fidelity fallback**, not an engine
deck. The event diagnostics report that fallback whenever the detailed Stone
or Heidmann gates are not satisfied.

### 6.4 Component sources (exponents as implemented)

Each source returns 1/3-octave SPL at a 1 m reference radius for one engine
(or the whole airframe). Spectra are smooth "haystack" humps, parabolic in
log2(f/f_peak); directivities are tabulated lobes interpolated over emission
angle θ.

| source | level law (dB) | spectrum peak |
|---|---|---|
| simplified mixed jet fallback | `C_jet + 80·log10(v_jet/c₀) + 10·log10(A_jet)` + aft-dominant directivity — intensity ∝ `V_j⁸·A_j` | Strouhal ≈ 0.25: `f_peak = f_scale·0.25·v_jet/d_jet` |
| Stone-style multi-stream jet | the same density-corrected `V⁸A` scaling is evaluated separately for outer, optional inner/intermediate, and merged virtual sources, each with its own peak and directivity offset; the spectra are summed energetically | enabled only with supplied outer **and** merged velocity, flow, diameter, temperature, and pressure; otherwise the simplified fallback is named in diagnostics |
| simplified fan fallback | `C_fan + 10·log10(mdot) + 40·log10(M_tip)` + legacy two-lobe directivity | estimated haystack around BPF plus one BPF-band tone |
| Heidmann-style engine-deck fan | `C_fan + 10·log10(mdot) + 20·log10(ΔTt)` with separate inlet/discharge lobes and a rotor-stator-spacing adjustment | requires mass flow, temperature rise, tip speed plus RPM or N1, diameter, blade/stator counts, and rotor-stator spacing; supplies BPF harmonics 1–3 and buzz-saw eligibility only for tip Mach ≥ 1 |
| Fink-style wing trailing edge | `C_wingflap + 50·log10(V/c₀) + 10·log10(δ*·b)`, `δ* = 0.37·c̄·Re^−0.2`; dipole directivity `10·log10(sin²θ + 0.05)` | `f ≈ 0.1·V/δ*` |
| Fink-style slat | deployed slat uses an independently inspectable spectrum based on slat chord | `f ≈ 0.2·V/c_slat` |
| Fink-style flap main/side edges | `C_wingflap + 3 + 50·log10(V/c₀) + 10·log10(S_f·sin²δ_f)`; the legacy flap energy is split 75/25 between main and side virtual sources | main `f ≈ 0.6·V/(0.3c̄)`; side peak is 1.8 times higher |
| Fink-style nose/main landing gear | `C_gear + 60·log10(V/c₀) + 10·log10(n·d²)` with explicit nose/main wheel counts and a visible strut-geometry factor | `f ≈ 0.8·V/d`; nose peak is 1.25 times higher |

`PhysicsDesign` holds the configuration; when a synthesis tool has not
supplied geometry, defaults are derived from weight (wing loading
≈ 600 kg/m², aspect ratio 9, gear wheel count by weight class). The ANP
configuration convention is built in: departure = gear up, 10° flap, slats
out; approach = gear down, 30° flap, slats out.

The optional `core_combustor` component stays absent unless core flow,
temperature, pressure, combustor-exit temperature, and turbine attenuation are
all supplied. It is never synthesized from thrust/BPR alone.

### 6.5 NPD point simulation and diagnostics

An NPD point is *defined* (Doc 29/ANP) as a steady level flyover at 160 kt
at fixed power, observed at closest slant distance d. The model simulates
exactly that: for 69 emission angles θ = 5°…175° along the straight path
(`r = d/sinθ`, along-track position `x = −d/tanθ`, time `t = x/v`), each
component's 1 m band spectrum is propagated (spherical spreading + ISO
9613-1 absorption), A-weighted and energy-summed into L_A(t); engine sources
get +10·log10(N_engines). Then `LAmax = max_t L_A(t)` and
`SEL = 10·log10(∫ 10^(L_A/10) dt / 1 s)` (trapezoidal integration) — the SEL
duration effect (slower decay with distance than LAmax) emerges from the
integration, nothing is bolted on. `predict_table` repeats this over the
requested thrust settings and the 10 standard distances, yielding an
`NPDTable` identical in format to the surrogate's output.

`evaluate_sources()` accepts an instantaneous `FlightState`.
`single_event_diagnostics()` retains every component time history, its LAmax
and SEL, the energetic total, source enablement/fallback status, and input
status. Validation should proceed in this order: component spectra and
directivity; receiver time histories and energetic sums; then LAmax/SEL and
NPD tables. The legacy `single_event(..., return_components=True)` still
returns the `jet`, `fan`, and `airframe` LAmax roll-ups required by the CLI,
and additionally exposes the resolved component names.

### 6.6 Calibration freeze policy

The four additive level constants (`C_jet`, `C_fan`, `C_wingflap`, `C_gear`)
plus one spectral-placement factor (`f_scale = 2^x`, shared by all sources)
are fitted by bounded least squares to **one** reference aircraft's ANP
SEL + LAmax curves, both op modes — the **A320-211** at BPR 6.0
(`calibrate()`: a coarse grid over the strongly non-convex spectral
parameter, refitting the four level constants at each node, then a joint
bounded refinement; in-sample 1.57 dB). Departure separates jet from fan via
their different throttle scalings (V_j⁸ vs M_tip⁴); approach is
airframe-dominated. The constants are then **frozen** for every other
aircraft and every future design. Recalibrating on any other aircraft would
invalidate all out-of-sample claims (§11) — the 12-aircraft fleet check,
the BPR sweep and the 737-800 case study are only evidence because the model
never saw those aircraft. This is the only place the physics route touches
ANP data.

**Scope limit (by design, not a bug):** EPNL/PNLT tone-correction machinery
is not implemented; the physics route covers SEL + LAmax only, and the API
cross-check is restricted accordingly.

### 6.6 Streamlit physics workspace

The **Aircraft Designer** owns one shared aircraft definition and offers
learned-only, physics-only and comparison modes. After the learned prediction
establishes the frozen calibration context, its embedded physics section
constructs a typed `PhysicsDesign` from exact UI inputs and calls
`NoisePrediction.physics_diagnostics(...)` plus `physics_table(...)`. The
learned table is never passed into either method. In comparison mode it is
evaluated afterward at matching thrust/distance coordinates solely for an
output overlay and reported differences.

The page exposes event thrust, closest distance, BPR, airframe configuration,
atmosphere, and an optional detailed engine-deck form. Results include SEL and
LAmax, ten-distance physics NPD curves, component metrics, receiver time
histories, supplied/estimated/unavailable status, uncertainty wording, and the
explicit excluded-effects list. This makes fallback logic visible instead of
silently treating synthesized concept inputs as measured engine data.

Three v6.3 physical presets (`A320-270N`, `A350-1041`, and `7773ER`) provide
source-labelled starting points. A selected preset creates its own
`ParametricAircraft`; the learned overlay is recalculated for that aircraft,
while the component-physics call remains independent. `input_status` overrides
mark each manufacturer-backed field as supplied and derived or representative
geometry as estimated. The maintained source register and assumptions are in
[`PHYSICS_PRESETS.md`](PHYSICS_PRESETS.md).

Free-field spreading and frequency-dependent atmospheric absorption remain
the only propagation effects. Event diagnostics explicitly list unmodelled
installation/shielding, nacelle treatment or suppression, ground reflection,
lateral attenuation, terrain, and non-uniform atmosphere as future extension
points. None is hidden inside the four frozen source anchors. Component
anchors and model form remain uncertain and are not calibrated uncertainty
intervals; learned-tree dispersion is unrelated and must not be reported as
physics uncertainty. The route is conceptual screening research, not
certification.

---

## 7. API facade (`pnmf/api.py`)

`NoisePredictor(root=".", model=DEFAULT_MODEL, metrics=("SEL", "LAmax",
"EPNL", "PNLTM"), op_modes=("A", "D"), random_state=0)` loads the
`ANPDatabase` and fits the chosen model for every metric/op-mode combination
up front.

**`DEFAULT_MODEL = "et"`.** The only accepted learned-model strings are
`"et"` and `"rf"`. `PhysicsNPDModel` is not a third learner; it is invoked as
an independent output cross-check.

**Default power grid** (per engine, lb, from the aircraft's static thrust T):
departure `linspace(0.45·T, 0.95·T, 4)`, approach
`linspace(0.07·T, 0.35·T, 3)`, both rounded — high thrust for departure,
low for approach. An explicit sequence preserves the legacy shared-grid
behavior. A mapping such as `{"D": [...], "A": [...]}` supplies separate
mode grids; a missing mapping entry uses that mode's default. All selected
grids are validated as finite, positive, unique and ascending.

`predict(aircraft | **kwargs)` returns a **`NoisePrediction`** with:

- `.tables` — `{(metric, op_mode): NPDTable}` for every fitted combination;
- `.uncertainty` — `{(metric, op_mode): (P,10) cross-tree std or None}`;
- `.to_anp_csv(path)` — strict ANP layout (`NPD_ID`, `Noise Metric`,
  `Op Mode`, `Power Setting`, the ten distance columns, rounded 0.1 dB);
  uncertainty is deliberately *not* mixed in (fault F8);
- `.crosscheck_physics(bpr=None)` — runs the frozen physics route
  (calibrated lazily, once, on the A320-211; bpr defaults to the aircraft's
  `bypass_ratio`, else 6.0) and returns `{metric: mean |Δ| dB}` over the
  shared cells for SEL and LAmax only. The two routes share no fitting —
  outputs are compared, never coupled.

**`real_vs_future_table(db, prediction, crosscheck=None, n_neighbors=3,
ref_distance_ft=1000.0)`** — pure function (no I/O, no database writes)
backing the real-vs-future comparison report (§10): given a
`NoisePrediction` and the database, it finds the nearest real aircraft via
`ANPDatabase.nearest_npd_ids` and builds the summary comparison table of
predicted-vs-neighbor levels at the reference distance, using the
representative-power convention of §10.

---

## 8. QA gate (`pnmf/anp.py::qa_check`)

Every predicted table is validated before it may enter the database.
`qa_check(P, L, std=None, *, bounds=(20.0, 160.0), std_caution_db=3.0,
crosscheck_db=None, crosscheck_caution_db=5.0)` returns
`(status, reasons)` with status `ok` / `caution` / `rejected`:

| check | threshold | consequence |
|---|---|---|
| non-finite levels | any NaN/inf | **rejected** |
| plausibility bounds | any level < 20 dB or > 160 dB | **rejected** |
| distance monotonicity | any increase along the distance axis > 1e-6 dB | **rejected** ("unphysical") |
| power grid validity | non-finite or duplicate power settings | **rejected** |
| model uncertainty | mean cross-tree std > 3.0 dB | `caution` ("likely extrapolation") |
| physics disagreement | mean \|Δ\| vs physics route > 5.0 dB | `caution` |

Rejected tables are **never written**; `PredictionStore.add` skips them and
the aircraft row records the worst status of what was stored (an aircraft
whose tables were all rejected is not written at all). `caution` tables are
stored but flagged in `qa_status` so downstream consumers can filter.
Reference behaviour: the FUTURE-UHBR-TWIN dry run yields 4 ok (approach) /
4 caution (departure, σ above threshold — the model flagging extrapolation
for a BPR-15 twin with no close fleet neighbour) / 0 rejected.

---

## 9. Operations layer (`pnmf/operations.py`)

Links flight trajectories to noise: the operational half of the Doc-29
chain. Full ground-contour segmentation (energy fraction, lateral
attenuation) is the consumer tool's job.

**`OperationalProfile(op_type, points, ...)`** holds a trajectory as points
(`distance_ft`, `altitude_ft`, `speed_kt`, `thrust` per engine).
Constructors: `from_fixed_point(db, acft_id, op_type, ...)` from the ANP
fixed-point-profile table (~20 legacy aircraft), or the synthesizer below.
`segments()` returns per-segment midpoint state (x, altitude, speed, thrust,
length). `flyover_level(npd_table, observer_x_ft, lateral_offset_ft=0)`
computes a single-point LAmax-style check: the max over segments of the NPD
level at the observer's **closest slant distance to each segment** — an
analytic point-to-segment minimum in the (along-track, height) plane with
the lateral offset added in quadrature, thrust linearly interpolated at the
closest point (fault F3 fix: segment midpoints underestimate the close
approach on long segments).

**`DepartureSynthesizer(db)`** builds departure profiles SAE-AIR-1845-style
from the ANP procedural-steps table, which covers 142 aircraft (vs ~20 with
fixed-point profiles — fault F4). Per step type:

- **Thrust.** Jets: `Fn/δ = E + F·Vc + Ga·h + Gb·h² + H·Tc` with
  `δ(h) = (1 − 6.87535·10⁻⁶·h)^5.2559` and ISA temperature lapse.
  Propellers: `Fn = 325.87·η·hp / V`, V floored at 40 kt (the 1845
  ground-roll convention). A `thrust_scale` factor supports borrowing a
  neighbour's engine deck for a future aircraft.
- **Takeoff:** liftoff CAS `v_lof = C·√W`; ground roll
  `Sg = B·W² / (N·Fn)` with Fn evaluated at `v_lof/√2`.
- **Climb:** `sinγ = clip(K·(N·Fn/W − R), 10⁻³, 0.7)` with the Doc-29
  climb-angle factor K = 1.01 below 200 kt, 0.95 above; segment-mean thrust.
- **Accelerate:** energy-share with segment-mean thrust,
  `a_total = g·(N·Fn/W − R)`; the tabulated rate of climb is capped at 80 %
  of the excess-thrust budget (this guard is what fixed the diverging
  1900D/PA30 turboprop segments), and the horizontal share is floored at
  20 % of `a_total`.

Documented simplifications: ISA sea level, no wind, no runway gradient,
CAS ≈ TAS below 10,000 ft. All 142 procedural-step aircraft (jets and
propellers) produce physical profiles under test assertions.

---

## 10. Real-vs-future comparison report (`pnmf_cli.py report`)

Purpose: put a predicted future-aircraft NPD set next to the measured curves
of its nearest real neighbours, in one glance. The command:

1. predicts the future aircraft **live** via `NoisePredictor` (default
   concept: FUTURE-UHBR-TWIN, defined as the constant `FUTURE_UHBR_TWIN` in
   `pnmf/core.py`);
2. finds the n = 3 nearest real aircraft via
   `ANPDatabase.nearest_npd_ids(mtow_lb, engine_type=None, n_engines=None,
   n=3)` (§2) — nearest by the EASA-substitution-style criteria, mapped to
   de-duplicated `NPD_ID`s;
3. emits, all under `outputs/`:
   - **4 overlay figures** `real_vs_future_{SEL,LAmax}_{D,A}.png` — the
     future aircraft's predicted curve with a ±1σ cross-tree uncertainty
     band vs the neighbours' truth curves;
   - **1 fleet-envelope figure** `fleet_envelope_SEL_D.png` — every fleet
     SEL:D curve in gray, the neighbours highlighted blue, the future
     aircraft red: where the concept sits in the population;
   - **summary table** `real_vs_future_summary.csv` and `.md`, built by the
     pure function `pnmf.api.real_vs_future_table(db, prediction,
     crosscheck=None, n_neighbors=3, ref_distance_ft=1000.0)` (§7).

**Representative-power convention** (unit-safe across the mixed lbf / %RPM
power parameters of §5.1, which make absolute power values incomparable
across aircraft): for **departure**, each real aircraft is represented by
its HIGHEST tabulated power row and the future aircraft by the top point of
its power grid; for **approach**, the LOWEST vs lowest. Comparisons are made
at the reference distance (default 1000 ft, the ANP anchor column).

**No-write guarantee:** the report performs **no database writes** — it
reads the truth tables and renders artifacts only; `anp_data.sqlite` is
untouched (same discipline as `predict --dry-run`).

---

## 11. Validation architecture

Four complementary layers are maintained; the learned and physics routes are
never coupled.

1. **Aircraft-grouped learned validation.** `validate-model` evaluates ET and
   RF across all eight metric/mode tasks while grouping by aircraft. Current
   counts, fold results and limitations are in
   `docs/MODEL_TRAINING_REPORT.md`.
2. **Release-ordered validation.** The same report trains on the legacy corpus
   and evaluates the v6.3 supplement, with a purged variant that removes the
   shared `7773ER` identity. The resulting sample is small and does not prove
   unseen-family generalisation.
3. **Frozen Jet reference holdout.** `validate-jet-reference` provides the
   predeclared Jet-only protocol, purge set and source provenance documented
   in `docs/JET_REFERENCE_VALIDATION_REPORT.md`.
4. **Independent component physics.** The physics route touches ANP truth
   during the frozen A320-211 calibration only. Source spectra, receiver time
   histories, component energy sums and SEL/LAmax tables have focused software
   tests. Historical aggregate-physics figures do not validate the newly
   detailed Stone/Heidmann/core branches; those require engine-deck and
   measurement evidence.

The current physics equations, output logic, validation ladder and research
gaps are documented in
`docs/PNMF_COMPONENT_PHYSICS_TECHNICAL_PAPER.pdf`.
