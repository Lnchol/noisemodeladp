# How PNMF works

## 1. Build and inspect the data

`build_datastore()` reads the actual raw schemas:

- legacy v2.3 uses semicolon-delimited CSVs;
- v6.3 uses comma-delimited CSVs with matching aircraft/NPD fields.

Strings, whitespace, and operation modes are normalized. Tables are merged on
declared business keys; v6.3 wins true key collisions. `7773ER` is deliberately
kept twice in the aircraft table because its two source records point to
different NPD sets (`GE9015` and `7773ER`). This preserves both certified
curves and referential integrity.

The SQLite tables include `source_dataset` and `source_file`.
`anp_dataset_manifest` records source rows, merge keys, duplicate policy,
combined rows, and removed collisions.

## 2. Train ET or RF

For every noise metric/operation pair, `SurrogateNPDModel` builds one row per
NPD power setting:

`aircraft features + unit-corrected power features -> 10 distance levels`.

`et` is the default based on the prior legacy-corpus bake-off; `rf` remains the
supported comparison model. Both train on the combined v2.3+v6.3 corpus.
Predictions are projected to monotone non-increasing distance curves.

## 3. Cross-check component physics

`PhysicsNPDModel` independently combines jet, fan, and airframe component
sources and propagation. It is calibrated once on A320-211 and then frozen.
It needs a bypass ratio and component/geometry assumptions. Its supported
metrics are SEL and LAmax; EPNL/PNLTM tone corrections are outside scope.

## 4. Validate and store

Leave-one-aircraft-out validation evaluates ET/RF without training on the held
out NPD set. Prediction storage checks finite/plausible levels, distance
monotonicity, uncertainty, and physics disagreement. Generated data can never
enter the `anp_*` truth tables.
