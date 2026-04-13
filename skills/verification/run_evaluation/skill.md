---
id: verification.run_evaluation
version: "0.1.0"
phase: verification
allowed_operators:
  - verification_check
  - verification_postmortem
preferred_models:
  - evaluation
context_inputs:
  - run_record
  - verification_report
outputs:
  - failure_postmortem
capabilities: []
risk_level: low
trust_tier_required: first_party_trusted
---

# Run Evaluation Guidance

## Purpose

Guide the evaluation of experiment results and generation of structured failure postmortems.

## Verification Checks

- Compare all reported metrics against spec-defined thresholds
- Verify artifact presence and completeness
- Flag NaN, inf, or unreasonable metric magnitudes
- Consider both absolute thresholds and relative improvement over baseline

## Failure Classification

- **dependency**: missing packages, import errors, file not found
- **oom**: out of memory, killed by OOM, exit code 137
- **timeout**: exceeded configured time limit
- **runtime**: unhandled exceptions, assertion errors
- **metric_parse**: metrics.json missing, corrupt, or invalid values

## Postmortem Analysis

- Identify root cause from error trace, not just symptoms
- Distinguish mechanical failures (fixable by retry/config) from scientific failures
- Recommend concrete next steps: fix dependency, increase memory, adjust hyperparameters
- Record lessons that could inform future experiments
