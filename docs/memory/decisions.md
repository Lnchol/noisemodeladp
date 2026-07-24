# Decisions

- EFES stays the repository/governance root; PNMF is a cohesive
  `projects/pnmf` subtree.
- The legacy v2.3 corpus remains the base and v6.3 is an explicit supplement.
- Source collisions use declared table-specific business keys with v6.3
  winning; both `7773ER` aircraft records are retained because they reference
  different NPD sets.
- Every canonical truth row carries `source_dataset` and `source_file`.
- Supported learned models are exactly Extra Trees (`et`, default) and Random
  Forest (`rf`); evolve/champion and historical regressors are retired from the
  public workflow.
- `PhysicsNPDModel` is not a regression learner; it remains an independent
  component-source SEL/LAmax cross-check.
