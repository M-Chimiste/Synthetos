---
id: verification.verification_summary
version: 1.0.0
phase: phase4
allowed_operators:
  - run_verify
  - verification_report
outputs:
  - verification_summary
  - next_step_recommendations
capabilities:
  - outcome_summarization
  - historical_comparison_review
risk_level: low
---

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
