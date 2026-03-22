# Project Status

**Project:** ML Laboratory Co-Scientist  
**Repository:** `Synthetos`  
**Status Date:** 2026-03-22  
**Overall Status:** Phase 1 gap-closure implemented; literature intake is materially closer to Phase 1 exit completeness

## Current Summary

The Phase 1 literature loop has been tightened to close the largest implementation gaps from the architecture and phased plan review.

The system now:
- requires a real `triage` model route for literature screening
- normalizes structured source-scope defaults for intake
- deduplicates papers across sources using canonical identities plus fallback title/year matching
- preserves retrieval provenance on merged papers
- applies budgeted, selective full-text escalation instead of escalating every shortlisted paper
- binds and records Phase 1 literature skills during screening, shortlisting, and escalation
- exposes triage rationale, shortlist reason, escalation reason/type, and provenance summaries through API and UI
- stores the final literature packet as a distinct `literature_screening_report`
- emits explicit shortlist/escalation/budget events for orchestrator monitoring

## Completed This Session

### Backend behavior

- Added a dedicated `triage` route in [configs/models/routes.yaml](/Users/c/software_projects/Synthetos/configs/models/routes.yaml)
- Updated literature screening to resolve and persist the actual `triage` route id used
- Removed the silent “whole batch uncertain because route is missing” behavior; missing `triage` config now fails at operator execution time
- Added structured source-scope normalization with defaults for:
  - `mode`
  - `keywords`
  - `categories`
  - `date_from`
  - `date_until`
  - `max_results`
  - `fulltext_budget.max_fetches`
- Reworked paper deduplication to merge records across sources using:
  - arXiv id when available
  - DOI when available
  - normalized title/year fallback
- Added retrieval provenance and identity alias tracking inside `PaperCard.metadata_extra`
- Upgraded stronger identities onto existing papers when a later source provides a better canonical key
- Added budget-aware escalation selection and explicit escalation rationale generation
- Added explicit Phase 1 skill binding/execution recording for:
  - `literature_screen`
  - `shortlist_rank`
  - `fulltext_escalation`
- Added explicit events for:
  - `paper_shortlist_finalized`
  - `shortlist_decisions_finalized`
  - `paper_escalation_decision_finalized`
  - `fulltext_budget_exhausted`
  - `fulltext_fetch_skipped`
- Extended operator/report plumbing so the final literature packet is stored as `literature_screening_report`

### API and UI

- Extended paper summary/detail payloads to include:
  - `triage_rationale`
  - `shortlist_reason`
  - `escalation_reason`
  - `escalation_type`
  - `retrieval_provenance_summary`
- Updated the web intake form to capture structured source-scope inputs instead of raw JSON-only source-scope editing
- Updated the literature panel to show rationale and provenance inline for each paper
- Updated the CLI `cycle create` command to accept structured intake parameters for keywords, categories, date range, result cap, and full-text budget

### Tests

- Added/updated tests for:
  - triage route resolution and missing-route failure
  - cross-source deduplication and provenance merge
  - escalation budget selection
  - rationale visibility in Phase 1 API responses
  - Phase 1 skill lineage in integration flow
  - SSE/event-stream coverage for shortlist and escalation events

## Verification Status

### Confirmed

- `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .`
- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/`
- Result: **28/28 tests passed**

### Additional verification attempted

- `UV_CACHE_DIR=/tmp/uv-cache uv run alembic upgrade head`
  - This failed against SQLite as expected because the current Alembic migration path uses a foreign-key alter pattern that SQLite does not support
- `docker-compose up -d postgres`
  - Docker access worked with escalation, but port `5432` was already allocated by an existing local Postgres/container
- `LAB_DB_URL=postgresql+psycopg://synthetos:synthetos@localhost:5432/synthetos UV_CACHE_DIR=/tmp/uv-cache uv run alembic upgrade head`
  - Reached a live Postgres instance after escalation, but it was not the repo’s expected database and rejected the `synthetos` role

## Remaining Gaps / Follow-Up

- Postgres-backed Alembic verification still needs to run against the intended repo-managed Postgres instance
- Live arXiv retrieval against the public endpoint is still not covered in automated tests
- Live triage model smoke testing still depends on a configured reachable backend/API key
- The skill system is now recorded in lineage for Phase 1 operators, but skill influence remains intentionally lightweight and advisory rather than deeply behavior-shaping

## Recommended Next Steps

1. Run the Alembic/Postgres smoke test against the intended local Postgres instance once port/role ownership is clarified.
2. Do one live arXiv metadata retrieval smoke run and one live triage-model smoke run in a configured local environment.
3. Re-evaluate Phase 1 exit criteria after those environmental checks; the code-path gaps identified in the review are now addressed.
4. If Phase 1 is accepted, begin Phase 2 work on evidence extraction, hypothesis portfolio, and protocol compilation.
