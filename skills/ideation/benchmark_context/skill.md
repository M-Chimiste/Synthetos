---
id: ideation.benchmark_context
version: 0.1.0
phase: ideation
allowed_operators:
  - hypothesis_generation
  - protocol_compilation
preferred_models:
  - ideation
context_inputs:
  - research_charter
  - benchmark_metadata
outputs:
  - benchmark_context
capabilities:
  - source.read_metadata
risk_level: low
---

# Benchmark Context

## Purpose
Provide benchmark-specific context for hypothesis generation and protocol compilation.

## When to use
Use when the research problem targets a specific benchmark or competition dataset.

## Required behavior
- Surface relevant benchmark rules, constraints, and evaluation criteria
- Identify known strong baselines and leaderboard context
- Highlight dataset characteristics that affect experiment design
- Ensure generated hypotheses and protocols respect benchmark constraints
