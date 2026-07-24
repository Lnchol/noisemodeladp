# PNMF - Parametric Noise Modeling Framework

PNMF turns a parametric aircraft definition into ANP/Doc-29-compatible
Noise-Power-Distance tables for conceptual screening.

## INPUT -> FORMULAS -> OUTPUT

**INPUT.** Each learned sample is a 12-value vector:

`x = [engine-type one-hot (3), engine count, log10(MTOW), log10(MLW),
MLW/MTOW, log10(thrust/engine), log10(total thrust), noise chapter,
log10(unit-corrected power), throttle]`.

**FORMULAS.** For each metric/mode, an Extra Trees or Random Forest ensemble
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

1. **Data build:** merge the 155-record legacy v2.3 fleet with the 11-record
   v6.3 supplement. The combined corpus has 166 aircraft records (165 unique
   ACFT_IDs), 122 NPD sets, and 3,196 NPD rows.
2. **Learned prediction:** train Extra Trees (`et`, default) or Random Forest
   (`rf`) on the combined truth corpus.
3. **Physics cross-check:** run the independent component-source
   `PhysicsNPDModel` for SEL/LAmax using explicit bypass-ratio and geometry
   assumptions.
4. **Validation/storage:** compare routes, apply the physical QA gate, and
   store accepted predictions only in `predicted_*` tables.

The v6.3 CSVs are training data, not merely evaluation data. The embedded
manifest proves which source contributed each table and training row.

## Windows setup

From this directory:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe pnmf_cli.py datastore
.venv\Scripts\python.exe pnmf_cli.py manifest
.venv\Scripts\python.exe -m pytest tests -q
```

From the EFES root, use the same interpreter with `projects\pnmf\...` paths.
The CLI, UI, tests, and `pnmf.ps1` resolve data from this directory regardless
of caller CWD.

## Supported workflows

```powershell
.\pnmf.ps1 compare
.\pnmf.ps1 validate SEL:D SEL:A
.\pnmf.ps1 validate-model --folds 3 --seed 20260724
.\pnmf.ps1 predict --model et --dry-run
.\pnmf.ps1 predict --model rf --dry-run
.\pnmf.ps1 physics
.\pnmf.ps1 ui
```

Extra Trees and Random Forest are the only supported learned models.
`PhysicsNPDModel` is an independent scientific cross-check, not a third
regression model. Physics does not calculate EPNL/PNLTM tone corrections.

## CI and full-data validation

GitHub Actions runs only tracked-source compilation/import checks and
`tests/test_ci_smoke.py`, a synthetic test selection that needs no ANP data.
Raw ANP sources, `anp_data.sqlite`, and generated outputs remain ignored and
are intentionally unavailable in a clean hosted checkout.

The full local suite and `validate-model` require the provisioned v2.3/v6.3
corpus. Current full-data protocols, results, input hashes, and limitations are
recorded in [MODEL_TRAINING_REPORT](docs/MODEL_TRAINING_REPORT.md).

See [HOW_IT_WORKS](docs/HOW_IT_WORKS.md), [NPD design](docs/NPD_SYSTEM_DESIGN.md),
the [migration progress report](docs/MIGRATION_PROGRESS_REPORT.md), and the
[noiseframeworkv1 release notes](docs/releases/noiseframeworkv1.md).
