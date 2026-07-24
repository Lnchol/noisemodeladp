# Context

- Active application: `projects/pnmf`.
- Runtime: Python 3 local venv at `projects/pnmf/.venv`; never use the unrelated
  `python` on PATH.
- Canonical raw corpus: EASA ANP legacy v2.3 plus v6.3 CSV supplement under
  `projects/pnmf/03_data`; canonical runtime file is the rebuilt local SQLite.
- Supported learned models: exactly `et` (default) and `rf`.
- Independent physics route: `PhysicsNPDModel`, SEL/LAmax only, with explicit
  BPR/component inputs and frozen A320-211 calibration.
- Backup for the pre-migration tree:
  `C:\Users\efeko\adp\framework\pnmf_project_2\pnmf_project_backup_20260724_114903`.
