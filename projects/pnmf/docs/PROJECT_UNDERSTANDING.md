# PNMF — Project Understanding Guide

## In one sentence

The **Parametric Noise Modeling Framework (PNMF)** gives an early-stage aircraft concept a plausible, ANP-compatible set of noise tables, so it can be assessed in an established aircraft-noise workflow before certification measurements exist.

This guide is for non-specialists. Technical definitions are in [ABBREVIATIONS.md](ABBREVIATIONS.md); detailed methods and results are in [NPD_SYSTEM_DESIGN.md](NPD_SYSTEM_DESIGN.md) and [FINAL_REPORT.md](FINAL_REPORT.md).

## 1. The problem PNMF solves

Airport-noise tools normally require **noise–power–distance (NPD)** tables. These tables describe how loud an aircraft is at several engine power settings and distances, separately for departure and approach. The EASA Aircraft Noise and Performance (ANP) database contains certification-derived tables for existing aircraft, but a new concept aircraft has no such measurements.

That creates a practical gap:

```text
New aircraft idea → no certification noise data → cannot be assessed in a
standard ANP / ECAC Doc 29 noise workflow
```

PNMF fills this gap. A user supplies a parametric aircraft description—such as engine thrust, weights, number and type of engines, and noise chapter—and PNMF produces NPD-equivalent tables in the ANP layout. These tables can enter the same downstream workflow used for real aircraft instead of requiring a separate, one-off conceptual noise method.

PNMF is a **decision-support and screening tool for aircraft concept design**. It is not a replacement for certification measurements.

## 2. What the project does today

### Creates usable noise inputs for a future aircraft

The main output is a set of NPD tables for SEL, LAmax, EPNL, and PNLTM. Each is produced for departure and approach across standard ANP power settings and distances. The tables can be exported in a strict ANP-style CSV layout for use by downstream tools.

### Uses two independent prediction routes

1. **Data-driven surrogate.** Extra Trees (`et`, default) or Random Forest (`rf`) learns from the combined legacy-v2.3 plus v6.3 ANP corpus. These are the only supported learned models. Per-tree spread provides a per-cell uncertainty indicator.
2. **Physics-based route.** A separate, simplified acoustic model combines jet, fan, and airframe sources with propagation effects. Its constants are calibrated once to an A320-211 reference and then frozen. It predicts SEL and LAmax only.

The routes are intentionally not trained from one another. Agreement increases confidence; large disagreement signals that the concept may be outside the well-supported range and deserves engineering review.

### Checks whether generated data is usable as a screening input

Before a prediction can be stored, a quality-assurance gate checks for non-finite values, implausible sound levels, and curves that increase with distance. It marks a result `caution` when model uncertainty is high or the physics and data-driven routes disagree substantially. Generated predictions are stored separately from measured ANP truth data, preventing a prediction from becoming accidental training truth.

### Connects noise tables to operating trajectories

PNMF can synthesize a simplified departure profile from ANP procedural data, then estimate a closest-approach single-event level for a ground observer. For a future aircraft, it borrows the nearest suitable real-aircraft procedure and rescales the engine deck. This closes the loop from concept definition, through noise tables, to an illustrative operational-noise result.

### Provides evidence about accuracy

The project uses leave-one-aircraft-out validation: it removes one real aircraft from training, predicts that aircraft's complete NPD tables from its parameters, and compares them with ANP data. The previously documented 4.2–5.4 dB pooled and 2.0–3.4 dB per-aircraft-median ranges are **legacy 111-set baselines**, not post-v6.3 accuracy claims. The combined corpus contains 122 NPD sets and 3,196 NPD rows; its ET/RF accuracy must be reported only from the expanded-corpus validation artifacts. The physics route's documented 2.82 dB result is likewise its historical frozen-calibration baseline.

These figures make PNMF useful for **comparative concept decisions and uncertainty-aware screening**, not for claiming a precise future certified noise level.

## 3. Why it is useful

| Design question | How PNMF helps | Appropriate interpretation |
|---|---|---|
| Is concept A likely quieter than concept B? | Generates comparable ANP-style inputs for both concepts. | Use differences and uncertainty to rank options. |
| What does higher bypass ratio appear to change? | The physics route separates jet, fan, and airframe contributions and can run a BPR sweep. | Use it for direction and sensitivity, not an engine-certification prediction. |
| Can the concept be assessed in our existing workflow? | Exports NPD-equivalent tables and provides a departure profile. | It avoids a disconnected conceptual-noise method. |
| Where is a design outside known aircraft experience? | Uncertainty, QA status, nearest-aircraft comparison, and the independent cross-check expose extrapolation. | Treat `caution` as a request for more data or detailed analysis. |
| Which variables deserve more engineering work? | Validation highlights missing geometry and propulsion descriptors as likely sources of residual error. | Use it to target the next modelling or data-collection step. |

The main benefit is consistency. Rather than assigning a future aircraft an informal proxy and losing traceability, PNMF creates a documented prediction, states uncertainty, checks physical behaviour, and keeps the result in the data format used by the established ANP/Doc 29 pipeline.

## 4. Realistic current use cases

PNMF is most useful at the conceptual or pre-certification stage, when relative decisions matter more than a final compliance value.

- **Concept trade studies:** compare alternative thrust, weight, engine-count, or bypass-ratio assumptions while the configuration changes quickly.
- **Airport and route scenario studies:** feed a provisional NPD table into an ANP/Doc 29 consumer to investigate whether a future fleet or route concept changes local noise exposure.
- **Technology sensitivity studies:** examine whether a quieter propulsion assumption affects departure more than approach, and whether airframe noise becomes limiting.
- **Early requirements discussions:** give aircraft designers, airport planners, and noise specialists a shared, explicit basis for discussion before detailed engine-cycle data or test results exist.
- **Method development and education:** use the transparent two-route design, validation harness, and traceable datastore to teach or test parametric noise-modelling methods.
- **Prioritising expensive analysis:** use uncertainty and route disagreement to decide which concepts warrant higher-fidelity simulation, component testing, or a detailed operational study.

## 5. A sensible workflow

1. Define the candidate aircraft with the parameters known at the current design stage.
2. Generate NPD tables with the data-driven model.
3. Read the uncertainty and QA status; do not ignore a `caution` flag.
4. Cross-check SEL and LAmax with the independent physics route.
5. Compare the concept with its nearest real ANP aircraft and with competing concepts, rather than treating one prediction in isolation.
6. If operational context is needed, synthesize a departure trajectory and use the resulting table/profile in the downstream Doc 29 workflow.
7. Escalate concepts with high uncertainty, strong route disagreement, or an unconventional configuration to detailed modelling or specialist review.

This is a progressive-fidelity process: PNMF helps teams make better early choices, then shows where its own answer is too uncertain to be the last word.

## 6. What PNMF should not be used for

- **Certification or regulatory compliance claims.** Certification requires measured and formally prescribed evidence; PNMF generates conceptual predictions.
- **A precise absolute prediction for an unfamiliar configuration.** The ANP training fleet is dominated by conventional aircraft. A very unusual design can be outside both the data-driven model's experience and the physics model's validated scope.
- **Replacing a complete Doc 29 implementation.** PNMF provides the NPD input and operational-profile bridge. Lateral attenuation, ground effect, and energy/duration corrections remain the responsibility of the downstream noise tool.
- **Physics-route EPNL or PNLTM results.** Tone-correction machinery for those metrics is intentionally not implemented in the physics route.
- **Assuming every value has equal confidence.** A physical table can still be an extrapolation. Uncertainty, QA status, and the physics cross-check are part of the result, not optional extras.

## 7. Important current limitations

### Limited populated design features

Although the aircraft input object has room for bypass ratio, fan diameter, wing area, and span, the common ANP data used to train the surrogate does not consistently provide them. The trained surrogate therefore relies mainly on thrust, weights, engine count/type, noise chapter, and power-related features. Two aircraft with similar basic parameters but different technology can therefore still differ in noise.

### Conventional-aircraft validation scope

Neither prediction route has been validated for unconventional layouts such as distributed propulsion, blended-wing bodies, or configurations with strongly shielded engines. Predictions for them should be treated as exploratory hypotheses, not validated results.

### Simplified operations model

The departure synthesizer makes documented conceptual assumptions, including standard atmosphere, no wind or runway gradient, and approximate speed treatment. Borrowing and scaling a neighbour's procedure is practical for screening, but is not the same as designing and validating a new aircraft's actual procedure.

### Uncertainty is an indicator, not a complete probability statement

Surrogate uncertainty is based on variation among tree predictions. It is a valuable warning indicator, especially for extrapolation, but it is not a full calibrated probability distribution of the eventual certification result.

## 8. High-value next steps

The following work would expand the project most usefully. These are proposals, not capabilities claimed by the current code.

| Priority | Proposed work | Why it matters |
|---|---|---|
| Highest | Connect a consistent aircraft-synthesis source (for example CPACS, PrADO, or RCAIDE) so BPR, fan diameter, wing area, span, flap/gear configuration, and engine-cycle variables are populated. | These are the missing explanations most likely to improve accuracy and interpretability. |
| Highest | Validate the operational-profile and downstream interface against ECAC Doc 29 reference cases and the intended FSR/NIROS integration. | This would turn the current conceptual bridge into a verified workflow component. |
| High | Add tone-correction and duration machinery to the physics route so it covers EPNL and PNLTM as well as SEL and LAmax. | The independent cross-check would then cover all NPD metrics. |
| High | Add an explicit out-of-distribution detector using feature-space distance, configuration flags, and calibrated uncertainty. | A clearer warning system would reduce overconfidence for concepts with no close ANP analogue. |
| High | Complete and interpret the full expanded-corpus ET/RF validation now that v6.3 CSV integration is implemented. | This establishes measured post-integration evidence without reusing legacy accuracy claims. |
| Medium | Add configuration-specific models or targeted data for turboprops, piston aircraft, and sparse engine classes. | The current population is uneven; specialised treatment can reduce class-specific bias. |
| Medium | Calibrate uncertainty formally, for example with held-out residual calibration or conformal prediction. | Reported intervals would be easier to interpret quantitatively. |
| Medium | Add scenario batches and automated trade-study reports. | Designers could compare many concepts, operating procedures, and observer locations reproducibly. |
| Research | Extend the physics route for shielding, distributed propulsion, novel airframes, and installation effects, then validate each extension independently. | This is essential before unconventional configurations are treated as more than exploratory cases. |

## 9. Bottom line

PNMF creates a traceable, uncertainty-aware bridge between a parametric aircraft concept and the ANP/Doc 29 ecosystem. Its strongest role is to compare alternatives, reveal risk, and guide where detailed work is worth spending effort. Read its outputs together with their validation range, QA status, uncertainty, and physics cross-check—not as a substitute for certification data or detailed engineering analysis.
