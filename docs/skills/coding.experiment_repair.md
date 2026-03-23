# coding.experiment_repair

## Manifest

- **ID:** coding.experiment_repair
- **Version:** 1.0.0
- **Phase:** phase3
- **Risk Level:** medium
- **Allowed Operators:** run_retry_repair
- **Outputs:** repair_patch, retry_plan
- **Capabilities:** deterministic_run_repair, harness_patch_revision
- **Valid:** Yes

## Validation Issues

- **warning:** Phase 'phase3' is not in known phases: ['coding', 'execution', 'ideation', 'literature', 'planning', 'reporting', 'verification']

## Documentation

Applies a bounded repair pass for failed experiment runs caused by harness or runtime issues.
