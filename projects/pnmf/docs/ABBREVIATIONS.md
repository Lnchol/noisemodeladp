# PNMF vocabulary and abbreviations

This glossary explains the abbreviations, symbols, model names and data terms
used in PNMF. It is intended to be read alongside `HOW_IT_WORKS.md` when
getting started. Meanings are specific to this repository unless stated
otherwise.

## Framework, standards and data

| Term | Expansion / meaning | Use in this project |
|---|---|---|
| **PNMF** | **Parametric Noise Modeling Framework** | The framework that turns a parametric aircraft definition into an ANP-compatible noise table. Used throughout the project. |
| **ANP** | Aircraft Noise and Performance database | The EASA data source loaded by `pnmf/anp.py`. The canonical corpus combines legacy v2.3 with the v6.3 CSV supplement and preserves per-row provenance. |
| **NPD** | Noise–Power–Distance | A table of single-event noise levels over engine-power settings and standard slant distances. `NPDTable` in `pnmf/core.py` is PNMF's in-memory representation. |
| **EASA** | European Union Aviation Safety Agency | Publisher of the ANP data and the aircraft-substitution reference data used for external validation. |
| **ECAC** | European Civil Aviation Conference | The European body behind the Doc 29 aircraft-noise modelling method that consumes NPD-style data. |
| **Doc 29** | ECAC Document 29 | The aircraft-noise calculation methodology whose NPD lookup convention PNMF follows: linear interpolation in power and logarithmic interpolation in distance. |
| **SAE** | SAE International (formerly Society of Automotive Engineers) | Source of aerospace recommended practices cited by the trajectory and acoustics layers. |
| **SAE AIR-1845** | Aerospace Information Report 1845 | The simplified departure-profile synthesis approach implemented in `pnmf/operations.py`. |
| **SAE ARP 866A** | Aerospace Recommended Practice 866A | Cited background for atmospheric-absorption calculations in `pnmf/physics.py`. |
| **FSR** | Project/tool-group label; the repository does not define an expansion | The downstream TU Darmstadt assessment context described in the README and reports. It is treated as a Doc-29-style NPD consumer. |
| **NIROS** | Downstream noise-tool name; the repository does not define an expansion | Named in the design documentation as an example FSR/Doc-29 consumer. PNMF does not implement NIROS. |
| **ICAO** | International Civil Aviation Organization | Used in the substitution-data check to identify aircraft types. |
| **CSV** | Comma-Separated Values | Source-table format. Legacy v2.3 files are semicolon-delimited; v6.3 supplement files are comma-delimited. The datastore builder handles both explicitly. |
| **SQLite** | Lightweight embedded SQL database | `anp_data.sqlite` is the canonical runtime store for combined truth and isolated predictions. Historical model-search tables may remain for reproducibility but are not part of the supported workflow. |
| **SQL** | Structured Query Language | The query language used internally for the SQLite datastore in `pnmf/anp.py`. |
| **DDL** | Data Definition Language | SQL statements that create the prediction and model-registry tables. |
| **API** | Application Programming Interface | The programmatic facade in `pnmf/api.py`, primarily `NoisePredictor`. |
| **CLI** | Command-Line Interface | `pnmf_cli.py`, which exposes datastore/manifest, ET/RF prediction and validation, physics, comparison, demo, and substitution commands. |
| **QA** | Quality assurance | The gate in `qa_check()` that rejects non-finite, implausible or distance-increasing predicted tables and marks uncertain/cross-check-disagreeing tables as `caution`. |

## Noise metrics and operating modes

| Term | Expansion / meaning | Use in this project |
|---|---|---|
| **SEL** | Sound Exposure Level | Energy-integrated single-event level, normally expressed in dB. Predicted by both the surrogate and physics routes. |
| **LAmax** | Maximum A-weighted sound level | The highest instantaneous A-weighted level during an event. Predicted by both routes and used in the sideline/flyover demonstrations. |
| **EPNL** | Effective Perceived Noise Level | Certification-oriented metric that includes perceived-noise and duration concepts. The surrogate predicts it from ANP data; the physics route intentionally does not. |
| **EPNdB** | Effective Perceived Noise decibel | The decibel unit associated with EPNL. It appears in the external aircraft-substitution data. |
| **PNLT** | Perceived Noise Level with tone correction | The tone-corrected perceived noise quantity required on the path to EPNL. It is explicitly out of scope for the physics route. |
| **PNLTM** | Maximum tone-corrected Perceived Noise Level | An ANP NPD metric stored/predicted by the surrogate and included in validation. |
| **A / D** | Approach / Departure operating mode | The two ANP modes. For example, `SEL:D` means departure SEL and `LAmax:A` means approach maximum level. |
| **dB** | decibel | Logarithmic level unit used for all PNMF output metrics and validation errors. |
| **dBA** | A-weighted decibel | Decibel level after the standard A-frequency weighting; used internally by the physics route when combining spectral bands. |
| **SPL** | Sound Pressure Level | Frequency-band level emitted by each physics component before propagation and A-weighted summation. |
| **OASPL** | Overall Sound Pressure Level | A broadband, unweighted source-level quantity used internally in the component-source formulae. |

## Aircraft, propulsion and operational quantities

| Term | Expansion / meaning | Use in this project |
|---|---|---|
| **ACFT_ID** | Aircraft identifier | ANP key that identifies an aircraft record and links procedural, aerodynamic and engine-coefficient data. |
| **NPD_ID** | NPD identifier | ANP key that identifies a shared set of NPD curves. It links the aircraft descriptor to its noise table. |
| **MTOW** | Maximum Take-Off Weight | Aircraft maximum certified take-off mass/weight. It is a core parametric feature and nearest-neighbour criterion. |
| **MLW** | Maximum Landing Weight | Aircraft maximum certified landing weight. It is a core surrogate feature. |
| **MTOM** | Maximum Take-Off Mass | Mass-form name for MTOW; appears in the data/model terminology. PNMF input fields use weight in pounds (`mtow_lb`). |
| **BPR** | Bypass Ratio | Ratio of bypass-air to core-air mass flow in a turbofan. It drives the physics route and is used for future-concept sensitivity studies; it is not populated for the ANP surrogate-training fleet. |
| **UHBR** | Ultra-High Bypass Ratio | A very high-BPR turbofan concept. `FUTURE-UHBR-TWIN` is PNMF's demonstration aircraft. |
| **CNT** | Corrected Net Thrust | ANP power-parameter label, usually in lbf. `power_features()` recognises `CNT (lb)` as an absolute-thrust axis. |
| **Fn** | Net thrust | Symbol used in the departure synthesizer's engine-deck equations; treated as thrust per engine. |
| **RPM** | Revolutions Per Minute | A rotational-speed power axis found in a small number of ANP records. PNMF converts it to a within-table throttle fraction because it is not directly a thrust unit. |
| **CAS** | Calibrated Airspeed | Airspeed used by the simplified departure-performance equations. |
| **TAS** | True Airspeed | Physical airspeed through the air. The conceptual synthesizer approximates CAS as TAS below 10,000 ft. |
| **ROC** | Rate Of Climb | Vertical climb speed. It appears in the profile-synthesis plausibility and guard logic. |
| **ISA** | International Standard Atmosphere | Standard sea-level temperature, density and pressure assumptions used in the performance and physics calculations. |
| **N1** | Low-pressure-spool / fan rotational-speed convention | Mentioned in the simplified fan-tip-Mach thrust-lapse model; it is not an ANP input column. |
| **BPF** | Blade-Passing Frequency | Fan tonal frequency calculated from tip Mach number, fan diameter and blade count in `EngineState`. |

## Acoustics, physics and units

| Term | Expansion / meaning | Use in this project |
|---|---|---|
| **ISO 9613-1** | International Standard 9613-1, atmospheric sound absorption | The atmospheric-absorption model used in `pnmf/physics.py`. |
| **IEC 61672** | International Electrotechnical Commission standard 61672 | The A-weighting reference implemented in `a_weighting()`. |
| **Hz / kHz** | Hertz / kilohertz | Frequency units. The physics route uses 24 one-third-octave bands from 50 Hz to 10 kHz. |
| **1/3-octave band** | One-third-octave frequency band | Spectral resolution of the physics component sources and ANP spectral-class-compatible bands. |
| **SI** | International System of Units | Internal unit system of the physics route: metres, newtons and metres per second. The ANP-facing layer remains feet and lbf. |
| **ft / ft²** | foot / square foot | ANP distances, trajectory altitude/distance, and some operational formulae. |
| **m / m² / m/s** | metre / square metre / metres per second | Physics-route geometry and flow units. |
| **kt** | knot | Aircraft speed unit used in ANP-style operational calculations and the 160 kt physics NPD reference flyover. |
| **lb / lbf** | pound (weight convention) / pound-force | The ANP data and public API use pounds for aircraft weights and lbf for engine thrust. Code fields ending `_lb` follow the database naming convention. |
| **N** | newton | SI force unit used internally in `pnmf/physics.py`. |
| **Pa / kPa** | pascal / kilopascal | Pressure units used in the atmospheric-absorption reference conditions. |
| **RH** | Relative Humidity | Input to atmospheric absorption; the reference condition is 70% RH. |
| **Re** | Reynolds number | Dimensionless flow quantity used by the wing/slat trailing-edge source model. |
| **V⁸, V⁶, V⁵** | Velocity-to-the-eighth/sixth/fifth scaling | Shorthand for implemented source sensitivities: jet mixing approximately V⁸, landing gear V⁶, and wing/flap sources V⁵. |
| **C_jet, C_fan, C_wingflap, C_gear** | Calibrated additive source-level constants | Four physics-route calibration parameters fitted once to A320-211 curves and then frozen for all other designs. |

## Modelling, validation and data integrity

| Term | Expansion / meaning | Use in this project |
|---|---|---|
| **ET / et** | Extra Trees (Extremely Randomized Trees) | The default supported learned model. Its per-tree variation provides the native uncertainty estimate. |
| **RF / rf** | Random Forest | The second supported learned model and ET comparison baseline. |
| **GBR / gbr** | Gradient Boosting Regressor | Historical experiment only. It is rejected by the current learned-model API and is not exposed by the CLI or UI. |
| **kNN** | k-Nearest Neighbours | Nearest-neighbour proxy baseline mentioned in the validation comparisons. |
| **GP** | Gaussian Process | A probabilistic-regression reference point. Cross-tree standard deviation is described as a less expensive stand-in for GP predictive variance. |
| **LOO** | Leave-One-Out (here, leave-one-aircraft-out) | Validation in which a model is retrained without one `NPD_ID` and predicts that held-out aircraft's full table. |
| **CV** | Cross-Validation | Repeated held-out validation, including PNMF's leave-one-aircraft-out ET/RF evaluation. |
| **GroupKFold** | Grouped K-fold cross-validation | scikit-learn splitter used to ensure all rows from an aircraft remain together, preventing aircraft leakage between train/test folds. |
| **RMSE** | Root Mean Squared Error | Main validation score, in dB. It penalises larger errors more strongly. |
| **MAE** | Mean Absolute Error | Supplementary validation score, in dB. |
| **bias** | Mean signed prediction error | Reported as prediction minus truth; it shows systematic over- or under-prediction. |
| **p90** | 90th percentile | In validation summaries, the 90th percentile of absolute cell error. |
| **σ / std** | Standard deviation | In predicted NPD tables, the cross-tree standard deviation per cell. High mean uncertainty triggers a QA `caution` result. |
| **isotonic regression** | Monotonic constrained regression | Enforces the physical rule that predicted level cannot increase as distance increases. |
| **semi-empirical model** | Historical fitted scaling model | Historical regression experiment. It is distinct from the current component-source `PhysicsNPDModel` and is not supported publicly. |
| **truth tables (`anp_*`)** | Measured/source ANP data | Combined v2.3+v6.3 tables written only by datastore construction. They are the sole training/validation source. |
| **prediction tables (`predicted_*`)** | PNMF-generated future-aircraft data | QA-gated outputs stored separately from truth to prevent training on generated data. |

## Named external tools and organisations

| Term | Expansion / meaning | Use in this project |
|---|---|---|
| **pyNA** | Python Noise Assessment | NASA-associated conceptual aircraft-noise framework family. PNMF's physics route is described as pyNA-family, not as a dependency on pyNA. |
| **ANOPP** | Aircraft NOise Prediction Program | NASA noise-prediction program cited as part of the component-source model family. |
| **PANAM** | Aircraft-noise prediction tool name; expansion is not defined in this repository | DLR tool cited as comparable conceptual-design practice. |
| **DLR** | German Aerospace Center (`Deutsches Zentrum für Luft- und Raumfahrt`) | Organisation cited in the ANSWr inter-tool-comparison context. |
| **NASA** | National Aeronautics and Space Administration | Organisation associated with pyNA/ANOPP and the inter-tool context. |
| **ONERA** | French aerospace research laboratory (`Office national d'études et de recherches aérospatiales`) | Organisation cited in the ANSWr inter-tool-comparison context. |
| **ANSWr** | Aircraft Noise Simulation Working group / inter-tool comparison name; expansion is not defined in this repository | Used only as a cited 3–4 dB inter-tool-agreement benchmark. The spelling appears as `ANSWr`/`ANSWR` in project material. |
| **FAA** | Federal Aviation Administration | Cited through the Fink FAA-RD-77-29 airframe-noise correlation family. |
| **CPACS** | Common Parametric Aircraft Configuration Schema | Suggested future source for geometry and propulsion features not present in the ANP fleet. |
| **RCAIDE** | Aircraft-design framework name; expansion is not defined in this repository | Suggested future source for geometry/propulsion features. |
| **PrADO** | Aircraft-design tool name; expansion is not defined in this repository | Suggested future source for geometry/propulsion features. |

## Reading compact labels in PNMF outputs

- `SEL:D`, `EPNL:A`, and similar labels read as **metric:operating mode**.
- `L_200ft` through `L_25000ft` are NPD level columns at the ten standard
  slant distances in feet.
- A `power_setting` row and its `power_param` say how the NPD power axis is
  measured. `CNT (lb)`, percent of maximum static thrust and RPM must not be
  compared as if they were the same unit.
- `std_*` columns are uncertainty companions to the corresponding `L_*`
  columns; they are deliberately excluded from strict ANP-layout CSV exports.
- `ok`, `caution`, and `rejected` are QA statuses. A rejected table is never
  written to the prediction store.
