---
id: example.hello_world
version: 0.1.0
phase: planning
allowed_operators: [echo]
preferred_models: [summarization]
context_inputs:
  - research_charter
outputs:
  - greeting
capabilities: []
risk_level: low
trust_tier_required: third_party_untrusted
---

# Hello World Skill

## Purpose

A minimal example skill for testing skill discovery, validation, and the catalog API.

## When to Use

This skill is used during Phase 0 testing to verify the skill system works end to end.

## Behavior

Returns a simple greeting message. This is a placeholder skill with no real research utility.
