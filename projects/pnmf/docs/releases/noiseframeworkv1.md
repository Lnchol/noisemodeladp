# noiseframeworkv1 release notes

## Purpose and boundary

PNMF turns a parametric aircraft definition into ANP/ECAC Doc-29-compatible
Noise-Power-Distance (NPD) tables for early conceptual screening. It is not a
certification method, and its validation does not establish accuracy for
unseen aircraft families or unconventional configurations.

## INPUT -> FORMULAS -> OUTPUT

- **Input:** 12 learned values: engine-type one-hot (3), engine count,
  `log10(MTOW)`, `log10(MLW)`, weight ratio, per-engine and total thrust logs,
  noise chapter, unit-corrected power log, and throttle.
- **Formulas:** ET/RF returns the mean of its tree predictions for ten distance
  targets; tree spread is an uncalibrated dispersion heuristic. Predicted rows
  are projected non-increasing with distance. NPD lookup is linear in power
  and linear in `log10(distance)`.
- **Output:** ten levels from 200 to 25,000 ft for all eight learned tasks:
  SEL, LAmax, EPNL, and PNLTM, each for approach and departure.

The independent physics route combines jet mixing (`V_jet^8`), fan, airframe,
and propagation models for SEL/LAmax. BPR and component geometry are explicit
physics-only assumptions; they are not available to the learned ANP model.

## Data and models

- Legacy ANP v2.3 remains the training base: 111 NPD sets and 2,776 NPD rows.
- The verified v6.3 supplement adds 11 NPD sets and 420 rows. The canonical
  datastore has 122 NPD sets and 3,196 truth rows with source provenance.
- Supported learned models are Extra Trees (`et`, default) and Random Forest
  (`rf`). The component physics route remains separate and its A320-211
  calibration is frozen.

## Commands

Run from the repository root:

```powershell
projects\pnmf\pnmf.ps1 datastore
projects\pnmf\pnmf.ps1 manifest
projects\pnmf\pnmf.ps1 test
projects\pnmf\pnmf.ps1 validate-model --folds 3 --seed 20260724
projects\pnmf\pnmf.ps1 compare
projects\pnmf\pnmf.ps1 physics
```

## Validation evidence

The full local suite recorded 52 passed and 1 expected skip. The v6.3 temporal
holdout was trained only on legacy v2.3. After removing the one exact aircraft
identity overlap (`7773ER`), cell-pooled RMSE in dB was:

| task | ET | RF |
| --- | ---: | ---: |
| EPNL approach | 2.761 | 2.917 |
| EPNL departure | 5.290 | 5.606 |
| LAmax approach | 2.217 | 2.359 |
| LAmax departure | 4.639 | 4.950 |
| PNLTM approach | 2.645 | 2.522 |
| PNLTM departure | 5.074 | 5.072 |
| SEL approach | 2.419 | 2.467 |
| SEL departure | 4.640 | 4.920 |

See the
[tag-pinned MODEL_TRAINING_REPORT](https://github.com/Lnchol/noisemodeladp/blob/noiseframeworkv1/projects/pnmf/docs/MODEL_TRAINING_REPORT.md)
for the complete protocol, raw holdout, grouped CV, support slices, hashes, and
limitations.

## Known limits

- The holdout has only ten purged v6.3 aircraft and is not unseen-family
  validation.
- Learned features omit BPR and component geometry; sparse classes and
  extrapolation remain risks.
- The physics route supports SEL/LAmax only and is not validated for
  unconventional aircraft.
- Lateral attenuation, ground effect, full operational assessment, and
  certification remain downstream or out of scope.

## Release assets

Attach only the current validation PDF listed in `SHA256SUMS.txt`.
`MODEL_ARCHITECTURE_REPORT.pdf` and `PNMF_ADP_Review.pptx` are deliberately
excluded because they are stale or historical.

Raw data, SQLite databases, generated output folders, model artifacts, virtual
environments, and temporary files are excluded. GitHub automatically supplies
source archives for tag `noiseframeworkv1`; this document does not hard-code a
release commit.
