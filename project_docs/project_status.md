# Project Status

**Project:** ML Laboratory Co-Scientist
**Repository:** `Synthetos`
**Status Date:** 2026-03-22
**Overall Status:** Phase 2 (Evidence, Hypotheses, Protocols) implemented and verified — ready for Phase 3

## Current Summary

Phase 2 is complete. The system can now extract structured evidence from shortlisted papers, generate a ranked hypothesis portfolio, critique hypotheses on novelty/feasibility/impact, and compile the top-ranked hypothesis into a validated ExperimentSpec. The full pipeline chains automatically: `evidence_extraction → hypothesis_generation → hypothesis_critique → protocol_compilation`.

## Phase 2 — What Was Built

### Database Layer
- Three new SQLAlchemy models: `EvidenceCardModel`, `HypothesisCardModel`, `ExperimentSpecModel`
- Alembic migration `20260322_000004_phase2_evidence_hypotheses.py`
- Pydantic domain schemas: `EvidenceCard`, `HypothesisCard`, `ExperimentSpec`
- API response schemas: summaries, details, list responses, portfolio ranking, evidence summary
- `CyclePhase` enum extended with Phase 2 sub-phases
- `CycleCommandRequest` extended with `start_evidence`, `request_hypothesis_review`, `request_protocol_compilation`

### Service Layer (`libs/ideation/`)
- `services.py` — evidence CRUD, conflict/redundancy detection, hypothesis creation/critique/ranking, experiment spec creation/validation/rejection
- `extraction.py` — LLM-based evidence extraction with Jinja2 templates
- `hypothesis_gen.py` — LLM-based multi-hypothesis generation (single call, temperature 0.7)
- `critique.py` — per-hypothesis LLM critique with novelty/feasibility/impact scoring
- `protocol_compiler.py` — LLM-based experiment protocol compilation
- All modules follow the same pattern as `libs/literature/triage.py`: Pydantic models, template loading, JSON parsing with graceful fallback

### Operators (4 new, registered in OPERATOR_REGISTRY)
- `evidence_extraction_operator` — reads full-text artifacts (up to 4000 chars), extracts evidence, detects conflicts/redundancy
- `hypothesis_generation_operator` — generates 5 candidate hypotheses from evidence summary
- `hypothesis_critique_operator` — scores each hypothesis, computes portfolio ranking (composite = novelty × feasibility × impact), auto-approves top 3
- `protocol_compilation_operator` — compiles top hypothesis into ExperimentSpec, validates (deterministic), rejects if blocking issues

### API Endpoints (8 new GET endpoints)
- `GET /api/v1/cycles/{id}/evidence` — list evidence cards
- `GET /api/v1/cycles/{id}/evidence/summary` — aggregate evidence stats
- `GET /api/v1/cycles/{id}/evidence/{eid}` — evidence detail
- `GET /api/v1/cycles/{id}/hypotheses` — list hypotheses
- `GET /api/v1/cycles/{id}/hypotheses/portfolio` — ranked portfolio
- `GET /api/v1/cycles/{id}/hypotheses/{hid}` — hypothesis detail with evidence cards
- `GET /api/v1/cycles/{id}/experiment-specs` — list specs
- `GET /api/v1/cycles/{id}/experiment-specs/{sid}` — spec detail with hypothesis summary

### CLI Commands (9 new)
- `evidence list|show|summary`
- `hypothesis list|show|portfolio`
- `experiment list|show`
- `cycle start-evidence`

### Skills (4 new under `skills/ideation/`)
- `evidence_extraction` — for evidence_extraction operator
- `novelty_critique` — for hypothesis_critique operator
- `protocol_drafting` — for protocol_compilation operator
- `benchmark_context` — for hypothesis_generation and protocol_compilation

### Web UI
- TypeScript interfaces for all Phase 2 entities
- API fetch functions for evidence, hypotheses, portfolio, experiment specs
- EvidencePanel — summary stats + scrollable evidence card list
- HypothesisPortfolioPanel — ranked hypothesis cards with dimension scores
- ExperimentSpecPanel — spec details with validation status
- "Start Evidence Extraction" button

### Prompt Templates (5 new under `prompts/ideation/v1/`)
- `evidence_extraction.md`, `hypothesis_generation.md`, `hypothesis_critique.md`, `protocol_compilation.md`, `conflict_detection.md`

### Model Routes (4 new)
- `evidence_extractor`, `ideation`, `critic`, `protocol_drafter`

### Tests
- 5 new unit test files (29 new tests): ideation services, evidence extraction, hypothesis generation, critique, protocol compiler
- 1 new integration test file (6 new tests): Phase 2 API endpoints + full pipeline with mocked LLM
- 4 new test fixtures: sample evidence/hypotheses/critique/protocol responses

## Verification Status

### Confirmed
- `uv run ruff check .` — 0 violations
- `uv run pytest tests/` — **63/63 tests passed** (zero regressions from Phase 0/1)

### Test Breakdown
- Phase 0 integration: 2 tests
- Phase 1 integration: 5 tests
- Phase 2 integration: 6 tests
- Unit tests: 50 tests

## Phase 2 Exit Criteria (All Met)

1. ✅ Evidence cards produced from shortlisted sources
2. ✅ At least three candidate hypotheses generated and ranked
3. ✅ Chosen hypothesis compiles into a valid ExperimentSpec
4. ✅ Skills influence context assembly in a recorded way
5. ✅ Orchestrator can inspect portfolio and request next operator step through API

## LLM Gateway Overhaul (Cross-Cutting)

Completed a major overhaul of the model gateway to be provider-agnostic, local-first, and support structured outputs.

### Bug Fix
- Fixed critical production bug: `call_chat_completion()` was returning a raw dict (full OpenAI response), but 4 of 5 callers treated it as a string. Tests masked this because they mocked with strings. Gateway now returns extracted content string.

### Provider Support
- Created `libs/adapters/llm/providers.py` — pure-function adapters for OpenAI-compatible (vLLM, LM Studio, Ollama, OpenAI), Anthropic (Messages API), and Google (Gemini). No vendor SDKs, just httpx request construction.
- The `provider` field on `ModelRouteConfig` now drives endpoint, auth, payload format, and response extraction.
- Added `priority` field for fallback chains (lower = preferred).
- Added `supports_json_mode` field for structured output opt-in.

### Structured Outputs + JSON Repair
- Added `json-repair` dependency for handling malformed LLM JSON.
- Created `libs/adapters/llm/json_utils.py` — shared `parse_json_lenient()` with multi-level fallback: `json.loads()` → extract from prose/fences → `json_repair`.
- All 5 `_parse_*_json()` functions now use the shared utility.
- Added `json_mode=True` to all LLM callers + `call_structured()` convenience method.

### Local-First Defaults
- All default routes now point to LM Studio (`localhost:1234`), no hardcoded model names.
- Example configs: `routes.openai-example.yaml`, `routes.anthropic-example.yaml`, `routes.multi-local-example.yaml` (3 Mac + 1 GPU workstation).
- Timeout defaults bumped to 60-120s for local inference.

### Verification
- `uv run ruff check .` — 0 violations
- `uv run pytest tests/` — **104/104 tests passed** (41 new tests added)

## Recommended Next Steps

1. Begin Phase 3: Code generation and containerized execution
2. Run live smoke test with real LLM backend (local LM Studio) to verify end-to-end flow
3. Run Alembic migration against Postgres to verify Phase 2 schema
4. Consider model catalog feature for managing models across multiple local servers
