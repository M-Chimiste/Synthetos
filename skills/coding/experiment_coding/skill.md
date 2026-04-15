---
id: coding.experiment_coding
version: "0.1.0"
phase: execution
allowed_operators:
  - execution_setup
  - execution_run
preferred_models:
  - coding
context_inputs:
  - experiment_spec
outputs:
  - run_artifacts
capabilities: []
risk_level: low
trust_tier_required: first_party_trusted
---

# Experiment Coding Guidance

## Purpose

Guide code structure and execution conventions for experiment runs inside containers.

## Code Structure

- Entry point script at the workspace root (e.g., `run_experiment.py`)
- Separate model definition from training loop
- Use deterministic seeds for reproducibility
- Log progress to stdout for telemetry capture

## Metric Reporting

- Write final metrics to `/artifacts/metrics.json`
- Format: flat JSON object `{"metric_name": numeric_value}`
- Report all metrics defined in the experiment spec
- Ensure numeric values are finite (no NaN, no inf)

## Artifact Output

- Write all artifacts to `/artifacts/`
- Include model checkpoints, plots, and logs as specified in the experiment spec
- Use consistent naming matching `expected_artifacts` in the spec
