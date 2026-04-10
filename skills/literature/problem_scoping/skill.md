---
id: literature.problem_scoping
version: 0.1.0
phase: discovery
allowed_operators: [discovery_intake]
preferred_models: [planning]
context_inputs:
  - research_charter
  - problem_profile
outputs:
  - scoped_problem
capabilities: []
risk_level: low
trust_tier_required: first_party_trusted
---

# Literature problem scoping

## Purpose

Help the discovery intake operator turn a researcher's loose problem statement
into a tight, retrieval-friendly query.

## Behavior

When called by the intake operator, this skill rewrites the user's problem
statement into:

1. A short, dense topic phrase suitable for lexical retrieval.
2. A list of synonyms and adjacent terms.
3. A short list of arXiv categories most likely to contain relevant work.
4. Any obvious exclusions (e.g. "not survey papers", "not pre-2018 work").

The rewritten artifact is attached to the ProblemProfile so the
``discovery_search`` operator has a more focused query than the raw user text.

## When to use

Always, on every new discovery session, unless the user supplies pre-scoped
search terms.
