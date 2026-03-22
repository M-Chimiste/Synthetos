# Project Status

**Project:** ML Laboratory Co-Scientist
**Repository:** `Synthetos`
**Status Date:** 2026-03-22
**Overall Status:** Phase 1 (Research Intake & Literature Triage) implemented and verified — ready for Phase 2

## Current Summary

Phase 1 is complete. The system now delivers a full literature intake pipeline: a user can define a research problem, start literature intake, and the system will automatically retrieve papers from arXiv (and internal corpus), screen them by title + abstract using LLM triage, rank a shortlist, optionally fetch full text (HTML-first, PDF fallback with markitdown conversion), and generate a comprehensive literature screening report.

Five new operators chain together via `next_actions` auto-enqueue:
1. `source_retrieval` — fetches from arXiv OAI-PMH + internal corpus
2. `literature_screen` — LLM-based title+abstract triage (loops until all papers screened)
3. `shortlist_rank` — ranks screened papers, identifies escalation candidates
4. `fulltext_escalation` — HTML-first (ar5iv), PDF fallback with markitdown conversion
5. `literature_report` — generates the screening packet markdown report

## Phase 1 Completed Work

### Core Infrastructure Changes

- **next_actions auto-enqueue**: `apply_operator_result()` now auto-enqueues follow-up jobs from `OperatorResult.next_actions`, enabling operator chaining
- **Worker auto-QUEUED**: Worker transitions cycle to QUEUED when pending jobs exist after an operator succeeds
- **State machine**: Added READY → QUEUED transition to support pipeline re-entry
- **CyclePhase enum**: Advisory sub-phase tracker (`libs/core/phases.py`) for tracking pipeline progress in state snapshot context
- **start_intake command**: Extended `CycleCommandRequest` to accept `"start_intake"`, which enqueues the `source_retrieval` job

### Database & Schemas

- **3 new tables** via Alembic migration `20260322_000003_phase1_literature.py`:
  - `source_retrieval_sessions` — tracks retrieval runs against sources
  - `paper_cards` — core literature entity with lifecycle status, triage scores, shortlist rank, escalation info, dedup hash
  - `screening_decisions` — individual triage decisions (audit trail)
- **New Pydantic domain schemas**: `PaperCard`, `SourceRetrievalSession`, `ScreeningDecision`
- **New API schemas**: `PaperCardSummary`, `PaperCardDetail`, `PaperListResponse`, `LiteratureTriageResponse`, `RetrievalSessionListResponse`

### Source Adapters

- **arXiv OAI-PMH adapter** (`libs/adapters/arxiv/`): Rate-limited harvester with XML parsing, resumption token support, category/date filtering, subcategory support
- **Internal corpus adapter** (`libs/adapters/corpus/`): Searches local markdown/text files under `$LAB_DATA_ROOT/corpus`
- **Fulltext fetcher** (`libs/adapters/literature/fulltext.py`): HTML-first (ar5iv), PDF fallback with **markitdown** conversion to markdown

### Literature Services

- `libs/literature/services.py`: Business logic for paper ingestion (with dedup), screening, shortlisting, escalation recording, triage summary building, and screening report generation
- `libs/literature/triage.py`: LLM triage integration with Jinja2 prompt rendering, structured JSON response parsing, graceful fallback for malformed responses

### LLM Gateway

- Added `call_chat_completion()` to `ModelGateway` — OpenAI-compatible chat completions endpoint
- Added `triage` model route in `configs/models/routes.yaml`

### Five New Operators

All registered in `OPERATOR_REGISTRY`:
- `source_retrieval_operator` — arXiv + corpus retrieval → PaperCards
- `literature_screen_operator` — LLM triage with batch processing + loop
- `shortlist_rank_operator` — score-based ranking + escalation detection
- `fulltext_escalation_operator` — HTML/PDF fetch + markitdown conversion
- `literature_report_operator` — screening packet generation

### Skills & Prompts

- **2 new skills**: `literature.shortlist_critique`, `literature.escalation_rationale`
- **4 prompt assets**: `title_abstract_triage.md` (real Jinja2 template), `shortlist_ranking.md`, `escalation_rationale.md`, `screening_report.md`

### API Endpoints

- `GET /api/v1/cycles/{id}/papers` — list papers with optional status filter
- `GET /api/v1/cycles/{id}/papers/{paper_id}` — paper detail with screening decisions
- `GET /api/v1/cycles/{id}/literature` — triage summary (counts + paper list)
- `GET /api/v1/cycles/{id}/retrieval-sessions` — retrieval session list
- `POST /api/v1/cycles/{id}/commands` extended with `"start_intake"`

### Web UI

- "Start Literature Intake" button on cycle detail panel (visible when cycle is READY)
- Literature Triage panel with retrieval progress, paper list, lifecycle status badges, triage scores, shortlist ranks
- Header updated to "Phase 1 Control Tower"

### CLI

- `cycle start-intake <cycle_id>` — sends start_intake command
- `papers list <cycle_id> [--status=]` — lists papers
- `papers show <cycle_id> <paper_id>` — paper detail
- `literature summary <cycle_id>` — triage summary

### Dependencies

- Added `jinja2`, `markitdown`, `tenacity` to `pyproject.toml`

## Verification Status

### Confirmed

- `uv run ruff check .` — 0 violations
- `uv run pytest tests/` — 23/23 tests passed (6 integration, 17 unit)
- Phase 0 integration tests still pass (no regressions)
- Full pipeline integration test: create cycle → initialize → start intake → source retrieval → screening → shortlist → escalation → report (all with mocked external calls)

### Test Coverage

- **Unit tests** (17): core, skills, gateway, arxiv adapter XML parsing, literature services (ingest, screen, shortlist, escalation, report), triage JSON parsing
- **Integration tests** (6): Phase 0 cycle+worker, Phase 0 skills, start_intake command, paper listing, literature triage endpoint, full pipeline with mock adapters

## Phase 0 Work (Still In Place)

All Phase 0 foundation remains intact and operational:
- Monorepo structure, config, Docker Compose
- State machine, job queue, operator pattern
- API, CLI, Web UI (extended for Phase 1)
- Skill system, event streaming, auth

## Current Risks / Gaps

- Integration tests use SQLite (no `FOR UPDATE SKIP LOCKED`, JSON column behavior differs from PostgreSQL)
- arXiv OAI-PMH has not been tested against live endpoint (only fixture-based XML parsing tests)
- LLM triage tests mock the gateway; no end-to-end LLM test
- pyright not yet in dev dependencies
- Alembic not yet primary migration path (still using `create_all()` for dev/test)

## Recommended Next Steps

1. Run a local Postgres-backed verification with Alembic migrations
2. Test arXiv adapter against live OAI-PMH endpoint
3. Begin Phase 2: Evidence extraction, hypothesis portfolio, protocol compilation
4. Add pyright as dev dependency and fix type errors
5. Expand test coverage: auth rejection, error paths, concurrent worker scenarios
