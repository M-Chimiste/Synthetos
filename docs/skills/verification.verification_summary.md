# verification.verification_summary

## Manifest

- **ID:** verification.verification_summary
- **Version:** 1.0.0
- **Phase:** phase4
- **Risk Level:** low
- **Allowed Operators:** run_verify, verification_report
- **Outputs:** verification_summary, next_step_recommendations
- **Capabilities:** outcome_summarization, historical_comparison_review
- **Valid:** Yes

## Validation Issues

- **warning:** Phase 'phase4' is not in known phases: ['coding', 'execution', 'ideation', 'literature', 'planning', 'reporting', 'verification']

## Documentation

# Verification Summary

## Purpose

Summarize verification outcomes for experiment runs, including baseline comparison, historical comparison, and overall assessment of result quality.

## When to use

Use during or after verification to produce human-readable summaries of verification check results and to generate next-step recommendations.

## Required behavior

- Summarize deterministic verification check results clearly
- Indicate whether the result is robust, tentative, or rejected with supporting evidence
- Reference baseline and historical comparisons
- Suggest next steps based on the verification outcome
