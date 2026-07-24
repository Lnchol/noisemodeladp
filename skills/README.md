# Skills

This is the canonical collection of reusable Codex skills. Each folder contains
a `SKILL.md` with YAML frontmatter and may include scripts or references. Codex
loads a skill's full body only when it is relevant.

## Layout

```
skills/
  _template/SKILL.md     # copy this to start a new skill
  <skill-name>/SKILL.md  # one folder per skill (+ optional scripts/, refs/)
```

## Built-in (general, project-agnostic)

These ship with the Efes skeleton and apply to any project:

- **`wrap-session`** — the end-of-session ritual: update the memory bank, run the
  Definition of Done. The rot-guard for the vibe lane.
- **`write-adr`** — scaffold a numbered ADR from the template.
- **`review-own-diff`** — self-review a change against the Definition of Done
  before declaring it done.
- **`clean-code`** — general code-quality rules (small single-responsibility
  files, naming, error handling, "why" comments, no god classes).
- **`write-tests`** — drive a change with tests: turn acceptance criteria into a
  failing test first, pin behavior/contracts, keep the suite green.
- **`ponytail`** — minimal-code discipline (vendored from
  [upstream](https://github.com/DietrichGebert/ponytail), MIT): the "does this
  need to exist" ladder — YAGNI → reuse → stdlib → native → installed dep →
  one line → minimum code. Governs *how much* code exists; `clean-code` governs
  its shape.
- **`caveman`** — terse chat output (vendored from
  [upstream](https://github.com/JuliusBrussee/caveman), MIT): drops filler,
  pleasantries, and hedging from responses (~65% fewer output tokens);
  technical content stays exact. Conversation only — never repo files.
- **`spec-feature`** — scaffold a feature spec from the template before
  writing code.
- **`provider-audit`** — check external vendors sit behind an adapter, not
  called directly from domain code.
- **`module-boundary-check`** — check domains don't import each other
  directly and shared contracts live in one place.
- **`commit-msg`** — format/validate a commit message against the chosen
  convention, only once a commit has been explicitly asked for.
- **`specialize-agents`** — refresh the four Codex role files with the
  project's real paths, commands, and constraints.

## Codex use

Keep skill content here rather than duplicating it under `.codex`. Update the
collection when repository conventions change.

## Project-specific (added after the interview)

Once the stack and project type are known, the agent should **research and add
skills that fit this project** — from public skill registries or the web — as
new folders here (e.g. a framework's conventions, a testing approach, an API
client pattern). Keep each skill small, single-purpose, and in the repo language.

> Adding a non-trivial skill is a decision: note it in `docs/memory/decisions.md`
> (and an ADR if it changes how the project is built).
