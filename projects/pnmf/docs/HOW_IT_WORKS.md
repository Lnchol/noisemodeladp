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

`PhysicsNPDModel` independently evaluates gated jet, fan and optional core
sources plus six airframe sources. It propagates one-third-octave spectra into
component and total receiver time histories, then derives SEL and LAmax.
Inputs are marked supplied, estimated or unavailable, and missing detailed
engine data trigger explicit fallbacks. Four source anchors are calibrated
once on A320-211 and then frozen. EPNL/PNLTM tone corrections remain outside
scope. Full equations and gaps are documented in
`PNMF_COMPONENT_PHYSICS_TECHNICAL_PAPER.pdf`.

To run it interactively, stay in **Aircraft Designer**. Select one shared
aircraft and choose learned only, component physics only, or compare mode.
Compare mode prepares ET/RF and then exposes event thrust, closest distance,
BPR, airframe/configuration and atmosphere below the shared-aircraft summary.
Optional typed engine-deck fields activate detailed fan and core paths when
complete. Physics SEL/LAmax, NPD curves, component contributions, event time
histories and evidence-status tables appear in the same section. ET/RF is only
an output overlay and does not provide a physics input.

Each run button maintains a live operation trace. ET/RF reports power-grid
canonicalization, feature preparation and all metric/operation table
evaluations. Component physics reports unit-boundary conversion, typed design
assembly, frozen calibration, enabled sources, propagation, acoustic-energy
summation, event metrics and both physics NPD tables. The trace observes
execution only; it does not change calculations or couple the two routes.

The shared-aircraft selector includes source-labelled physical presets for the
v6.3 `A320-270N`, `A350-1041`, and `7773ER` records. Applying a preset updates
both the learned aircraft and physics inputs. Published span, engine and
landing-gear fields remain `supplied`; calculated wing area and incomplete
geometry remain `estimated`. The source register is
[`PHYSICS_PRESETS.md`](PHYSICS_PRESETS.md).

## 4. Validate and store

Leave-one-aircraft-out validation evaluates ET/RF without training on the held
out NPD set. Prediction storage checks finite/plausible levels, distance
monotonicity, uncertainty, and physics disagreement. Generated data can never
enter the `anp_*` truth tables.
