---
id: literature.title_abstract_triage
version: 0.1.0
phase: discovery
allowed_operators: [discovery_analyze]
preferred_models: [metadata_analysis]
context_inputs:
  - paper_title
  - paper_abstract
  - problem_profile
outputs:
  - metadata_analysis_packet
capabilities: []
risk_level: low
trust_tier_required: first_party_trusted
---

# Title and abstract triage

## Purpose

Tighten the metadata-depth analysis prompt used by ``discovery_analyze`` so
the model focuses on what matters: contribution type, method family, and
shortlist fit.

## Behavior

When attached to the analyze operator, this skill prepends the following
guidance to the system prompt:

- Read title + abstract together; do not infer beyond what is written.
- Penalize generic claims (e.g. "we propose a novel method") that are not
  backed by an experimental hint.
- Distinguish benchmark / dataset releases from method papers.
- If the abstract is empty or boilerplate, mark `shortlist_fit < 0.3` and
  flag it under `risks_or_caveats`.
- Keep `one_line_summary` under 200 characters.

## When to use

Default skill for the analyze step. Disable only if you want raw model
behavior with no triage guidance.
