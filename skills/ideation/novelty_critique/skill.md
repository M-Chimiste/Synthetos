---
id: ideation.novelty_critique
version: 0.1.0
phase: ideation
allowed_operators:
  - hypothesis_critique
preferred_models:
  - critic
context_inputs:
  - hypothesis_card
  - evidence_cards
  - research_charter
outputs:
  - critique_scores
  - critique_issues
capabilities:
  - source.read_metadata
risk_level: low
---

# Novelty Critique

## Purpose
Evaluate hypotheses for novelty, feasibility, and impact.

## When to use
Use after hypothesis generation to assess quality before protocol drafting.

## Required behavior
- Score each hypothesis on novelty, feasibility, and expected impact
- Identify overlap with existing published work
- Flag hypotheses that lack sufficient evidence support
- Recommend whether each hypothesis should proceed to protocol drafting
