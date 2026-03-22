# Project Status

**Project:** ML Laboratory Co-Scientist  
**Repository:** `Synthetos`  
**Status Date:** 2026-03-22  
**Overall Status:** Phase 2 implemented, hardened, and re-verified — ready for Phase 3

## Current Summary

Phase 2 now meets the architectural intent of the phased plan, not just the mocked happy path. The system can:

- extract evidence cards from shortlisted sources
- preserve provenance and read depth on evidence
- detect both redundancy and conservative conflict signals between evidence claims
- generate and rank multiple hypotheses from evidence only
- stop cleanly when evidence or hypotheses are missing instead of auto-advancing
- compile approved hypotheses into validated `ExperimentSpec`s
- record Phase 2 skill execution lineage
- record durable Phase 2 model invocation lineage
- resolve required model routes from committed repo config

The Phase 2 pipeline remains:

`evidence_extraction -> hypothesis_generation -> hypothesis_critique -> protocol_compilation`

but now only advances when prerequisites are actually satisfied.

## What Was Completed In This Session

### Orchestration hardening

- Enforced evidence-first progression in `libs/orchestration/operators.py`
- `evidence_extraction` no longer queues `hypothesis_generation` when no papers or no evidence cards are produced
- `hypothesis_generation` now no-ops with a clear report when evidence is absent
- `hypothesis_critique` now no-ops with a clear report when generated hypotheses are absent
- `protocol_compilation` continues to require approved hypotheses and now records Phase 2 skill lineage in its no-op path too

### Phase 2 skill runtime + lineage

- Wired all four Phase 2 operators into the existing skill-binding/runtime pattern
- Added Phase 2 `skill_execution_records` so evidence, hypothesis, critique, and protocol steps are recorded like Phase 1
- Expanded skill payloads to capture operator-specific influence metadata:
  - evidence context shaping
  - benchmark context injection
  - novelty critique activity
  - protocol drafting / protocol context shaping

### Model routing + invocation lineage

- Added committed default route config at `configs/models/routes.yaml`
- Added durable model invocation persistence for all Phase 2 LLM-backed steps
- Recorded route id, model id, prompt id, job/cycle linkage, and invocation parameters including bound skills

### Evidence conflict detection

- Replaced the placeholder conflict detector with a deterministic, conservative pass
- Kept redundancy detection as a separate heuristic
- Added symmetric `conflict_with` linking and explanatory `conflict_notes`

### Testing and verification coverage

- Added unit tests for Phase 2 operator gating behavior
- Added unit tests for conflict detection behavior
- Extended Phase 2 integration tests to verify:
  - committed model-route resolution
  - Phase 2 skill execution records
  - Phase 2 model invocation persistence
  - zero-evidence runs do not auto-advance

## Verification Status

### Confirmed this session

- `uv run pytest tests` — **112/112 tests passed**
- `uv run ruff check /Users/c/software_projects/Synthetos` — **passed**

### Not yet live-verified

- No live end-to-end run against a real local or hosted model backend was performed in this session
- No Phase 2 smoke test against a real LM Studio / vLLM / other configured inference service was performed yet

## Phase 2 Exit Criteria

1. ✅ Evidence cards are produced from shortlisted sources
2. ✅ At least three candidate hypotheses can be generated and ranked
3. ✅ The chosen hypothesis compiles into a valid `ExperimentSpec`
4. ✅ Skills influence context assembly and outputs in a recorded way
5. ✅ An orchestrator can inspect the portfolio and request the next operator step through the API

## Recommended Next Steps

1. Begin Phase 3 implementation: execution lab, isolated workspaces, and containerized runs
2. Run a live smoke test against a real model backend using the committed route config
3. Verify Alembic migrations against the target Postgres setup, not just SQLite-backed tests
4. Add Phase 3 telemetry/control views to the web UI once execution starts landing
