---
id: ideation.experiment_planning
version: "0.1.0"
phase: ideation
allowed_operators:
  - protocol_compile
preferred_models:
  - protocol_drafting
context_inputs:
  - hypothesis_cards
  - research_charter
outputs:
  - experiment_specs
capabilities: []
risk_level: low
trust_tier_required: first_party_trusted
---

# Experiment Planning Guidance

## Purpose

Guide the compilation of hypotheses into fully executable experiment specifications with baselines, controls, metrics, and runnable code.

## Baseline Definition

- Every spec must define a baseline: what does success look like without the hypothesis?
- Include expected metric values from prior work or reasonable estimates
- Reference existing results when available

## Metric Specification

- Define at least one primary metric with direction (maximize/minimize)
- Set thresholds when possible — makes verification deterministic
- Include secondary metrics for monitoring (training loss, convergence speed)

## Code Generation

- Write complete, self-contained Python scripts
- Output metrics to /artifacts/metrics.json as `{metric_name: numeric_value}`
- Include requirements.txt or pip install commands
- Use standard ML libraries (PyTorch, numpy, scikit-learn)
- Handle edge cases: missing data, convergence failure, OOM fallback

## Stop Conditions

- Define at least one stop condition (max epochs, target metric, timeout)
- Prefer early stopping over fixed epoch counts
