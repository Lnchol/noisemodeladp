# ANP v6.3 Jet Release-Holdout Validation Report

> Generated 2026-07-24T12:20:39.734044+00:00 from frozen EASA ANP reference data. This is conceptual-screening evidence, not certification evidence.

## Conclusion and evidence boundary

v6.3 is preferable as newer EASA-collected/verified reference provenance, but no official source proves universal accuracy superiority.

This conclusion is about source provenance and release chronology, not a claim that every v6.3 curve is intrinsically more accurate than every legacy curve. EASA states that it collects, verifies and makes ANP data available under Regulation (EU) No 598/2014. EASA separately describes v2.3 as legacy data collected before that mandate.

- [EASA Aircraft Noise and Performance (ANP)](https://www.easa.europa.eu/en/domains/environment/policy-support-and-research/aircraft-noise-and-performance-anp-data)
- [EASA ANP legacy data](https://www.easa.europa.eu/en/domains/environment/policy-support-and-research/aircraft-noise-and-performance-anp-data/anp-legacy-data)
- [Regulation (EU) No 598/2014](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32014R0598)

## Protocol

The primary training protocol uses only complete-task Jet curves from legacy v2.3. No v6.3 target row enters training. The frozen test contains three v6.3 references selected before errors by descriptor-only distance.

![Validation architecture](jet_reference_assets/jet_reference_architecture.png)

For each engine-count category, the candidate pool is restricted to `source_dataset=supplement_v6.3`, `engine_type=Jet`, and all eight metric/mode tasks. Medians and IQRs are calculated within that v6.3 category over `[log10(MTOW_lb), log10(total static thrust_lb), noise chapter]`:

`distance = sqrt(sum_j (((x_j - median_j) / IQR_j)^2))`.

A zero-IQR contribution is exactly zero. Lowest score wins; lexical `NPD_ID` is the deterministic tie-break. Noise targets, predictions and errors are not selection inputs.

- 2 engines: `A330-743L` / Airbus A330-743L / RR Trent 772B / robust distance `0.216692`.
- 3 engines: `FAL900EX` / Dassault FAL900EX / TFE731-60 / robust distance `0.000000`.
- 4 engines: `747400RN` / Boeing 747400RN / PW4062A / robust distance `0.000000`.

The three-engine and four-engine categories each contain only one v6.3 candidate. Their zero distances express singleton category medians; those aircraft are not general representatives of their engine-count populations.

## Family purge and exact separation

Before fitting, the conservative predeclared family guard removes `CF680E`, `TRENT7`, `JT9DBD`, `JT9DFL`, `JT9D7Q`, `PW4056`, and `GENX67` from the legacy training pool because they are A330/747 family analogues of the selected references. Falcon 20 is not automatically purged: no broad Falcon-name heuristic is used.

The resulting train/test split is 76/3 curves. Training contains 57 twin, 9 tri, and 10 quad curves. Per task it contains 216 approach and 297 departure power rows. The test contains 12 approach and 17 departure rows per metric: 29 per metric × 4 metrics = 116 rows and 1160 power-distance cells.

FAL900EX grids are approach `{500, 1000, 1500, 2000}` lbf and departure `{2500, 3000, 3500, 4000, 4500, 4700}` lbf. The contract fails if these grids, the source split, purge set, counts, ACFT_ID separation, or selected references drift.

## Models and metrics

Production Extra Trees (ET) and Random Forest (RF) are fitted independently for all eight EPNL, LAmax, PNLTM and SEL × approach/departure tasks. The standard 12 learned features and monotone distance projection are unchanged. `PhysicsNPDModel` remains an independent SEL/LAmax component-source route and supplies neither features nor targets to this experiment.

- `error = prediction − truth`
- `RMSE = sqrt(mean(error²))`
- `MAE = mean(abs(error))`
- `bias = mean(error)`
- `p90 = percentile(abs(error), 90)`
- `within ±k dB = 100 × mean(abs(error) ≤ k)`

Cell-pooled results weight every power-distance cell equally. Category-balanced results calculate metrics per engine-count category and give each of the three categories equal weight; balanced RMSE is the square root of mean category MSE.

| model | aggregation | engine_count_category | rmse_dB | mae_dB | bias_dB | p90_abs_error_dB | pct_within_3_dB | pct_within_5_dB | n_cells |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| et | category_balanced | all | 3.931 | 3.213 | 0.459 | 6.010 | 50.648 | 73.343 | 1160 |
| et | cell_pooled | all | 3.953 | 3.239 | 0.545 | 6.425 | 50.000 | 72.931 | 1160 |
| rf | category_balanced | all | 3.868 | 3.193 | 0.413 | 5.785 | 51.972 | 74.491 | 1160 |
| rf | cell_pooled | all | 3.900 | 3.231 | 0.491 | 6.398 | 51.121 | 73.966 | 1160 |

## Results by reference category

| model | aggregation | engine_count_category | rmse_dB | mae_dB | bias_dB | p90_abs_error_dB | pct_within_3_dB | pct_within_5_dB | n_cells |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| et | cell_pooled | 2 | 3.240 | 2.440 | -2.021 | 5.972 | 69.444 | 85.278 | 360 |
| et | cell_pooled | 3 | 2.993 | 2.232 | -1.562 | 5.386 | 74.500 | 88.000 | 400 |
| et | cell_pooled | 4 | 5.187 | 4.966 | 4.961 | 6.672 | 8.000 | 46.750 | 400 |
| rf | cell_pooled | 2 | 2.765 | 2.087 | -1.855 | 5.222 | 76.667 | 89.722 | 360 |
| rf | cell_pooled | 3 | 3.121 | 2.503 | -1.894 | 5.271 | 67.000 | 88.500 | 400 |
| rf | cell_pooled | 4 | 5.244 | 4.987 | 4.987 | 6.863 | 12.250 | 45.250 | 400 |

![Overall metrics](jet_reference_assets/jet_reference_metrics.png)

“Within ±3 dB” and “within ±5 dB” are threshold-agreement percentages over correlated cells. They are not aircraft-level success rates, confidence probabilities, or certification margins.

![Truth versus prediction](jet_reference_assets/jet_reference_npd_comparison.png)

![Residual heatmap](jet_reference_assets/jet_reference_residual_heatmap.png)

## Limitations

- Only three independent NPD curves are tested; 1,160 cells do not constitute 1,160 independent aircraft.
- Tri- and quad-engine results each come from a singleton v6.3 candidate and cannot establish category-wide performance.
- Descriptor selection covers only weight, installed static thrust and noise chapter; it omits detailed geometry and engine technology.
- The conservative A330/747 purge reduces obvious family leakage but cannot prove the absence of all engineering similarity.
- Findings apply to these conventional jets and eight NPD tasks, not unconventional configurations, fleet-wide accuracy, or certification.

## Reproducibility and provenance

- Seed `20260724`; runtime `7.857` s.
- Datastore SHA-256 `9b3ea2f58347ebb348128c49b3238e6a0b28852858fa7e87c89fad51d5e9fe8e`.
- Source-manifest SHA-256 `316d3362f1b064a54f6be1f026a11c3fe297a0172e4ad95fc44ba4e7e8e0683f`.
- Git `fa736685444f0ebdd64f019f21b3a368007b823d`, dirty `True`.
- Full candidate scores, reference metadata, split exclusions, predictions, fit records, summaries, source manifest, artifact hashes and official URLs are in `outputs/model_validation/jet_reference_v63`.
