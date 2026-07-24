# PNMF Codex workspace

The application is [`projects/pnmf`](projects/pnmf/README.md). Root
`AGENTS.md` routes Codex work; `projects/pnmf/AGENTS.md` defines the modeling
invariants.

## Windows setup and checks

Run from the repository root:

```powershell
py -3 -m venv projects\pnmf\.venv
projects\pnmf\.venv\Scripts\python.exe -m pip install -r projects\pnmf\requirements.txt
projects\pnmf\.venv\Scripts\python.exe projects\pnmf\pnmf_cli.py datastore
projects\pnmf\.venv\Scripts\python.exe projects\pnmf\pnmf_cli.py manifest
projects\pnmf\.venv\Scripts\python.exe -m pytest projects\pnmf\tests -q
projects\pnmf\.venv\Scripts\python.exe projects\pnmf\pnmf_cli.py validate-model --folds 3
projects\pnmf\.venv\Scripts\python.exe projects\pnmf\pnmf_cli.py compare
projects\pnmf\.venv\Scripts\python.exe projects\pnmf\pnmf_cli.py physics
```

`projects\pnmf\pnmf.ps1 <task>` is the caller-CWD-independent task runner.

Raw ANP sources in `projects/pnmf/03_data`, the rebuilt SQLite datastore,
trained model files, `.venv`, and generated `outputs` are local/ignored
artifacts. Do not stage them. The source tree and tests remain reproducible
without committing those files.

Hosted GitHub CI therefore runs only compilation/import checks and the
data-independent synthetic `tests/test_ci_smoke.py` selection. The full local
suite and `validate-model` require the ignored ANP corpus/datastore; their
current evidence is [MODEL_TRAINING_REPORT](projects/pnmf/docs/MODEL_TRAINING_REPORT.md).

## Codex workflow

Use `.codex/agents` in order: read-only `code-explorer`, then the routine
`fast-task-executor` or complex `hard-task-specialist`, then read-only
`validation-runner`. Keep PNMF changes within the scoped project rules; Codex
must not commit or push unless explicitly asked.

## Project reports

- [Project understanding](projects/pnmf/docs/PROJECT_UNDERSTANDING.md)
- [System design](projects/pnmf/docs/NPD_SYSTEM_DESIGN.md)
- [Model architecture](projects/pnmf/docs/MODEL_ARCHITECTURE_REPORT.md)
- [Academic paper](projects/pnmf/docs/academic_paper.md)
- [Final report](projects/pnmf/docs/FINAL_REPORT.md)
- [Migration progress](projects/pnmf/docs/MIGRATION_PROGRESS_REPORT.md)
- [Abbreviations and glossary](projects/pnmf/docs/ABBREVIATIONS.md)
