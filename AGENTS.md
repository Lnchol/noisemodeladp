# Codex workspace rules

The active application is `projects/pnmf`. Before changing it, read
`docs/memory/{context,progress,decisions}.md` and its scoped `AGENTS.md`.
Repository language is English.

## Workflow

Use the Codex roles in `.codex/agents`:

1. `code-explorer` locates relevant code and constraints without editing.
2. `fast-task-executor` handles routine, bounded work; use
   `hard-task-specialist` for deep debugging or architectural/model changes.
3. `validation-runner` independently runs the applicable checks without edits.

Keep ownership explicit and do not overwrite unrelated work. Add tests and
validation evidence for behavior changes. Do not commit or push unless asked.

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
