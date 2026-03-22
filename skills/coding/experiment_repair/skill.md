---
id: coding.experiment_repair
version: 1.0.0
phase: phase3
allowed_operators:
  - run_retry_repair
outputs:
  - repair_patch
  - retry_plan
capabilities:
  - deterministic_run_repair
  - harness_patch_revision
risk_level: medium
---

Applies a bounded repair pass for failed experiment runs caused by harness or runtime issues.
