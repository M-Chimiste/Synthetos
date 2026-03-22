---
id: ideation.protocol_drafting
version: 0.1.0
phase: ideation
allowed_operators:
  - protocol_compilation
preferred_models:
  - protocol_drafter
context_inputs:
  - hypothesis_card
  - evidence_cards
  - research_charter
outputs:
  - experiment_spec
capabilities:
  - source.read_metadata
risk_level: low
---

# Protocol Drafting

## Purpose
Compile approved hypotheses into executable experiment protocols.

## When to use
Use after hypotheses have passed novelty critique and are approved for experimentation.

## Required behavior
- Translate each approved hypothesis into a concrete experiment specification
- Define datasets, metrics, baselines, and success criteria
- Specify resource requirements and execution constraints
- Ensure the protocol is self-contained and reproducible
