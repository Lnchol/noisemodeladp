# Codex session protocol

This is the active handoff protocol. Architecture ADRs and changelogs are
historical records, not onboarding instructions.

## Start of session

1. Read `AGENTS.md` (rules, stack, repo map).
2. Read `docs/memory/context.md` — current working state and tribal knowledge.
3. Read `docs/memory/progress.md` — what's done / in progress / next.
4. Read `docs/memory/decisions.md` — the "why" log.
5. Read `projects/pnmf/AGENTS.md` before changing PNMF.
6. Restate the immediate goal before touching anything.

## During the session

- Use the Codex pipeline: explore → fast/hard implementation → validation.
- Open an ADR the moment an architecture/tech decision is made.
- Keep changes inside module boundaries; don't break contracts.
- Keep `AGENTS.md` stable; session state belongs in the memory bank.

## End of session

1. Update `docs/memory/progress.md` — newest entry on top, dated, with the
   **Next step** clearly stated.
2. **Rotate `progress.md` when it grows:** past ~10 entries, move all but the
   newest 5 to `docs/memory/progress-archive.md` (same format, append at top).
   The archive is history; only `progress.md` is read every session.
3. Update `docs/memory/context.md` if the working state or open questions changed.
4. Append to `docs/memory/decisions.md` if a decision was locked (link the ADR).
5. Update `README.md` only when active onboarding, commands, or report links
   change.
6. Run the Definition of Done gate for anything you're calling complete.
7. Do not commit or push unless the user asked.
