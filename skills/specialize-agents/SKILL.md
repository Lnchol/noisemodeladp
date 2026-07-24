---
name: specialize-agents
description: Refresh the four .codex/agents role files with this project's paths, commands, constraints, and complexity heuristic when their orientation is stale.
---

# Specialize the agent roster

## When to use

Use whenever project structure drifts enough that `code-explorer`,
`fast-task-executor`, `hard-task-specialist`, or `validation-runner` has stale
assumptions about entry points, constraints, or test commands.

## Steps

1. Read the current project-orientation block in each `.codex/agents/*.toml`.
2. Gather what changed: key entry points, the real
   test/lint/typecheck/build commands, a concrete example of "fast" vs
   "hard" work for this project.
3. Update all four `.codex/agents/*.toml` files together.
4. Note the refresh in `docs/memory/progress.md` if it's a meaningful
   update, not for trivial wording tweaks.

## Notes

A generic or stale orientation block is unfinished. Keep the refresh
repeatable and record only durable project facts.
