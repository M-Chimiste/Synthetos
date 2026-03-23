# verification.postmortem_reflection

## Manifest

- **ID:** verification.postmortem_reflection
- **Version:** 1.0.0
- **Phase:** phase4
- **Risk Level:** low
- **Allowed Operators:** failure_postmortem, verification_report
- **Outputs:** retrieval_hints, protocol_update_hints
- **Capabilities:** failure_pattern_matching, remediation_suggestion
- **Valid:** Yes

## Validation Issues

- **warning:** Phase 'phase4' is not in known phases: ['coding', 'execution', 'ideation', 'literature', 'planning', 'reporting', 'verification']

## Documentation

# Postmortem Reflection

## Purpose

Analyze failed or rejected experiment runs to identify root causes, suggest remediations, and generate hints for literature re-search and protocol revision.

## When to use

Use after a run has been verified and the outcome is rejected, invalid, or the run failed during execution.

## Required behavior

- Identify the most likely root cause from available evidence (stderr, exit code, metrics, verification checks)
- Compare against similar prior failures in the same cycle
- Generate actionable remediation suggestions categorized by type
- Produce retrieval hints that could help address the failure through literature
- Suggest protocol updates to prevent similar failures
