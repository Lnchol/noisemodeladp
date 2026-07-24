# PNMF — Parametric Noise Modeling Framework

PNMF turns a parametric aircraft definition into ANP/Doc-29-compatible
Noise-Power-Distance tables for conceptual screening.

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
and the [migration progress report](docs/MIGRATION_PROGRESS_REPORT.md).
