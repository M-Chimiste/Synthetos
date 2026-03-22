---
id: literature.title_abstract_triage
version: 0.1.0
phase: literature
allowed_operators:
  - literature_screen
outputs:
  - screening_decisions
capabilities:
  - source.read_metadata
  - source.request_fulltext
risk_level: low
---

# Title and Abstract Triage

## Purpose
Screen title and abstract together before any deeper paper read.

## When to use
Use after metadata retrieval and before escalation to HTML or PDF content.

## Required behavior
- Consider title and abstract jointly.
- Produce shortlist rationale for any promoted item.
- Escalate to deeper reads only when a clear reason exists.

