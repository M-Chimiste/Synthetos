---
id: verification.postmortem_reflection
version: 1.0.0
phase: phase4
allowed_operators:
  - failure_postmortem
  - verification_report
outputs:
  - retrieval_hints
  - protocol_update_hints
capabilities:
  - failure_pattern_matching
  - remediation_suggestion
risk_level: low
---

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
