---
id: literature.problem_scoping_support
version: 0.1.0
phase: planning
allowed_operators:
  - initialize_cycle
outputs:
  - charter_feedback
capabilities:
  - charter.read
risk_level: low
---

# Problem Scoping Support

## Purpose
Help the initialization operator sanity-check whether a charter has the minimum ingredients needed
to proceed into the first research cycle state.

## When to use
Use during cycle initialization after a charter is created and before downstream work is queued.

## Required behavior
- Verify that the charter has an explicit problem statement.
- Check that success criteria and stop conditions are present.
- Prefer concise research framing over benchmark-only framing.

