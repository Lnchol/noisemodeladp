# Codex workspace rules

The active application is `projects/pnmf`. Before changing it, read
`docs/memory/{context,progress,decisions}.md` and its scoped `AGENTS.md`.
Repository language is English.

## Workflow

Use subagents only when independent, bounded work makes them materially
useful. Do not delegate trivial work or tightly sequential steps. When useful,
route reconnaissance to `code-explorer`, implementation to
`fast-task-executor` or `hard-task-specialist`, and independent validation to
`validation-runner`.

Keep ownership explicit, report concise evidence summaries rather than raw
logs, and do not overwrite unrelated work. Add tests and validation evidence
for behavior changes. Do not commit or push unless asked.

## PNMF routing and safety

- Use `projects/pnmf/.venv/Scripts/python.exe`, never an unrelated Python.
- Keep commands and entry points independent of caller CWD.
- Preserve learned/physics independence, Doc-29 interpolation, frozen physics
  calibration, units, provenance, and truth/prediction table separation.
- Treat PNMF output as conceptual screening, not certification.
- Never stage secrets, raw data, local SQLite databases, model artifacts,
  virtual environments, or regenerated outputs.

Run PNMF tasks from the repository root with
`projects\pnmf\pnmf.ps1 <task>`, or use the exact commands in `README.md`.
