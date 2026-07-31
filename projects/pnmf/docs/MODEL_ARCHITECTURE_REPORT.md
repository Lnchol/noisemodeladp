# PNMF basic model architecture

## Data

| Source | Role | NPD sets | NPD rows |
|---|---|---:|---:|
| Legacy v2.3 CSV | base training/evaluation fleet | 111 | 2,776 |
| v6.3 CSV | explicit training/evaluation supplement | 11 | 420 |
| Combined | canonical corpus | 122 | 3,196 |

The v6.3 data is training data, not merely evaluation or comparison data.
`build_datastore()` reads its comma-delimited CSVs, and the manifest plus
row-level provenance proves its contribution.

## Input → model → output

Aircraft type, engine count, thrust, weights, chapter, and power setting feed a
learned multi-output regressor. It predicts the ten standard-distance NPD
levels for each metric and operation mode.

Supported learned models are Extra Trees (`et`, default) and Random Forest
(`rf`). Historical regression experiments remain internal for reproducibility
but are retired from the API, CLI, and UI.

`PhysicsNPDModel` is a separate component-source calculation using gated jet,
fan and optional core branches, six airframe sources, and free-field
propagation. It is not a regression model. It supports SEL/LAmax. Explicit
physical inputs are preferred; missing detailed inputs activate visible
low-fidelity fallbacks.

ET/RF success is measured with leave-one-aircraft-out validation. Physics is
calibrated once on A320-211 and evaluated out of sample. Every generated table
must also pass finite-range, distance-monotonicity, uncertainty, and
route-disagreement QA checks.
