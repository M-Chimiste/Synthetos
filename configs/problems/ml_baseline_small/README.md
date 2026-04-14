# ml_baseline_small — CI-safe pilot fixture

Tiny synthetic 2-class classification task used to smoke-test the full
Synthetos chain end-to-end. CPU-only, deterministic seeds, no external
network, no GPU. Target runtime under 5 minutes on a laptop.

## Purpose

This fixture is not a scientific experiment. It exercises:

- discovery (metadata triage over a stub corpus subset)
- analysis (graph + coverage on a handful of stub papers)
- ideation (hypothesis generation against canned evidence)
- protocol compile + execution (tiny sklearn logistic regression in a
  sandboxed container)
- verification (baseline comparison + artifact presence)
- autonomous loop (3-run budget, supervised mode)
- cycle close + Phase 6 pattern consolidation

## Hardware prerequisites

- CPU only (any commodity x86_64 or ARM laptop is sufficient)
- No GPU required
- ~2 GB RAM during the run

## Cost estimate

Essentially free — no hosted model calls are required when running against
a local LLM endpoint (LMStudio/Ollama). Wall clock < 5 minutes.
