---
slug: physics-reference-harness
status: awaiting-approval
intent: clear
review_required: false
pending-action: write .omo/plans/physics-reference-harness.md
approach: Add a local-only SERDP09 case-844 jet-spectrum validator that reads the user-supplied archive, compares peak-normalized 1/3-octave spectral shape and directivity without fitting PNMF, and records measured/predicted residuals.
---

# Draft: physics-reference-harness

## Components (topology ledger)
<!-- Lock the SHAPE before depth. One row per top-level component that can succeed or fail independently. -->
<!-- id | outcome (one line) | status: active|deferred | evidence path -->
<!-- source-case | Select and parse NASA SERDP09 clean G6S1/44080 acquisition 844 with its measured flow state and lossless PSD | active | tmp/SERDP09_MDOEchevron/SERDP09acousticEscort.xlsx; tmp/SERDP09_MDOEchevron/844_nb/844_nb.dat; tmp/SERDP09_MDOEchevron/SERDP09TestReqtsV3.8.doc -->
<!-- physics-check | Evaluate the existing JetSource against the parsed case and report only shape/directivity residuals, never a re-fit or certification result | active | projects/pnmf/pnmf/physics.py:467-538; projects/pnmf/tests/test_physics.py -->

## Open assumptions (announced defaults)
<!-- Record any default you adopt instead of asking, so the user can veto it at the gate. -->
<!-- assumption | adopted default | rationale | reversible? -->
<!-- reference case | Use NASA SERDP09 icrdg=844, no-chevron G6S1/44080 static case | Workbook config2=na; matched 855 is chevron P02L13W08; 844 directly maps to 844_nb.dat | yes -->
<!-- comparison contract | Peak-normalized 1/3-octave shape and directivity only | NASA PSD at 1-ft model scale and PNMF 1-m SPL have different additive references; normalization avoids invalid absolute-level claims | yes -->
<!-- data handling | Keep the NASA archive under tmp and never stage it; validator takes an explicit data-root | workspace rules forbid raw-data staging | yes -->
<!-- test strategy | TDD: synthetic ASCII-spectrum parsing test plus local real-data validator run | protects the archive reader without committing NASA raw data | yes -->

## Findings (cited - path:lines)

- `tmp/SERDP09_MDOEchevron/0SERDP09acousticREADME.txt`: archive defines `icrdg` as the join key from Excel conditions to `<icrdg>_nb/<icrdg>_nb.dat`; spectra are ASCII frequency/angle/PSD and `-999` is invalid.
- `tmp/SERDP09_MDOEchevron/SERDP09acousticEscort.xlsx`, `SERDP09_FF.db!A142:AJ142`: case 844 is `52FF`, `G6S1`, `config2=na`, setpoint 44080, with ambient/core/bypass measured state. `A152:AJ152` is matched chevron case 855.
- `tmp/SERDP09_MDOEchevron/SERDP09TestReqtsV3.8.doc`, Model Hardware/Table 2 and Instrumentation/Far-field acoustics: G6 is a 1.65-Mach F400 nozzle; measurements are 24-angle, 1-ft lossless source-centric PSD in dB re 20 uPa.
- `projects/pnmf/pnmf/physics.py:467-538`: `JetSource` already emits unweighted 1/3-octave source spectra from supplied streams. It must be invoked directly, avoiding `PhysicsNPDModel` event propagation and calibration.

## Decisions (with rationale)

- Reuse `JetSource`, `EngineState`, and `THIRD_OCTAVE_HZ`; do not change source equations or model anchors.
- Convert NASA narrowband PSD to integrated 1/3-octave levels before normalizing each spectrum by its peak. Exclude `-999` and the invalid 160-degree samples.
- Map NASA measured core/bypass streams to the existing detailed source path only after unit conversion. If its required supplied-stream gate cannot be met exactly, report the case as incompatible instead of silently using PNMF fallback estimates.
- Keep ECAC Volume 3 out of this increment; it is a future full-Doc-29 contour verification target, not a component-jet benchmark.
- Keep the increment physics-only. It cannot improve ET/RF accuracy directly: the NASA spectra are component-source measurements, while ET/RF are trained only from provenance-controlled ANP truth rows. The residual report may identify physics-model limitations or future feature-research priorities, but it must not become an ET/RF feature, target, calibration input, or validation score.

## Scope IN

- A local archive reader and explicit `--data-root` validation command for SERDP09 case 844.
- TDD coverage for parser/invalid-value handling and focused local run against the supplied archive.
- A compact provenance/residual report with data hash, condition fields, comparison contract, and screening-only limitation.

## Scope OUT (Must NOT have)

- No ET/RF changes, ANP fitting, Doc-29 interpolation, A320 calibration changes, aircraft-input additions, chevron modelling, or certification claim.
- No raw NASA spectra, workbook, Word file, ZIP, or generated output staged in Git.
- No absolute-level or EPNL/PNLTM validation claim.
- No ET/RF model, feature, training, selection, calibration, or validation change.

## Open questions

- None. The scoped default is to keep the harness local-only and shape/directivity-only.

## Approval gate
status: awaiting-approval
<!-- When exploration is exhausted and unknowns are answered, set status: awaiting-approval. -->
<!-- That durable record is the loop guard: on a later turn read it and resume at the gate instead of re-running exploration. -->
