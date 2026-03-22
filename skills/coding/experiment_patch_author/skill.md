---
id: coding.experiment_patch_author
version: 1.0.0
phase: phase3
allowed_operators:
  - run_prepare
outputs:
  - workspace_patch
  - run_config
capabilities:
  - deterministic_patch_authoring
  - execution_harness_staging
risk_level: low
---

Produces a deterministic execution patch and run configuration for the Phase 3 offline benchmark harness.
