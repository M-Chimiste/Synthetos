---
id: example.elevated_capability
version: "0.1.0"
phase: execution
allowed_operators:
  - execution_setup
preferred_models:
  - coding
context_inputs:
  - experiment_spec
outputs:
  - artifact_manifest
capabilities:
  - fs.write
  - network.access
risk_level: high
trust_tier_required: user_local_trusted
---

# Elevated Capability Example

## Purpose

Demonstrate a skill manifest that requires the runtime trust gate before it can
be enabled.

## Why It Is Gated

This example requests two elevated capabilities:

- `fs.write`
- `network.access`

That combination is intentionally blocked for `third_party_untrusted` skills by
the validator. It must be installed as `user_local_trusted` or
`first_party_trusted`.

## Example Use

Use a skill like this only when a run genuinely needs to fetch external assets
and materialize derived files into the execution workspace.
