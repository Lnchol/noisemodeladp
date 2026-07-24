# Progress

## 2026-07-24 — PNMF adopted into EFES

- Preserved the original PNMF tree in a timestamped sibling backup.
- Retained EFES `main` history and placed the cohesive application under
  `projects/pnmf`.
- Integrated raw v2.3 + v6.3 sources with deterministic merge keys,
  provenance columns, integrity gates, and an embedded dataset manifest.
- Narrowed the supported learned-model surface to Extra Trees and Random Forest;
  retained component physics as an independent workflow.
- Made CLI, UI, tests, and PowerShell runner independent of caller CWD.
- Next: validation lane runs full pytest plus CLI validation/physics/demo.
