---
skill_id: analysis.reproducibility_checklist
version: "0.1"
phase: analysis
trust_tier: first_party_trusted
allowed_operators:
  - analysis_review
description: Reproducibility assessment checklist for research papers
---

# Reproducibility Checklist

## Data availability

- [ ] Are datasets named and cited?
- [ ] Are datasets publicly available?
- [ ] Is the data split strategy described?
- [ ] Are preprocessing steps documented?

## Code and implementation

- [ ] Is code publicly released?
- [ ] Are dependencies and versions specified?
- [ ] Are random seeds reported?
- [ ] Is the training procedure described in sufficient detail?

## Compute requirements

- [ ] Is hardware described (GPU model, count, memory)?
- [ ] Is training time reported?
- [ ] Is inference cost discussed?

## Experimental rigor

- [ ] Are experiments repeated with different seeds?
- [ ] Are confidence intervals or standard deviations reported?
- [ ] Are ablation studies included?
- [ ] Are hyperparameter sensitivity analyses provided?
