---
id: literature.shortlist_critique
version: 0.1.0
phase: discovery
allowed_operators: [discovery_finalize]
preferred_models: [evaluation]
context_inputs:
  - shortlist
  - problem_profile
outputs:
  - shortlist_critique
capabilities: []
risk_level: low
trust_tier_required: first_party_trusted
---

# Shortlist critique

## Purpose

Provide a sanity check on the final shortlist before the discovery report is
written.  Used by the finalize operator to flag obviously weak shortlists
without blocking the run.

## Behavior

Reads the stable view + discovery view and emits a short critique covering:

- Coverage gaps (no benchmark papers? no recent work?).
- Overly clustered topics (too many near-duplicates from one group).
- Suspiciously low metadata-analysis scores across the top-N.

## When to use

Default skill for the finalize step. Output is advisory only -- it never
prevents finalization.
