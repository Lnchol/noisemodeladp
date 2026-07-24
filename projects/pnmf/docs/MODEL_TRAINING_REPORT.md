# PNMF Model Training and Validation Report

> Generated 2026-07-24T10:42:09.728690+00:00 by `pnmf_cli.py validate-model`. This is the current learned-model evidence report; `FINAL_REPORT.md` is historical.

## Scope and conclusion

This run evaluates exactly the production Extra Trees (`et`) and Random Forest (`rf`) regressors for all eight SEL/LAmax/EPNL/PNLTM times approach/departure tasks. It is evidence for interpolation within the available aircraft population and for a release-ordered legacy-to-supplement transfer. It is not certification evidence and does not establish performance on unseen aircraft families because the datastore has no curated family labels.

**Maturity: 2/5 - reproducible retrospective validation.** Split leakage by exact aircraft identity is controlled and release holdout is reported, but family-level, prospective and genuinely external confirmation remain missing.

## Exact prediction task

Each power row is one supervised sample with 12 inputs:

`[is_jet, is_turboprop, is_piston, n_engines, log10(MTOW_lb), log10(MLW_lb), MLW/MTOW, log10(static_thrust_lb_per_engine), log10(total_static_thrust_lb), noise_chapter, log10(power_lb), throttle]`.

Engine type is a three-column one-hot encoding and engine count is a separate numeric feature. The ten targets are the truth levels at 200, 400, 630, 1,000, 2,000, 4,000, 6,300, 10,000, 16,000 and 25,000 ft. For `CNT (lb)`, `power_lb=P` and `throttle=P/T_static`; for percent CNT, `power_lb=P/100*T_static` and `throttle=P/100`; for RPM, `throttle=P/max(P_grid)` and `power_lb=throttle*T_static`. MTOW and MLW are required positive and transformed directly with `log10(value)`. Static thrust per engine, total static thrust, and converted row power use `log10(max(value, 1))`; throttle is clipped to [0, 2].

The held-out aircraft descriptor and held-out power grid are inputs to the prediction task; held-out noise levels are used only after prediction for scoring. In particular, the temporal model is fit from legacy targets only. Conditioning on the requested power grid is part of producing an NPD table, not target leakage.

Production hyperparameters were not tuned in this run:

- ET: `{"class": "sklearn.ensemble.ExtraTreesRegressor", "max_depth": 24, "max_features": 0.5, "min_samples_leaf": 1, "n_estimators": 500, "n_jobs": -1, "random_state": "run_seed"}`
- RF: `{"class": "sklearn.ensemble.RandomForestRegressor", "max_depth": null, "max_features": 1.0, "min_samples_leaf": 2, "n_estimators": 200, "n_jobs": -1, "random_state": "run_seed"}`

Every effective scikit-learn constructor parameter, including defaults, is captured under `models` in `run_manifest.json`.

Both produce ten outputs jointly. The normal production monotonic projection is applied after prediction. Cross-tree dispersion is an ensemble disagreement heuristic; it is not calibrated uncertainty and this validation does not turn it into a confidence interval.

## Protocol 1 - internal aircraft-grouped CV

3 deterministic folds are built from connected components of the bipartite `ACFT_ID`--`NPD_ID` graph. Consequently no NPD curve is split, aircraft sharing a curve stay together, and identical IDs across releases (including `7773ER`) stay together. This is honestly labelled aircraft-grouped CV, not unseen-family CV.

| model | metric | op_mode | rmse_dB | mae_dB | bias_dB | p90_abs_error_dB | n_curves | n_aircraft_groups |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| et | EPNL | A | 4.550 | 3.086 | 0.174 | 7.019 | 122 | 121 |
| et | EPNL | D | 4.876 | 3.601 | 0.570 | 7.797 | 122 | 121 |
| et | LAmax | A | 4.228 | 2.811 | 0.274 | 6.338 | 122 | 121 |
| et | LAmax | D | 4.661 | 3.533 | 0.579 | 7.356 | 122 | 121 |
| et | PNLTM | A | 4.752 | 3.238 | 0.093 | 7.593 | 122 | 121 |
| et | PNLTM | D | 5.045 | 3.810 | 0.408 | 8.183 | 122 | 121 |
| et | SEL | A | 3.878 | 2.546 | 0.085 | 5.676 | 122 | 121 |
| et | SEL | D | 4.548 | 3.370 | 0.556 | 6.998 | 122 | 121 |
| rf | EPNL | A | 4.631 | 3.187 | 0.112 | 7.327 | 122 | 121 |
| rf | EPNL | D | 5.070 | 3.825 | 0.298 | 8.006 | 122 | 121 |
| rf | LAmax | A | 4.262 | 2.894 | 0.206 | 6.529 | 122 | 121 |
| rf | LAmax | D | 4.778 | 3.687 | 0.303 | 7.532 | 122 | 121 |
| rf | PNLTM | A | 4.896 | 3.372 | 0.139 | 7.730 | 122 | 121 |
| rf | PNLTM | D | 5.257 | 3.987 | 0.153 | 8.129 | 122 | 121 |
| rf | SEL | A | 3.955 | 2.640 | 0.097 | 5.517 | 122 | 121 |
| rf | SEL | D | 4.677 | 3.481 | 0.275 | 7.069 | 122 | 121 |

## Protocol 2 - temporal release holdout

The model is trained on `legacy_v2.3` and evaluated on `supplement_v6.3`. The raw result includes exact identity overlap. The purged result removes supplement test curves whose exact `ACFT_ID` occurs in legacy training; training itself is unchanged.

Purged exclusions:

- `7773ER` (exact_ACFT_ID_shared_with_legacy:7773ER).

### Temporal raw

| model | metric | op_mode | rmse_dB | mae_dB | bias_dB | p90_abs_error_dB | n_curves | n_aircraft_groups |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| et | EPNL | A | 2.675 | 1.661 | 0.850 | 5.844 | 11 | 11 |
| et | EPNL | D | 5.138 | 4.012 | 0.726 | 8.871 | 11 | 11 |
| et | LAmax | A | 2.131 | 1.358 | 0.890 | 2.520 | 11 | 11 |
| et | LAmax | D | 4.557 | 3.576 | 0.369 | 7.708 | 11 | 11 |
| et | PNLTM | A | 2.550 | 1.646 | 0.566 | 5.575 | 11 | 11 |
| et | PNLTM | D | 4.948 | 3.794 | -0.031 | 8.364 | 11 | 11 |
| et | SEL | A | 2.322 | 1.537 | 0.816 | 3.021 | 11 | 11 |
| et | SEL | D | 4.483 | 3.488 | 0.805 | 7.676 | 11 | 11 |
| rf | EPNL | A | 2.794 | 1.985 | 1.525 | 5.924 | 11 | 11 |
| rf | EPNL | D | 5.411 | 4.330 | 1.780 | 9.284 | 11 | 11 |
| rf | LAmax | A | 2.266 | 1.508 | 1.275 | 3.232 | 11 | 11 |
| rf | LAmax | D | 4.846 | 3.906 | 1.145 | 8.153 | 11 | 11 |
| rf | PNLTM | A | 2.421 | 1.612 | 0.950 | 5.426 | 11 | 11 |
| rf | PNLTM | D | 4.940 | 3.898 | 1.034 | 8.265 | 11 | 11 |
| rf | SEL | A | 2.364 | 1.727 | 1.178 | 3.456 | 11 | 11 |
| rf | SEL | D | 4.746 | 3.826 | 1.587 | 7.877 | 11 | 11 |

### Temporal purged

| model | metric | op_mode | rmse_dB | mae_dB | bias_dB | p90_abs_error_dB | n_curves | n_aircraft_groups |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| et | EPNL | A | 2.761 | 1.685 | 1.065 | 6.029 | 10 | 10 |
| et | EPNL | D | 5.290 | 4.084 | 1.190 | 8.969 | 10 | 10 |
| et | LAmax | A | 2.217 | 1.423 | 1.040 | 2.945 | 10 | 10 |
| et | LAmax | D | 4.639 | 3.567 | 0.824 | 7.960 | 10 | 10 |
| et | PNLTM | A | 2.645 | 1.708 | 0.714 | 5.921 | 10 | 10 |
| et | PNLTM | D | 5.074 | 3.824 | 0.365 | 8.636 | 10 | 10 |
| et | SEL | A | 2.419 | 1.620 | 0.957 | 4.060 | 10 | 10 |
| et | SEL | D | 4.640 | 3.583 | 1.195 | 7.769 | 10 | 10 |
| rf | EPNL | A | 2.917 | 2.120 | 1.720 | 6.037 | 10 | 10 |
| rf | EPNL | D | 5.606 | 4.474 | 2.327 | 9.488 | 10 | 10 |
| rf | LAmax | A | 2.359 | 1.586 | 1.461 | 4.681 | 10 | 10 |
| rf | LAmax | D | 4.950 | 3.925 | 1.698 | 8.329 | 10 | 10 |
| rf | PNLTM | A | 2.522 | 1.701 | 1.105 | 5.599 | 10 | 10 |
| rf | PNLTM | D | 5.072 | 3.949 | 1.542 | 8.476 | 10 | 10 |
| rf | SEL | A | 2.467 | 1.844 | 1.336 | 4.564 | 10 | 10 |
| rf | SEL | D | 4.920 | 3.963 | 2.063 | 8.083 | 10 | 10 |

## Metrics

All errors are `prediction - truth`. Cell-pooled metrics are `RMSE=sqrt(mean(e^2))`, `MAE=mean(|e|)`, `bias=mean(e)`, and `p90=percentile90(|e|)`. Curve-balanced and aircraft-group-balanced RMSE are `sqrt(mean_u(mean_cells_in_u(e^2)))`; their MAE, bias and p90 are the arithmetic means of the corresponding per-unit statistic. The machine-readable summary also reports source-, engine-type-, engine-count- and joint type/count slices with cell, curve and group counts.

## Engine support and stress interpretation

Every evaluated fold/test slice is classified on exact engine-type/count training support: zero training groups is `impossible_exact_cell`, one or two is `sparse_exact_cell`, and three or more is `feasible_exact_cell`. A model can still emit a prediction for an impossible exact cell by borrowing across other counts/types; that is extrapolation, not evidence of supported generalisation.

| protocol | variant | status | n_slices |
| --- | --- | --- | --- |
| internal_aircraft_group_cv | combined | feasible_exact_cell | 136 |
| internal_aircraft_group_cv | combined | impossible_exact_cell | 16 |
| internal_aircraft_group_cv | combined | sparse_exact_cell | 24 |
| temporal_release_holdout | purged | feasible_exact_cell | 24 |
| temporal_release_holdout | raw | feasible_exact_cell | 24 |

## What the evidence does and does not prove

- Internal CV tests transfer to held-out aircraft-identity components in the combined corpus. It does not test curated families or novel architectures.
- Temporal raw tests release transfer but contains exact identity overlap; temporal purged removes that known overlap. Only 11 supplement aircraft exist, so both are small tests.
- The independent frozen physics route is valid as a separate mechanistic cross-check for SEL/LAmax only. It was not fit or evaluated by this command and cannot validate EPNL/PNLTM.
- A genuinely external confirmation set must not have supplied training targets or model selection feedback. The substitution workbook is useful contextual evidence, but its curated proxy assignments and coverage are not direct measured NPD truth for the conceptual aircraft task, so correlations against it are not an absolute accuracy claim.

## Reproducibility record

- Seed: `20260724`; folds: `3`.
- Git commit: `3c4846c97cdf244c964f44d8d1e1e0c1aa6714ae`; dirty: `True`.
- Datastore SHA-256: `9b3ea2f58347ebb348128c49b3238e6a0b28852858fa7e87c89fad51d5e9fe8e`.
- Source-manifest SHA-256: `316d3362f1b064a54f6be1f026a11c3fe297a0172e4ad95fc44ba4e7e8e0683f`.
- Python `3.14.2`, numpy `2.5.1`, pandas `3.0.5`, scikit-learn `1.9.0`.
- Run duration: `30.010` s.

Fixed seeds make the multi-threaded scikit-learn fits numerically reproducible to the observed approximately `1e-13` level, not guaranteed byte-identical. Samples, split definitions, source manifest, and support matrix are byte-stable for an unchanged datastore/configuration. Prediction and summary files can differ in last-bit formatting, and timestamps, durations, Git state and the run manifest necessarily vary.

Every SHA-256 in `run_manifest.json` is a run-specific integrity hash for that emitted artifact, not a claim that independently executed model outputs must have identical bytes. Deterministic splits, samples, cell predictions, balanced summaries, support matrix, and per-fit records are all listed beside the manifest.

## Next experiments

1. Curate manufacturer/platform/engine-family labels, freeze them, then run true leave-family-out validation.
2. Add a prospectively frozen external NPD dataset with no training or model-selection use.
3. Expand rare turboprop/piston and engine-count cells before drawing conclusions from sparse/impossible support slices.
4. Calibrate predictive intervals on held-out groups; keep them distinct from raw tree dispersion.
5. Repeat the temporal holdout when a later ANP release provides a larger, genuinely new test population.
