---
id: literature.shortlist_critique
version: 0.1.0
phase: literature
allowed_operators:
  - shortlist_rank
preferred_models:
  - triage
context_inputs:
  - research_charter
  - screened_papers
outputs:
  - critique_notes
capabilities:
  - source.read_metadata
risk_level: low
---

# Shortlist Critique

## Purpose
Critique and validate the shortlist ranking before proceeding to escalation.

## When to use
Use after title+abstract screening and before deeper reading decisions.

## Required behavior
- Review the top-ranked papers for relevance to the charter
- Flag potential redundancy between shortlisted papers
- Identify gaps in coverage that the shortlist may miss
- Propose re-ranking if the default score-based ranking seems wrong
