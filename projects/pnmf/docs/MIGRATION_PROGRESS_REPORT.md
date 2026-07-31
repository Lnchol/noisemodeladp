# EFES migration and ANP v6.3 integration progress

Date: 2026-07-24

## Completed

- Preserved the former workspace in the timestamped sibling backup
  `pnmf_project_backup_20260724_114903`.
- Made the original path the EFES git root and moved the cohesive PNMF
  application to `projects/pnmf`.
- Recreated the local environment instead of moving the old `.venv`.
- Made CLI, Streamlit, tests, and PowerShell tasks caller-CWD independent.
- Integrated raw EASA ANP v2.3 and v6.3 CSV data into the canonical datastore.
- Added per-row provenance and an inspectable merge manifest.
- Narrowed supported learned models to ET (default) and RF.
- Kept `PhysicsNPDModel` separate and clearly limited to SEL/LAmax.

## Data provenance and counts

| Source | Aircraft records | NPD sets | NPD rows |
|---|---:|---:|---:|
| Legacy v2.3 | 155 | 111 | 2,776 |
| v6.3 supplement | 11 | 11 | 420 |
| Combined | 166 (165 unique IDs) | 122 | 3,196 |

There are no NPD-ID or NPD-row-key collisions. The aircraft ID `7773ER`
exists in both releases with different NPD references, so both records are
kept. Other table collisions are resolved on documented business keys with
v6.3 winning.

## Model rationale

Extra Trees and Random Forest are robust multi-output ensembles for the mixed
aircraft/power features. ET remains the default based on the prior legacy-data
bake-off; the expanded-corpus validation numbers must be treated as new
evidence and are recorded only after the validation lane completes.

The physics route is valuable because it uses component specifications rather
than learned fleet regression. Its independence makes disagreement a caution
signal, not an optimization target.

## Baseline before integration

Legacy v2.3 RF pooled LOO RMSE was SEL/D 5.09, SEL/A 4.23, EPNL/D 5.26,
EPNL/A 5.05, LAmax/D 5.04, LAmax/A 4.57, PNLTM/D 5.36, and PNLTM/A 5.25 dB.
Physics fleet median RMSE was 2.82 dB. These are baselines, not claims for the
new 122-set corpus.

## Research gaps after migration

- The full eight-combination ET/RF validation on the expanded corpus is
  complete and recorded in `MODEL_TRAINING_REPORT.md`; the remaining evidence
  gap is a curated aircraft-family split and prospectively frozen external
  NPD set.
- Reassess the frozen physics constants only through a separately approved
  calibration study.
- Add physically justified EPNL/PNLTM tone/duration modeling if that route is
  expanded.
- Obtain richer geometry/BPR data to reduce imputation in conceptual inputs.

## Focused implementation verification

- Combined datastore/manifest build: passed.
- Migration and Streamlit tests: 8 passed.
- Core and physics tests: 21 passed.
- Learning/datastore tests: 14 passed, 1 expected loose-CSV skip.
- External-CWD ET dry-run: completed, 0 rejected; all 8 tables were cautioned
  for extrapolation uncertainty. Physics disagreement was 3.23 dB SEL and
  2.27 dB LAmax.

The migration acceptance work was subsequently completed. Use
`MODEL_TRAINING_REPORT.md` and `JET_REFERENCE_VALIDATION_REPORT.md` for current
learned-model evidence, and
`PNMF_COMPONENT_PHYSICS_TECHNICAL_PAPER.pdf` for the current physics
architecture and its separate validation gaps.
