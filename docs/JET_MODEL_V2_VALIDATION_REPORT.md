# Jet-v2 Model Validation Report

> Historical superseded report. The canonical active artifact is [Jet Model Methodology and Validation](JET_MODEL_METHODOLOGY_AND_VALIDATION_REPORT.md); this file is retained only for audit traceability and is not a production-selection authority.

This report is screening evidence for interpolation in the available ANP population, not unseen-family, uncertainty-calibration, or certification evidence.

## Decision

- Feature schema: `jet_compact_v1`; frozen identifier: `jet-v2`.
- Jet route gate: **PASS**.
- Production scope: `jet_merged`.
- Population: `2664` rows, `94` curves, `93` aircraft groups.

A failed candidate gate freezes compact Jet-v2. Production promotion is an explicit audited source change; historical scope identities are not selected from this report.

## Protocol

Five-fold grouped validation uses seeds `[13, 91, 20260724]`. Groups are stratified jointly by engine count and aircraft-level log-total-static-thrust tertile; no aircraft group crosses folds. All eight metric/mode tasks contain all 94 Jet curves.
The frozen 83-legacy-to-11-v6.3 comparison remains descriptive release-transfer evidence, not a pristine unseen test.

## Feature schemas and formula

The derived field is `log_total_operating_cnt_lb = log10(per-engine corrected net thrust in lb) + log10(engine count)`. It is not generic power output. Jet schemas remove constant engine-type one-hot columns and compare compact, count-removed, count-replaced, and count-plus-total candidates.

Frozen schema names: `{"jet_add_total_operating_v1": ["n_engines", "log_mtow", "log_mlw", "mlw_mtow", "log_thrust_per_eng", "log_total_thrust", "noise_chapter", "log_power_lb", "throttle", "log_total_operating_cnt_lb"], "jet_compact_v1": ["n_engines", "log_mtow", "log_mlw", "mlw_mtow", "log_thrust_per_eng", "log_total_thrust", "noise_chapter", "log_power_lb", "throttle"], "jet_drop_count_v1": ["log_mtow", "log_mlw", "mlw_mtow", "log_thrust_per_eng", "log_total_thrust", "noise_chapter", "log_power_lb", "throttle"], "jet_replace_count_v1": ["log_mtow", "log_mlw", "mlw_mtow", "log_thrust_per_eng", "log_total_thrust", "noise_chapter", "log_power_lb", "throttle", "log_total_operating_cnt_lb"]}`.

## Conservative gate

Thresholds: `{"max_rf_regression_fraction": 0.01, "max_slice_regression_db": 0.5, "max_task_regression_db": 0.25, "min_relative_improvement": 0.05, "tie_margin_db": 0.05}`. ET must improve at least 5%; the 10,000-resample paired aircraft-group bootstrap interval must be below zero; task, count/static/operating-CNT slices and RF are bounded by the declared regression limits.

## Artifacts

`samples.csv`, `splits.csv`, `predictions.csv`, `fit_runs.csv`, `schema_metrics.json`, `gate_decisions.json`, and `bootstrap_results.json` contain the exact features, formulas, splits, predictions, metrics, thresholds, hashes, and decisions.

## Scientific boundaries

The learned ET/RF and frozen physics SEL/LAmax routes remain independent. No power-axis monotonic constraint is added because the Jet truth contains curve-task reversals. Results remain conceptual screening evidence, not certification or calibrated uncertainty.
