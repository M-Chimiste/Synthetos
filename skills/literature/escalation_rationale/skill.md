---
id: literature.escalation_rationale
version: 0.1.0
phase: literature
allowed_operators:
  - fulltext_escalation
preferred_models:
  - triage
context_inputs:
  - research_charter
  - shortlisted_papers
outputs:
  - escalation_rationale
capabilities:
  - source.read_metadata
  - source.request_fulltext
risk_level: low
---

# Escalation Rationale Drafting

## Purpose
Provide clear, documented reasons for escalating papers from metadata-only to full-text reading.

## When to use
Use when deciding which shortlisted papers require full text access.

## Required behavior
- Justify each full-text fetch with a concrete reason tied to the research problem
- Prefer HTML or machine-readable full text over PDF
- Record the reason so it appears in the literature screening report
- Respect budget limits on the number of deeper reads
