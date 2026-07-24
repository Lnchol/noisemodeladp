# PNMF scoped engineering rules

Project root is this directory (`projects/pnmf`). Use
`.venv\Scripts\python.exe`; never `python` from PATH.

## Invariants

- Learned prediction (`pnmf/models.py`) and component physics
  (`pnmf/physics.py`) are independent routes. Never couple their fitting.
- Supported learned models are exactly Extra Trees (`et`, default) and Random
  Forest (`rf`).
- `PhysicsNPDModel` is a separate component-spec workflow, not the historical
  regression `SemiEmpiricalNPDModel`. It supports SEL/LAmax only and requires
  explicit BPR/component assumptions.
- Physics uses metres/newtons; ANP/NPD uses feet/lbf. Conversion occurs only at
  the physics model boundary.
- Do not alter `core.py` Doc-29 interpolation or frozen A320-211 physics
  calibration incidentally.
- Predicted NPD rows remain monotone non-increasing with distance.
- `models.power_features()` is the mixed-power-unit correction point.
- Truth (`anp_*`), predictions (`predicted_*`), and legacy trial tables remain
  strictly separate.

## Data

`pnmf_cli.py datastore` combines:

- `03_data/EASA_ANP_LEGACY_database_v2.3` (semicolon CSV);
- `03_data/EASA_ANP_database_v6.3` (comma CSV supplement).

Every truth row carries source provenance. v6.3 is required by default and a
missing/empty supplement is a hard `DataSourceError`. Inspect with
`pnmf_cli.py manifest`.

## Commands

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe pnmf_cli.py datastore
.venv\Scripts\python.exe pnmf_cli.py manifest
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe pnmf_cli.py compare
.venv\Scripts\python.exe pnmf_cli.py physics
```

All entry points are caller-CWD independent.
