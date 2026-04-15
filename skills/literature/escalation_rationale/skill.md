---
id: literature.escalation_rationale
version: 0.1.0
phase: discovery
allowed_operators: [discovery_analyze, discovery_finalize]
preferred_models: [metadata_analysis]
context_inputs:
  - paper_title
  - paper_abstract
  - problem_profile
outputs:
  - escalation_rationale
capabilities: []
risk_level: low
trust_tier_required: first_party_trusted
---

# Escalation rationale

## Purpose

Reusable guidance for writing the ``escalation_rationale`` field of a
metadata-analysis packet.

## Behavior

Asks the model to answer one focused question per paper:

> If we paid the full-text-fetch cost on this paper, what specific question
> would the deeper read have to answer to be worth the cost?

When the model cannot articulate that question, the rationale should
recommend *not* escalating.

## When to use

Used by both the analyze step and the finalize step. The finalize step uses
the same prompt to grade existing rationales when revisiting the shortlist.
