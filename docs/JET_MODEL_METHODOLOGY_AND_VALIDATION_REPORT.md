# Jet Model Methodology and Validation Report

This report is screening evidence for interpolation in the available ANP population, not unseen-family, uncertainty-calibration, or certification evidence.

## Decision

- Feature set: compact nine-feature Jet production schema.
- Jet route gate: **PASS**.
- Production training population: complete Jet population.
- Population: `2664` rows, `94` curves, `93` aircraft groups.

A failed candidate gate keeps the compact production feature set. Production promotion is an explicit audited source change; validation output cannot silently reroute production.

## Learned-model comparison

- ET group/task-balanced RMSE: `4.451 dB`; RF validation RMSE: `4.828 dB`.
- Paired aircraft-group ET minus RF bootstrap interval: `[-0.8165001554283696, -0.019265505600573204]` dB; RF cannot become the production learner through this workflow.
- Equal task weighting is applied after aircraft-group balancing. Selected-schema task RMSE:
- `EPNL/A`: `4.089 dB`
- `EPNL/D`: `5.088 dB`
- `LAmax/A`: `3.752 dB`
- `LAmax/D`: `4.782 dB`
- `PNLTM/A`: `4.139 dB`
- `PNLTM/D`: `5.066 dB`
- `SEL/A`: `3.664 dB`
- `SEL/D`: `4.769 dB`
- Selected-schema balanced task comparison:
- `EPNL/A`: ET `4.089 dB` vs RF `4.405 dB` (winner: `ET`).
- `EPNL/D`: ET `5.088 dB` vs RF `5.558 dB` (winner: `ET`).
- `LAmax/A`: ET `3.752 dB` vs RF `3.969 dB` (winner: `ET`).
- `LAmax/D`: ET `4.782 dB` vs RF `5.286 dB` (winner: `ET`).
- `PNLTM/A`: ET `4.139 dB` vs RF `4.367 dB` (winner: `ET`).
- `PNLTM/D`: ET `5.066 dB` vs RF `5.501 dB` (winner: `ET`).
- `SEL/A`: ET `3.664 dB` vs RF `3.911 dB` (winner: `ET`).
- `SEL/D`: ET `4.769 dB` vs RF `5.277 dB` (winner: `ET`).
- Task-level result: **ET wins all 8 recorded tasks.**

## Protocol

Five-fold grouped validation uses seeds `[13, 91, 20260724]`. Groups are stratified jointly by engine count and aircraft-level log-total-static-thrust tertile; no aircraft group crosses folds. All eight metric/mode tasks contain all 94 Jet curves.
The selected-feature RMSE reuses the grouped folds used for feature selection; it is not a nested-CV or post-selection holdout estimate.
The frozen 83-legacy-to-11-v6.3 comparison remains descriptive release-transfer evidence, not a pristine unseen test.

## Feature schemas and formula

The derived field is `log_total_operating_cnt_lb = log10(per-engine corrected net thrust in lb) + log10(engine count)`. It is not generic power output. Jet schemas remove constant engine-type one-hot columns and compare compact, count-removed, count-replaced, and count-plus-total candidates.

Production feature order: `n_engines`, `log_mtow`, `log_mlw`, `mlw_mtow`, `log_thrust_per_eng`, `log_total_thrust`, `noise_chapter`, `log_power_lb`, `throttle`.
The frozen comparison covers the compact feature set, engine count removed, engine count replaced by total operating CNT, and compact features plus total operating CNT.

## Conservative gate

Thresholds: `{"max_rf_regression_fraction": 0.01, "max_slice_regression_db": 0.5, "max_task_regression_db": 0.25, "min_relative_improvement": 0.05, "tie_margin_db": 0.05}`. ET must improve at least 5%; the 10,000-resample paired aircraft-group bootstrap interval must be below zero; task, count/static/operating-CNT slices and RF are bounded by the declared regression limits.

## Artifacts

`samples.csv`, `splits.csv`, `predictions.csv`, `fit_runs.csv`, `schema_metrics.json`, `gate_decisions.json`, and `bootstrap_results.json` contain the exact features, formulas, splits, predictions, metrics, thresholds, hashes, and decisions.
The validated datastore SHA-256 is `ab1a1a23865bc3faecf80671b83f6f114cdce2cc79deb32b7687a3cd3930a8d7`. Source release hashes and URLs are recorded in `anp_dataset_manifest` and `docs/EASA_ECAC_SOURCE_LEDGER.md`.
The Doc 29 lane is run only with `verify-doc29-reference --workbook <official-workbook>` and checks interpolation/reference-case equivalence; it does not measure ET accuracy or validate component physics.
Component physics remains a separate SEL/LAmax plausibility lane with its own provenance, fallbacks, and exclusions; it does not receive learned features, residuals, or corrections.

## Scientific boundaries

The learned ET/RF and frozen physics SEL/LAmax routes remain independent. No power-axis monotonic constraint is added because the Jet truth contains curve-task reversals. Results remain conceptual screening evidence, not certification or calibrated uncertainty.
EASA source provenance does not establish ML accuracy. ECAC Doc 29 Volume 3 Part 1 is an implementation/reference-case check, not real-aircraft measurement validation.
