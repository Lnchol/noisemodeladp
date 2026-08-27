# PNMF workspace governance

Apply this rule to work in this repository.

Before changing the active application, read `AGENTS.md`,
`projects/pnmf/AGENTS.md`, and `docs/memory/context.md`, `progress.md`, and
`decisions.md`. The active application is `projects/pnmf`; repository language
is English.

Preserve these boundaries:

- Use `projects/pnmf/.venv/Scripts/python.exe`, never PATH Python.
- Keep learned Extra Trees/Random Forest prediction independent from
  `PhysicsNPDModel`.
- Preserve Doc-29 interpolation, frozen A320-211 physics calibration, units,
  provenance, monotone NPD rows, and truth/prediction table separation.
- Treat physics as SEL/LAmax conceptual screening, not certification.
- Preserve unrelated work. Do not commit, push, or edit `.claude/**` or
  `.codex/**` unless the user explicitly asks.

Run PNMF tasks from the repository root with
`projects\pnmf\pnmf.ps1 <task>` or the exact commands in the scoped README.
For a behavior change, add focused evidence, run the narrowest applicable
check, then run the relevant validation lane. Report exact commands and
results, including anything that remains unverified.

Use PNMF subagents only when work is independent and bounded: reconnaissance
before implementation, one explicit implementation owner, and independent
validation after the change.
