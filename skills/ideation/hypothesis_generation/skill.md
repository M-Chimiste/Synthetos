---
id: ideation.hypothesis_generation
version: "0.1.0"
phase: ideation
allowed_operators:
  - hypothesis_generate
  - hypothesis_critique
preferred_models:
  - hypothesis_generation
context_inputs:
  - evidence_cards
  - research_charter
outputs:
  - hypothesis_cards
capabilities: []
risk_level: low
trust_tier_required: first_party_trusted
---

# Hypothesis Generation Guidance

## Purpose

Guide the hypothesis generation and critique process to produce novel, testable, evidence-grounded hypotheses from the evidence extracted in Phase 2.

## Generation Behavior

When generating hypotheses:

- Ground each hypothesis in specific evidence cards — cite evidence IDs
- Prefer hypotheses that combine multiple evidence sources
- Ensure each hypothesis is falsifiable and testable with standard ML methods
- Include a proposed mechanism explaining *why* the hypothesis might hold
- Consider both confirmatory and exploratory hypotheses

## Critique Behavior

When critiquing hypotheses:

- Evaluate novelty relative to the evidence base — is this insight non-obvious?
- Assess feasibility given typical ML lab constraints (GPU hours, dataset availability)
- Rate impact on the research problem — would confirmation meaningfully advance understanding?
- Identify concrete failure modes — what would falsify this hypothesis?
- Flag hypotheses that are too vague to compile into an experiment
