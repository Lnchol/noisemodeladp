# PNMF - Parametric Noise Modeling Framework

PNMF turns a parametric aircraft definition into ANP/Doc-29-compatible
Noise-Power-Distance tables for conceptual screening.

## INPUT -> FORMULAS -> OUTPUT

**INPUT.** Each Jet learned sample is a 9-value vector:

`x = [engine count, log10(MTOW), log10(MLW), MLW/MTOW,
log10(thrust/engine), log10(total thrust), noise chapter,
log10(unit-corrected power), throttle]`.

**FORMULAS.** For each metric/mode, the production Extra Trees ensemble
predicts all ten distances jointly:

`L_hat(x) = (1/T) sum(t_i(x))`.

Tree-to-tree standard deviation is reported as a dispersion heuristic, not a
calibrated confidence interval. Each predicted row is projected to the nearest
non-increasing sequence in `log10(distance)`. Doc-29 lookup then interpolates
the row linearly in `log10(distance)` and interpolates/extrapolates linearly in
power:

`L(P,d) = interp_P(P, interp_logd(log10(d), L_at_standard_distances))`.

The separate physics route energetically combines jet mixing
(`acoustic power proportional to V_jet^8`), fan, and airframe sources, then
applies spherical spreading, atmospheric absorption, A-weighting, and flyover
integration. It produces SEL and LAmax only; its component geometry and bypass
ratio (BPR) are physics-only assumptions because those inputs are unavailable
in the learned ANP feature set.

**OUTPUT.** Each power setting gets ten NPD levels at 200, 400, 630, 1,000,
2,000, 4,000, 6,300, 10,000, 16,000, and 25,000 ft. The learned route covers
all eight tasks: SEL, LAmax, EPNL, and PNLTM for approach and departure.

## Basic architecture

1. **Data build:** rebuild a Jet-only runtime from immutable EASA v2.3 and
   v6.3 sources: 136 aircraft rows, 135 unique ACFT_IDs, 94 complete curves,
   2,664 NPD rows, and 93 aircraft groups.
2. **Learned prediction:** train Extra Trees on the frozen nine-feature Jet
   schema and complete Jet population. Random Forest is validation-only.
3. **Physics cross-check:** run the independent component-source
   `PhysicsNPDModel` for SEL/LAmax using explicit bypass-ratio and geometry
   assumptions.
4. **Validation/storage:** compare routes, apply the physical QA gate, and
   store accepted predictions only in `predicted_*` tables.

The Streamlit **Aircraft Designer** now owns the complete workflow. Select one
shared Jet preset or custom aircraft, then choose **Learned ET only**,
**Component physics only**, or **Compare learned + physics**. Compare mode runs
ET for the shared aircraft and places exact event thrust, distance,
airframe/configuration, atmosphere and optional engine-deck physics inputs
directly below it. The resulting SEL/LAmax curves are overlaid at identical
thrust and distance coordinates. ET remains an output comparison and never
feeds the physics calculation.

Both run buttons expose a live calculation log. The learned log identifies
feature preparation and every metric/operation NPD table evaluation. The
physics log identifies the SI boundary conversion, frozen calibration,
component-source evaluation, propagation, energetic summation, SEL/LAmax
formulas, physics NPD tables and same-coordinate comparison. Completed logs
remain visible until the aircraft or calculation is replaced.

For a faster check, apply one of the source-labelled v6.3 presets to both
routes:
`A320-270N`, `A350-1041`, or `7773ER`. Each preset loads manufacturer-backed
BPR/fan/span/landing-gear values while keeping unsourced geometry visibly
estimated. See [`docs/PHYSICS_PRESETS.md`](docs/PHYSICS_PRESETS.md) for the
field-level assumptions and first-party references.

The v6.3 CSVs are training data, not merely evaluation data. The embedded
manifest proves which source contributed each table and training row.

## One-click Windows launch

Double-click `Launch_PNMF.cmd`. On the first run it creates the private
`.venv`, installs `requirements.txt`, starts Streamlit, and opens
`http://localhost:8501`. Later runs reuse the environment. Keep the launcher
window open while using PNMF; close it to stop the local server.

The PowerShell equivalent is:

```powershell
.\pnmf.ps1
```

`pnmf.ps1` automatically creates or updates `.venv` before every task and
resolves data from this directory regardless of caller CWD. Python 3 with the
standard Windows `py` launcher is the only prerequisite.

## Supported workflows

```powershell
.\pnmf.ps1 validate-jet-model
.\pnmf.ps1 validate-jet-reference
.\pnmf.ps1 verify-doc29-reference --workbook <official-workbook> --sha256 <sha256>
.\pnmf.ps1 predict --dry-run
.\pnmf.ps1 physics
.\pnmf.ps1 ui
```

Extra Trees is the sole production learner. Random Forest appears only in the
read-only validation evidence. `PhysicsNPDModel` is an independent scientific
cross-check, not a competing learner. Physics does not calculate EPNL/PNLTM
tone corrections.

## CI and full-data validation

GitHub Actions runs only tracked-source compilation/import checks and
`tests/test_ci_smoke.py`, a synthetic test selection that needs no ANP data.
Raw ANP sources, `anp_data.sqlite`, and generated outputs remain ignored and
are intentionally unavailable in a clean hosted checkout.

The full local suite and Jet validation require the provisioned v2.3/v6.3
corpus. Current full-data protocols, results, input hashes, and limitations are
recorded in [JET_MODEL_METHODOLOGY_AND_VALIDATION_REPORT](../../docs/JET_MODEL_METHODOLOGY_AND_VALIDATION_REPORT.md).

See [HOW_IT_WORKS](docs/HOW_IT_WORKS.md), [NPD design](docs/NPD_SYSTEM_DESIGN.md),
the [migration progress report](docs/MIGRATION_PROGRESS_REPORT.md), and the
[noiseframeworkv1 release notes](docs/releases/noiseframeworkv1.md).
