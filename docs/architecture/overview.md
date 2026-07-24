# Architecture overview

EFES provides repository governance. PNMF is isolated at `projects/pnmf`.

Raw ANP v2.3 + v6.3 CSVs → deterministic merge and manifest → SQLite truth
tables → ET/RF training → NPD prediction → independent component-physics
SEL/LAmax comparison → QA gate → separate prediction tables.

The learned route (`pnmf/models.py`) and physics route (`pnmf/physics.py`) share
only final outputs for comparison. Doc-29 interpolation remains centralized in
`pnmf/core.py`.
