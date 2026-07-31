# Task 1: Narrow SERDP archive ignore rule

Date: 2026-07-31

## Baseline (before edit)

```powershell
PS> git check-ignore -v tmp/SERDP09_MDOEchevron/SERDP09acousticEscort.xlsx
PS> $LASTEXITCODE
1
PS> git status --short -- tmp/SERDP09_MDOEchevron
?? tmp/SERDP09_MDOEchevron/
```

The workbook was not ignored before the change (no `check-ignore` output and exit code 1); the archive was untracked.

## Change

Added exactly this narrow `.gitignore` rule:

```gitignore
tmp/SERDP09_MDOEchevron/
```

No broad `tmp/` ignore was added.

## RED/GREEN and manual QA

```powershell
PS> git check-ignore -v tmp/SERDP09_MDOEchevron/SERDP09acousticEscort.xlsx
.gitignore:50:tmp/SERDP09_MDOEchevron/ tmp/SERDP09_MDOEchevron/SERDP09acousticEscort.xlsx
PS> $LASTEXITCODE
0
PS> git check-ignore -v tmp/SERDP09_MDOEchevron/844_nb/844_nb.dat
.gitignore:50:tmp/SERDP09_MDOEchevron/ tmp/SERDP09_MDOEchevron/844_nb/844_nb.dat
PS> $LASTEXITCODE
0
PS> git status --short -- tmp/SERDP09_MDOEchevron
PS>
```

Manual QA used the required PowerShell invocation for the workbook. PASS: output identifies the new, narrow `.gitignore` rule. Both the workbook and DAT path resolve to that same rule; the archive status is empty.

## Owned-path and dirty-worktree verification

```powershell
PS> git diff --name-only -- .gitignore
.gitignore
PS> git status --short -- .gitignore .omo/evidence/task-1-physics-reference-harness.md
 M .gitignore
?? .omo/evidence/task-1-physics-reference-harness.md
```

`git status --short` was also recorded before and after the change; it contained pre-existing unrelated work across `.codex/`, documentation, and `projects/pnmf/`. The archive itself was the only relevant untracked input before the rule and has no status entries after it. The only owned modifications are the one-line `.gitignore` rule and this evidence file.

Final `git status --short` receipt:

```text
 M .codex/config.toml
 M .gitignore
 M README.md
 M projects/pnmf/HOW_TO_USE.txt
 M projects/pnmf/README.md
 D projects/pnmf/docs/FINAL_REPORT.md
 D projects/pnmf/docs/GAP_ANALYSIS_REPORT.md
 M projects/pnmf/docs/HOW_IT_WORKS.md
 M projects/pnmf/docs/MIGRATION_PROGRESS_REPORT.md
 M projects/pnmf/docs/MODEL_ARCHITECTURE_REPORT.md
 M projects/pnmf/docs/MODEL_TRAINING_REPORT.md
 M projects/pnmf/docs/NPD_SYSTEM_DESIGN.md
 M projects/pnmf/docs/PROJECT_UNDERSTANDING.md
 D projects/pnmf/docs/academic_paper.md
 M projects/pnmf/pnmf.ps1
 M projects/pnmf/pnmf/__init__.py
 M projects/pnmf/pnmf/api.py
 M projects/pnmf/pnmf/physics.py
 M projects/pnmf/pnmf_cli.py
 M projects/pnmf/pnmf_ui.py
 M projects/pnmf/tests/test_physics.py
 M projects/pnmf/tests/test_ui.py
?? .omo/
?? projects/pnmf-framework/
?? projects/pnmf-frameworkv5.zip
?? projects/pnmf/Launch_PNMF.cmd
?? projects/pnmf/docs/ADVISOR_PRESENTATION_TEXT.md
?? projects/pnmf/docs/PHYSICAL_MODEL_IMPROVEMENT_RESEARCH.md
?? projects/pnmf/docs/PHYSICS_PRESETS.md
?? projects/pnmf/docs/PNMF_COMPONENT_PHYSICS_TECHNICAL_PAPER.pdf
?? "projects/pnmf/docs/Research papers and ECAC document/"
?? projects/pnmf/pnmf/physics_presets.py
?? projects/pnmf/tests/test_api_power_settings.py
?? projects/pnmf/tests/test_physics_presets.py
?? projects/pnmf/tools/export_framework_zip.ps1
```

## UltraQA and cleanup

- Malformed input, prompt injection, cancel/resume, hung command, flaky test, repeated interruptions: N/A; this is one static Git ignore rule with no parser, process, or interactive operation.
- Stale state: passed by rerunning `git check-ignore -v` after the edit for both paths.
- Dirty worktree: baseline status contained unrelated user changes; owned-path verification after the edit lists only `.gitignore` and this evidence file.
- Misleading output: passed by checking both the workbook and DAT paths and confirming the exact same narrow rule.
- Cleanup receipt: no processes, temporary directories, or browser resources were created.
