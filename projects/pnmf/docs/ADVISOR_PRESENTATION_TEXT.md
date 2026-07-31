# PNMF advisor presentation text

## 1. Opening: problem, purpose, and boundary

Aircraft-noise assessment is needed early, when an aircraft exists as a small set of design variables rather than as a certified, measured product. The problem is to turn that incomplete description into Noise-Power-Distance (NPD) tables that can be consumed by ANP/ECAC Doc 29-style noise workflows.

PNMF, the Parametric Noise Modeling Framework, does this for **conceptual screening**. It is useful for comparing configurations, identifying implausible inputs, and exploring how mass, thrust, engine count, engine type, and power setting may affect single-event noise. It is **not a certification tool**: it neither replaces measured/certified data nor establishes regulatory compliance.

The framework deliberately maintains two separate routes. A learned route uses the ANP population to make an NPD-equivalent prediction. A component-physics route is a mechanistic SEL/LAmax cross-check. Agreement is informative; disagreement is a caution signal, not proof that either route is correct.

## 2. What a user provides, and what PNMF returns

The basic aircraft input is engine type (jet, turboprop, or piston), number of engines, maximum take-off weight (MTOW), maximum landing weight (MLW), maximum sea-level static thrust per engine, noise chapter, and an optional name. For a chosen operating condition, the user also supplies or accepts a grid of per-engine power settings.

The learned sample vector has twelve values:

`x = [is_jet, is_turboprop, is_piston, n_engines, log10(MTOW_lb), log10(MLW_lb), MLW/MTOW, log10(static_thrust_lb_per_engine), log10(total_static_thrust_lb), noise_chapter, log10(power_lb), throttle]`.

PNMF returns tables at the ten standard ANP distances: 200, 400, 630, 1,000, 2,000, 4,000, 6,300, 10,000, 16,000, and 25,000 ft. The learned route covers SEL, LAmax, EPNL, and PNLTM for both approach and departure: eight prediction tasks in total. It can save accepted predictions separately from source truth and report QA findings and an ensemble-dispersion heuristic.

## 3. Data, provenance, and why this matters

The local datastore is built from the EASA ANP legacy v2.3 corpus plus the EASA ANP v6.3 CSV supplement. The current documented combined corpus contains 166 aircraft records (165 unique `ACFT_ID`s), 122 NPD sets, and 3,196 NPD rows. The v6.3 supplement is required by the current datastore workflow and is training data, not merely a later test set.

Each canonical truth row records `source_dataset` and `source_file`. Source collisions use declared table-specific business keys, with v6.3 winning where a collision is defined; records that share an aircraft ID but reference different NPD sets are retained. The datastore build validates source presence and truth-table integrity, and embeds a dataset manifest. This provenance is essential because a noise prediction can only be interpreted in light of the source curves that trained it.

Truth (`anp_*`), predictions (`predicted_*`), and older trial tables remain separate. That prevents a predicted result from silently becoming training or validation truth.

## 4. Learned ET/RF method

For each metric and operating mode, PNMF trains one multi-output ensemble on one sample per ANP power row. The target is the complete ten-distance NPD level vector, so the model predicts a row of an NPD table rather than ten unrelated scalar models.

For Extra Trees or Random Forest, the prediction can be written as:

`L_hat(x) = (1 / T) * sum_i t_i(x)`,

where `t_i` is tree `i` and `L_hat` contains ten sound levels. Extra Trees is the production default: 500 trees, `max_depth=24`, `max_features=0.5`, and `min_samples_leaf=1`. Random Forest provides the supported alternative: 200 trees and `min_samples_leaf=2`. These are frozen production settings in the current report, not parameters selected in that validation run.

After prediction, every row is projected with isotonic regression to be non-increasing in `log10(distance)`. This enforces the basic physical expectation that level does not rise as the observer becomes farther away. Tree-to-tree standard deviation may be displayed as a dispersion/extrapolation heuristic; it is explicitly not a calibrated confidence interval.

## 5. Power normalization and design adjustability

ANP power rows do not all use the same unit: corrected net thrust in lb, percent of maximum static thrust, or RPM occur in the corpus. Using the raw number would incorrectly treat, for example, an RPM value and a thrust value as comparable. PNMF therefore derives two unit-consistent features: corrected absolute power and throttle fraction.

For corrected net thrust, `power_lb=P` and `throttle=P/T_static`. For percent CNT, `power_lb=(P/100)*T_static` and `throttle=P/100`. For RPM, where an exact thrust conversion is unavailable, `throttle=P/max(P_grid)` and `power_lb=throttle*T_static`. The model uses `log10(max(power_lb,1))`; throttle is clipped to `[0,2]`.

This is the key adjustability concept: a future design can be evaluated at its own thrust and chosen operating-power grid while the model retains a comparable normalized power coordinate. It does not make unobserved engine architectures validated. In particular, RPM conversion is a documented approximation, and a query outside observed aircraft or engine-type/count support remains extrapolation.

## 6. NPD table use and Doc 29 interpolation

An NPD table is a set of single-event levels indexed by power and slant distance. When a downstream calculation asks for a level at a non-tabulated point, PNMF first interpolates each power row linearly in `log10(distance)`, then interpolates linearly in power:

`L(P,d) = interp_P(P, interp_log10(d)(L_table))`.

The implementation also linearly extrapolates at either end of the power and distance grids. That is compatible with the stated table lookup rule but is a reason for caution beyond the tabulated range. NPD tables themselves are not a full airport-noise model: route geometry, operations, ground/lateral effects, and other consumer-side corrections remain the responsibility of the downstream assessment workflow.

## 7. Independent component-physics cross-check

The physics route is intentionally not trained from the ET/RF residuals and
is not a third regression model. Its typed inputs cover engine stream/fan/core
state, airframe geometry/configuration, atmosphere and instantaneous flight
state; every field can be marked supplied, estimated or unavailable.
Legacy inputs remain supported through explicit low-fidelity fallbacks.
Internally it uses metres and newtons, converting only at the ANP boundary.

For each thrust setting, a simplified engine state includes, among other relations:

`V_jet,max = 700/(1+BPR)^0.44`, `V_jet = V_jet,max*sqrt(F/F_max)`, `mdot=F/V_jet`, and `M_tip = [1.6/(1+BPR)^0.15]*(F/F_max)^0.45`.

The component scaling laws are mechanistic sensitivities: jet-mixing
intensity is proportional to `rho_j^2*A_jet*V_jet^8`; fan level follows
mass-flow and temperature-rise/tip-speed scaling; wing/flap noise scales
approximately with `V^5`; and landing-gear noise approximately with
`V^6*n_wheels*d^2`. The detailed gates separate outer/inner/merged jet
virtual sources and fan inlet/discharge spectra. Airframe output separately
reports wing trailing edge, slat, flap main edge, flap side edge, nose gear
and main gear. An optional core source remains absent without complete core,
combustor and turbine-attenuation inputs. The sources are formed in 24
one-third-octave bands, energetically combined, A-weighted, propagated using
`-20 log10(r) - alpha(f)r`, and evaluated along a 160 kt straight flyover.

For each event, `LAmax = max_t L_A(t)` and
`SEL = 10 log10(integral 10^(L_A(t)/10) dt / 1 s)`. Diagnostics retain every
component time history and its energetic LAmax/SEL contribution. The four
source-level anchors (jet, fan, wing/flap, gear), plus spectral placement, are
fitted once by least squares to A320-211 SEL and LAmax curves, then frozen for
all other aircraft and future designs. The newly detailed jet/fan/core paths
share those anchors but still require engine-deck and measurement validation.
Physics produces **SEL and LAmax only**. It does not implement EPNL or PNLTM
tone-correction machinery, and it excludes ground effects, lateral
attenuation and engine-installation effects from the NPD source model. Full
equations and gaps are in `PNMF_COMPONENT_PHYSICS_TECHNICAL_PAPER.pdf`.

## 8. Outputs and QA interpretation

The primary output is an NPD table for each requested metric/mode, with an explicit power grid and the ten distance columns. The workflow checks input plausibility against the available fleet envelope, including engine type/count, thrust, weights, and thrust-to-weight relation. It checks NPD physicality and uses the post-prediction monotonic projection. Predictions can be stored only after acceptance in separate `predicted_*` tables.

Users should read the QA result together with the route comparison. A clean QA result means the requested input and resulting table passed implemented checks; it does not turn a conceptual estimate into certified evidence. Large learned-versus-physics deltas, sparse exact engine-type/count support, unusual power assumptions, or substantial cross-tree dispersion should trigger investigation or sensitivity analysis.

## 9. Current validation evidence and limitations

The current `MODEL_TRAINING_REPORT.md` is a reproducible retrospective validation dated 2026-07-24 and rates maturity **2/5: reproducible retrospective validation**. It assesses ET and RF on all eight tasks with 3 deterministic aircraft-grouped folds built from connected components of the `ACFT_ID`--`NPD_ID` graph. No NPD curve is split, aircraft sharing a curve stay together, and shared identities across releases are grouped together. This controls exact-identity leakage, but it is not a leave-family-out experiment.

Across internal grouped CV, ET cell-pooled RMSE ranges from 3.878 dB (SEL approach) to 5.045 dB (PNLTM departure); RF ranges from 3.955 to 5.257 dB. ET is the documented default. In a release-ordered test trained on legacy v2.3 and evaluated on supplement v6.3, the purged test removes the shared `7773ER` identity and has only ten curves. ET purged RMSE ranges from 2.217 dB (LAmax approach) to 5.290 dB (EPNL departure); RF ranges from 2.359 to 5.606 dB. These small temporal results are useful but do not establish performance for unseen aircraft families.

The evaluation labels exact engine-type/count cells as feasible, sparse, or impossible based on training-group support. A model may still emit a number in an impossible cell by borrowing information across types/counts; that is extrapolation, not demonstrated generalization. The current report also states that tree dispersion is uncalibrated, the physics route was not evaluated by that learned-model command, and the physics route cannot validate EPNL/PNLTM. There is no curated aircraft-family split, prospectively frozen external NPD dataset, or certification claim.

## 10. Concise overall status

PNMF is a runnable, provenance-aware conceptual NPD framework with reproducible ET/RF retrospective evidence, an independent frozen-calibration physics cross-check, caller-CWD-independent CLI/UI/test entry points, and explicit QA and data-separation safeguards. It is ready for disciplined screening studies and method development. It is not ready to be represented as certification-grade or as validated on novel aircraft families.

## 11. Five questions for future improvement

1. Can we curate and freeze manufacturer, platform, and engine-family labels so that true leave-family-out validation becomes possible?
2. What prospectively frozen external NPD dataset can be obtained without using it for training or model selection, and how will its provenance and licensing be documented?
3. Which additional turboprop, piston, and rare engine-count cases are needed to replace sparse or impossible support cells with meaningful evidence?
4. How should predictive intervals be calibrated on held-out aircraft groups while remaining clearly distinct from raw tree-to-tree dispersion?
5. Which measured or higher-fidelity component data can refine BPR, installation, geometry, operational configuration, and tone treatment without coupling the independent physics route to the learned model?
