# physics-reference-harness - Work Plan

> Superseded 2026-08-01 by user direction: remove NASA/SERDP09 implementation. The external archive remains an ignored, optional future high-speed supplementary-validation input; this plan's remaining final-gate items are intentionally not executed.

## TL;DR (For humans)
**What you'll get:** A local physics-reference check using the supplied NASA jet-noise measurements. It will either produce clearly scoped spectrum/directivity screening residuals or explain exactly why the reference cannot validly be compared.

**Why this approach:** It reuses the current physics model with fixed settings and refuses to fit it. That protects the frozen aircraft calibration while turning the new source data into honest evidence.

**What it will NOT do:** It will not change the learned ET/RF models, expand aircraft inputs, or claim certification. It will not download, commit, or alter the supplied measurement data.

**Effort:** Medium
**Risk:** Medium - the published material may not prove the stream and frequency mapping required for a valid comparison.
**Decisions to sanity-check:** An evidence-backed “incompatible” result is a successful safety outcome, not a reason to guess a mapping.

Your next move: start execution now, or request a high-accuracy review first. Full execution detail follows below.

---

> TL;DR (machine): Medium effort, medium mapping-evidence risk; local case-844 parser, guarded fixed-physics comparator, explicit command, and auditable real-data result.

## Scope
### Must have
- A local-only validation command for the user-supplied NASA SERDP09 MDOE archive, with an explicit absolute archive root supplied at invocation.
- Read the source workbook and narrowband `.dat` spectra; reject malformed, incomplete, or invalid readings instead of substituting values.
- Compare a documented fixed use of the existing `JetSource` with case 844 in shape/directivity space only, then emit an auditable machine-readable report.
- Preserve the frozen A320 calibration by never calling model calibration or modifying physics coefficients.
- Add focused synthetic tests and run the real local case when compatibility can be proven.

### Must NOT have (guardrails, anti-slop, scope boundaries)
- No ET/RF changes, retraining, aircraft-input expansion, ANP/SQLite writes, or UI/API changes.
- No new external dependency, web download, raw NASA data, derived spectrum, or report artifact committed to Git.
- No absolute SPL/error target and no fitted scale, angle offset, frequency offset, or calibration factor.
- No silent simple-mixed-jet fallback. If the archive-to-`JetSource` stream mapping or model-scale frequency basis is not proven, return a structured `incompatible` verdict with evidence.

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: TDD using the existing `unittest` suite via `projects\\pnmf\\pnmf.ps1 test`; synthetic temporary workbook/DAT data only.
- Evidence: `<attemptDir>/task-<N>-physics-reference-harness.md` (attemptDir = currentAttemptDir from `omo ulw-loop status --json`, `.omo/evidence/ulw/<session>/<goalId>/a<attempt>`; outside ulw-loop use `.omo/evidence/`).
- Real-data evidence: an ignored report under the explicit local archive root, containing source-file hashes, selected record IDs, inputs, compatibility decision, metrics/exclusions, and command line.

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.

Wave 1: todos 1 and 2 establish the narrow local-data boundary and parser contract.

Wave 2: todos 3 and 4 add the evaluator and its one explicit command surface.

Wave 3: todo 5 runs the supplied archive and captures the decision/report.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1 | none | 2, 5 | none |
| 2 | 1 | 3, 4, 5 | none |
| 3 | 2 | 4, 5 | none |
| 4 | 2, 3 | 5 | none |
| 5 | 1, 2, 3, 4 | final wave | none |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [x] 1. Keep the supplied SERDP09 archive local and explicitly ignored
  What to do / Must NOT do: Add only the narrow `tmp/SERDP09_MDOEchevron/` ignore rule; do not ignore the whole `tmp/` tree or modify any existing untracked user work. Confirm no raw workbook, Word file, DAT spectrum, or generated report is tracked.
  Parallelization: Wave 1 | Blocked by: none | Blocks: 2, 5
  References (executor has NO interview context - be exhaustive): `.gitignore`; `tmp/SERDP09_MDOEchevron/0SERDP09acousticREADME.txt`; workspace `AGENTS.md` PNMF routing and data-safety rules.
  Acceptance criteria (agent-executable): `git check-ignore -v tmp/SERDP09_MDOEchevron/SERDP09acousticEscort.xlsx` succeeds; `git status --short -- tmp/SERDP09_MDOEchevron` emits no trackable archive files.
  QA scenarios (name the exact tool + invocation): PowerShell `git check-ignore` for the workbook and one `.dat`; Evidence `<attemptDir>/task-1-physics-reference-harness.md`.
  Commit: N | n/a

- [x] 2. Parse selected SERDP09 conditions and narrowband spectra with a synthetic contract
  What to do / Must NOT do: Add the smallest parser module at `projects/pnmf/pnmf/serdp09_reference.py` and `projects/pnmf/tests/test_serdp09_reference.py`. Parse the archive README, selected workbook record, and DAT header/body; map `icrdg` to `<icrdg>_nb/<icrdg>_nb.dat`; integrate PSD in linear units over exact third-octave edges into existing `THIRD_OCTAVE_HZ` bands. Reject `-999`, invalid headers, duplicate/missing angles, non-finite data, and out-of-range bands. Do not add pandas or read an implicit default archive location.
  Parallelization: Wave 1 | Blocked by: 1 | Blocks: 3, 4, 5
  References (executor has NO interview context - be exhaustive): `projects/pnmf/pnmf/physics.py` (`THIRD_OCTAVE_HZ`, `JetSource`); `tmp/SERDP09_MDOEchevron/0SERDP09acousticREADME.txt`; `tmp/SERDP09_MDOEchevron/SERDP09TestReqtsV3.8.doc` page 12; `tmp/SERDP09_MDOEchevron/SERDP09acousticEscort.xlsx` sheet `SERDP09_FF.db`.
  Acceptance criteria (agent-executable): focused tests construct temporary mini-workbook/DAT files and verify record lookup, PSD integration, and each rejection branch; `projects\\pnmf\\pnmf.ps1 test` passes.
  QA scenarios (name the exact tool + invocation): `projects\\pnmf\\pnmf.ps1 test` includes valid synthetic data and malformed/invalid `-999` input; Evidence `<attemptDir>/task-2-physics-reference-harness.md`.
  Commit: N | n/a

- [x] 3. Evaluate only a proven source-model comparison, otherwise report incompatibility
  What to do / Must NOT do: Add an evaluator beside the parser that uses the existing `JetSource` and `THIRD_OCTAVE_HZ` with fixed, declared parameters and no `PhysicsNPDModel.calibrate` call. It may evaluate case 844 only after proving from source documentation how core/bypass measurements map to `outer`/ `merged` streams and how model-scale frequency maps to the prediction basis. For a compatible case, calculate per-angle peak-normalized spectral-shape RMSE plus broadband angular levels normalized once at a declared reference angle. Otherwise produce `incompatible` with the missing proof named. Do not fit any parameter, compare absolute levels, or invoke the simple mixed-jet fallback.
  Parallelization: Wave 2 | Blocked by: 2 | Blocks: 4, 5
  References (executor has NO interview context - be exhaustive): `projects/pnmf/pnmf/physics.py` (`JetSource.spectrum_with_diagnostics`, `component_spectra_with_diagnostics`, `PhysicsNPDModel.calibrate`); `projects/pnmf/docs/memory/decisions.md`; NASA dataset page `https://data.nasa.gov/dataset/serdp09-mdoe-chevron-nozzle-noise-database`; archive Test Requirements Table 2 and page 12.
  Acceptance criteria (agent-executable): synthetic tests prove that insufficient mapping/frequency evidence returns `incompatible`, valid direct data uses no calibration path, and normalizations are performed in the declared order.
  QA scenarios (name the exact tool + invocation): `projects\\pnmf\\pnmf.ps1 test`; inspect the generated synthetic report for verdict, declared fixed parameters, metrics, and exclusions; Evidence `<attemptDir>/task-3-physics-reference-harness.md`.
  Commit: N | n/a

- [x] 4. Expose one explicit, CWD-independent validation command
  What to do / Must NOT do: Add `validate-serdp09 --data-root <absolute-path>` to `projects/pnmf/pnmf_cli.py` and dispatch it from `projects/pnmf/pnmf.ps1`, following the existing command/error style. Return a non-zero exit for missing/relative roots and incompatible reference conditions while still writing/printing the diagnostics location. Keep `validate-jet-reference` and every existing command unchanged; do not add UI/API endpoints or a default data-root.
  Parallelization: Wave 2 | Blocked by: 2, 3 | Blocks: 5
  References (executor has NO interview context - be exhaustive): `projects/pnmf/pnmf_cli.py`; `projects/pnmf/pnmf.ps1`; `projects/pnmf/README.md`; root `AGENTS.md` command routing rule.
  Acceptance criteria (agent-executable): command help documents the explicit root; missing/relative root fails safely; a synthetic compatible/incompatible invocation produces the expected exit code and report without CWD dependence.
  QA scenarios (name the exact tool + invocation): from repository root and a second temporary CWD, invoke `projects\\pnmf\\pnmf.ps1 validate-serdp09 --data-root <absolute-path>`; Evidence `<attemptDir>/task-4-physics-reference-harness.md`.
  Commit: N | n/a

- [x] 5. Run the real local case 844 and save an auditable screening report
  What to do / Must NOT do: Execute the new command against the supplied `tmp/SERDP09_MDOEchevron` archive. Select case 844 from `SERDP09_FF.db` and record the source hashes, record/condition fields, angle/band exclusions, fixed model inputs, compatibility result, and metric definitions. Preserve an honest `incompatible` result if source mapping or frequency basis cannot be proven; do not convert it into an implementation/calibration task.
  Parallelization: Wave 3 | Blocked by: 1, 2, 3, 4 | Blocks: final wave
  References (executor has NO interview context - be exhaustive): archive case `844_nb/844_nb.dat`; `SERDP09_FF.db` row for `icrdg=844`; task 3 evaluator contract; NASA source citation above.
  Acceptance criteria (agent-executable): real-data command completes without network access; an ignored report exists, is parseable JSON or CSV/text as designed, and contains provenance plus a `compatible` or `incompatible` verdict.
  QA scenarios (name the exact tool + invocation): `projects\\pnmf\\pnmf.ps1 validate-serdp09 --data-root C:\\Users\\efeko\\adp\\framework\\pnmf_project_2\\pnmf_project\\tmp\\SERDP09_MDOEchevron`; Evidence `<attemptDir>/task-5-physics-reference-harness.md`.
  Commit: N | n/a

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [ ] F1. Plan compliance audit
  Compare every changed path and command to the five todos; reject any undocumented data tracking, fitting, ET/RF, UI/API, or calibration change. Evidence: `<attemptDir>/final-F1-physics-reference-harness.md`.
- [ ] F2. Code quality review
  Review parser boundaries, error messages, absolute-path enforcement, dependency additions, and changed-file diagnostics. Evidence: `<attemptDir>/final-F2-physics-reference-harness.md`.
- [ ] F3. Real manual QA
  Run `projects\\pnmf\\pnmf.ps1 validate-serdp09 --data-root C:\\Users\\efeko\\adp\\framework\\pnmf_project_2\\pnmf_project\\tmp\\SERDP09_MDOEchevron`, inspect its emitted report, then repeat from a different CWD. Confirm the verdict is evidence-backed. Evidence: `<attemptDir>/final-F3-physics-reference-harness.md`.
- [ ] F4. Scope fidelity
  Confirm A320 frozen calibration, Doc-29/ET/RF behavior, database, UI/API, and existing validation commands are untouched; run `projects\\pnmf\\pnmf.ps1 test`. Evidence: `<attemptDir>/final-F4-physics-reference-harness.md`.

## Commit strategy
- Major completed phases may be committed and pushed to `origin/main` under the user's standing authorization.
- Before each push, verify the staged path set excludes raw NASA data, local SQLite databases, model artifacts, virtual environments, secrets, and unrelated dirty work.
- Keep the supplied archive and generated real-data report ignored. Never stage them automatically.

## Success criteria
- `validate-serdp09` is explicit-root, CWD-independent, local-only, and cannot silently turn invalid archive evidence into a prediction.
- The report names case 844 provenance and produces either valid shape/directivity screening metrics or a structured incompatibility that names the unproven mapping/frequency condition.
- The frozen physics calibration and learned/physics independence remain unchanged; focused synthetic tests and the existing PNMF test command pass.
