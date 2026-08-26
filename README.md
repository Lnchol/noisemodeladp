# PNMF Codex workspace

The application is [`projects/pnmf`](projects/pnmf/README.md). Root
`AGENTS.md` routes Codex work; `projects/pnmf/AGENTS.md` defines the modeling
invariants.

## Windows launch and checks

For the fastest start, double-click:

`projects\pnmf\Launch_PNMF.cmd`

It creates the private virtual environment, installs dependencies when needed,
launches Streamlit, and opens PNMF in the browser. The PowerShell equivalent is
`projects\pnmf\pnmf.ps1`; task commands such as
`projects\pnmf\pnmf.ps1 test` bootstrap the environment automatically too.

Raw ANP sources in `projects/pnmf/03_data`, the rebuilt SQLite datastore,
trained model files, `.venv`, and generated `outputs` are local/ignored
artifacts. Do not stage them. The source tree and tests remain reproducible
without committing those files.

Hosted GitHub CI therefore runs only compilation/import checks and the
data-independent synthetic `tests/test_ci_smoke.py` selection. The full local
suite and Jet validation require the ignored ANP corpus/datastore; their
current evidence is [JET_MODEL_METHODOLOGY_AND_VALIDATION_REPORT](docs/JET_MODEL_METHODOLOGY_AND_VALIDATION_REPORT.md).

## Codex workflow

Use `.codex/agents` for independent bounded work when delegation is materially
useful: read-only reconnaissance, appropriate implementation, then independent
read-only validation. Keep PNMF changes within the scoped project rules; Codex
must not commit or push unless explicitly asked.

## Project reports

- [Project understanding](projects/pnmf/docs/PROJECT_UNDERSTANDING.md)
- [System design](projects/pnmf/docs/NPD_SYSTEM_DESIGN.md)
- [Model architecture](projects/pnmf/docs/MODEL_ARCHITECTURE_REPORT.md)
- [Component-physics technical paper](projects/pnmf/docs/PNMF_COMPONENT_PHYSICS_TECHNICAL_PAPER.pdf)
- [Current Jet methodology and validation](docs/JET_MODEL_METHODOLOGY_AND_VALIDATION_REPORT.md)
- [EASA and ECAC source ledger](docs/EASA_ECAC_SOURCE_LEDGER.md)
- [Jet reference validation](projects/pnmf/docs/JET_REFERENCE_VALIDATION_REPORT.md)
- [Migration progress](projects/pnmf/docs/MIGRATION_PROGRESS_REPORT.md)
- [Abbreviations and glossary](projects/pnmf/docs/ABBREVIATIONS.md)
- [Release notes: noiseframeworkv1](projects/pnmf/docs/releases/noiseframeworkv1.md)
