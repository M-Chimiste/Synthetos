# Project Status

**Product:** Synthetos (ML Laboratory Co-Scientist)
**Date:** 2026-04-10
**Phase:** 1 — Discovery Pipeline MVP
**Status:** Phase 1 remediation pass completed. Code-level quality gates pass (`ruff`, `pyright`, `pytest`, web build). The main remaining work is live integration validation against the real corpus, configured model endpoints, and a full end-to-end discovery smoke.

---

## Session Summary

Phase 1 now includes both the original discovery slice and the follow-up remediation pass that closed the main review gaps. A researcher (or orchestrator) can define a problem on a charter, retrieve candidates from the local pre-embedded arXiv mirror **and** the live arXiv API, fuse those sources onto one comparable first-stage ranking scale, optionally rerank with a local cross-encoder, run metadata-depth LLM analysis over title + abstract, and produce Stable + Discovery views plus a downloadable report bundle — all viewable in the React UI and consumable through the orchestrator API and SSE event stream.

The implementation followed the approved plan at `/Users/c/.claude/plans/fluffy-questing-wirth.md`, with one user-confirmed correction: the local arXiv corpus on disk is **~56 GB / 2,995,533 records** (not the smaller figure read earlier), and is pre-embedded with `Alibaba-NLP/gte-modernbert-base` (768-dim).

The main outcomes were:

- Added a Phase 1 schema with six new tables and a single Alembic migration that creates the `arxiv_corpus` mirror, resumable `corpus_import_runs`, both a generated `tsvector` GIN index and an HNSW index over the 768-dim `embedding` column
- Built source adapters for the internal corpus (hybrid BM25 + pgvector with RRF fusion) and the live arXiv API (Atom parser, 3-second token bucket, retry on 5xx/429)
- Built a cross-encoder reranker with a graceful-fallback strategy that emits `discovery.rerank_skipped` events when it degrades
- Built a five-step operator chain (`discovery_intake` → `search` → `rerank` → `analyze` → `finalize`) that walks a research cycle from `created` through `discovery_screened`, persists paper cards, view memberships, metadata-analysis packets, and a markdown + JSON report bundle to disk, and now fails truthfully when the report cannot be written
- Added a 10-endpoint discovery API mounted under `/api/v1` reusing the existing `cycles.*` scope model and the Phase 0 SSE event stream
- Added React routes for starting a discovery session, browsing Stable / Discovery views with manual triage, surfacing rationale fields, and viewing the rendered report
- Added a corpus importer CLI with a copy-oriented cold-load path, resumable upsert mode, and DB-backed checkpoint tracking, plus a `synthetos discovery run` headless wrapper
- Shipped four first-party `literature.*` skill packages and wired them into the actual intake/analyze/finalize operators through the skill registry
- Closed the main review gaps: truthful discovery failure state, session-scoped paper access, normalized mixed-source ranking, session-level failure propagation from worker jobs, and accurate UI counters for Stable vs Discovery views
- Added 44 unit tests covering RRF, dedupe, MMR views, the rerank fallback chain, the metadata-analysis schema, the arXiv Atom parser, evaluation metrics, discovery failure helpers, source-fusion behavior, and worker failure propagation

---

## What Was Added

### 1. Schema, migrations, and core types

- New ORM models:
  - `libs/storage/models/corpus.py` — `ArxivCorpusRecord` with `Vector(768)` embedding column, generated `tsvector` for BM25, JSONB scalar fields, plus `CorpusImportRun` for resumable import progress
  - `libs/storage/models/discovery.py` — `ProblemProfile`, `DiscoverySession`, `DiscoveryEvaluation`
  - `libs/storage/models/papers.py` — `PaperCard` with denormalized metadata, all five score columns (`bm25`, `dense`, `first_stage`, `rerank`, `final`), `view_membership`, `triage_status`, and `metadata_analysis` JSONB
- Pydantic DTOs:
  - `libs/schemas/discovery.py` — `ProblemProfileCreate/Read`, `RerankPolicy`, `DiscoveryBudget`, `DiscoverySessionRead/StartResponse`, `TriageRequest`, `EvaluationSubmission`, `EvaluationMetricRead`
  - `libs/schemas/papers.py` — `PaperCardRead`
- Alembic migration:
  - `libs/storage/migrations/versions/20260411_000001_phase1_discovery.py` — creates all six tables, the GIN index on `arxiv_corpus.tsv`, and the HNSW index on `arxiv_corpus.embedding` (`vector_cosine_ops`, `m=16`, `ef_construction=64`)
- New event taxonomy:
  - `libs/core/event_types.py` — `DiscoveryEvents` `StrEnum` namespaced under `discovery.*`

### 2. Embeddings router

- `libs/adapters/embeddings/router.py` — role/profile-based router mirroring the LLM router pattern, pinned to dimension 768. Reads a new `embeddings:` block in `configs/models.yaml`. Validates dimension at startup; loud failure on mismatch (the corpus is locked to `Alibaba-NLP/gte-modernbert-base`, so query-time embeddings must come from the same checkpoint).

### 3. Source adapters

- `libs/adapters/sources/base.py` — `SourceAdapter` `Protocol`, `SourceQuery`, `SourceHit` Pydantic DTOs
- `libs/adapters/sources/internal_corpus.py` — `InternalCorpusAdapter` runs lexical (`ts_rank_cd`) and dense (`embedding <=> :qvec`) legs concurrently and fuses with reciprocal rank fusion. Falls back to lexical-only if the embeddings router is unavailable.
- `libs/adapters/sources/arxiv_live.py` — async `httpx` client against `export.arxiv.org/api/query`, stdlib XML Atom parser, class-level token bucket enforcing the 3-second minimum interval, `tenacity` retry on 5xx / 429
- `libs/adapters/sources/dedupe.py` — DOI → canonical arXiv id → `sha1(title + first author)` key strategy with merge-prefer-embedded-row semantics

### 4. Reranker stack

- `libs/adapters/reranker/base.py` — `Reranker` `Protocol`, `RerankDoc`, `RerankResult`, error classes (`RerankerUnavailable`, `RerankBudgetExceeded`)
- `libs/adapters/reranker/local_cross_encoder.py` — `BAAI/bge-reranker-v2-m3` via `sentence-transformers`, lazy load, GPU autodetect, runs inside a thread executor with `asyncio.wait_for` budget enforcement
- `libs/adapters/reranker/no_op.py` — pass-through fallback that preserves first-stage ordering
- `libs/discovery/rerank_strategy.py` — chooser that runs the primary reranker and falls back to no-op on `RerankerUnavailable`, `RerankBudgetExceeded`, or any other reranker error, recording the `fallback_reason`

### 5. Discovery library

- `libs/discovery/ranking.py` — `rrf_fuse` and `normalize_scores`
- `libs/discovery/views.py` — `build_stable_view` (top-k by `final_score`, deterministic tie-break) and `build_discovery_view` (MMR with cosine over embeddings, falling back to category-overlap when no embeddings are present)
- `libs/discovery/metadata_analysis.py` — `MetadataAnalysisPacket` Pydantic schema and `analyze_one` / `analyze_many` calling `ModelRouter.complete_structured` with the `metadata_analysis` role under an `asyncio.Semaphore` rate limit
- `libs/discovery/reports.py` — markdown + JSON report bundle renderer that writes to `LAB_DATA_ROOT/artifacts/discovery/<session_id>/`
- `libs/discovery/evaluation.py` — Recall@K, Precision@K, MRR utilities
- `libs/discovery/skill_support.py` — registry-backed skill lookup plus structured helpers for problem scoping and shortlist critique

### 6. Discovery operators

All five operators live in `libs/discovery/operators/` and conform to the existing sync `OperatorHandler` contract; inner async work runs via `asyncio.run`. The chain is registered with the worker via `libs.discovery.operators.register` from `apps/worker/executor.py`:

| Operator | What it does |
|---|---|
| `discovery_intake` | Loads the profile, marks the session started, applies the `literature.problem_scoping` skill when available, transitions cycle `created → discovery_ready`, enqueues `discovery_search` |
| `discovery_search` | Fans out to internal corpus + arxiv_live, fuses source rankings with discovery-layer RRF, dedupes, persists `paper_cards` rows with normalized first-stage scores, enqueues `discovery_rerank` |
| `discovery_rerank` | Reranks the top-N via local cross-encoder; on failure or budget exhaustion falls back cleanly to no-op and emits `discovery.rerank_skipped` |
| `discovery_analyze` | Runs metadata-depth LLM analysis on the top-N reranked papers using the literature triage/escalation skill prompts when available, persists packets to `paper_cards.metadata_analysis` |
| `discovery_finalize` | Builds Stable + Discovery views, applies advisory shortlist critique, writes the report bundle to disk, and only transitions cycle `discovery_ready → discovery_screened` on true success |

Each step appends a structured `step_log` entry, merges into `discovery_sessions.stats`, and emits namespaced `discovery.*` events that the existing SSE stream surfaces in real time. Failed discovery jobs now also mark the linked `DiscoverySession` failed so the session resource stays truthful without requiring job inspection.

### 7. Discovery service and API

- `libs/core/services/discovery_service.py` — async business logic for starting a session, listing papers, triage overrides, evaluation submission, and report retrieval
- `apps/api/routers/discovery.py` — 10 endpoints under `/api/v1`:
  - `POST /charters/{charter_id}/discovery`
  - `GET /discovery`
  - `GET /discovery/{session_id}`
  - `GET /discovery/{session_id}/profile`
  - `GET /discovery/{session_id}/papers`
  - `GET /discovery/{session_id}/papers/{paper_id}`
  - `POST /discovery/{session_id}/papers/{paper_id}/triage`
  - `GET /discovery/{session_id}/report`
  - `POST /discovery/{session_id}/evaluation`
  - `GET /discovery/{session_id}/evaluation`
- Reuses the existing `cycles.read` / `cycles.write` scopes — no new scope strings
- Paper detail and triage routes now enforce true `(session_id, paper_id)` scoping rather than treating `session_id` as advisory

### 8. Configs and skills

- `configs/models.yaml` — added an `embeddings:` profile pinned to `Alibaba-NLP/gte-modernbert-base` / 768
- `configs/discovery/defaults.yaml` — first-stage / rerank / view / analysis defaults
- `skills/literature/` — four first-party skill packages: `literature.problem_scoping`, `literature.title_abstract_triage`, `literature.shortlist_critique`, `literature.escalation_rationale`

### 9. CLI

- `apps/cli/commands/corpus.py` — new `synthetos corpus` command group:
  - `import-arxiv --path artifacts/arxiv-embedded.jsonl [--limit] [--resume]`
  - `stats`
  - `inspect`
- `apps/cli/commands/discovery.py` — `synthetos discovery run --charter-id … --query …` headless wrapper that creates the cycle + profile + session, enqueues `discovery_intake`, and tails session status until completion

### 10. Web UI

- `apps/web/src/api/client.ts` and `hooks.ts` — typed clients and TanStack Query hooks for sessions, profiles, papers, triage, and reports
- `apps/web/src/routes/charters/$charterId/discovery/new.tsx` — form to create a discovery session (query, source scope, view preference, rerank policy, budgets)
- `apps/web/src/routes/discovery/$sessionId/index.tsx` — session detail page with Stable/Discovery view tabs, accurate aggregate counts, paper cards, rationale fields, failure state, manual triage, and the live SSE event stream
- `apps/web/src/routes/discovery/$sessionId/report.tsx` — markdown report viewer
- `apps/web/src/routes/charters/$charterId.tsx` — added a "Start discovery" button on the charter detail page
- `apps/web/src/routeTree.gen.ts` — regenerated to include the new routes

### 11. Tests

Added 44 unit tests under `tests/unit/`:

- `test_rrf.py` — RRF fusion math, ties, empty inputs, normalization
- `test_dedupe.py` — DOI / arXiv id / title-hash key generation, merge semantics
- `test_views.py` — stable view determinism, MMR diversification
- `test_rerank_strategy.py` — fallback chain (disabled, unavailable, budget exceeded, working primary)
- `test_metadata_analysis_schema.py` — Pydantic packet validation
- `test_arxiv_live_parser.py` — Atom parsing fixture
- `test_evaluation_metrics.py` — Recall@K, Precision@K, MRR
- `test_discovery_common.py` — session failure helper behavior
- `test_discovery_search.py` — mixed-source fusion and dedupe behavior

Plus a 20-record JSONL fixture at `tests/fixtures/arxiv_sample.jsonl`.

---

## Files Touched in This Phase 1 Pass

### New backend / library files

- `libs/storage/models/corpus.py`
- `libs/storage/models/discovery.py`
- `libs/storage/models/papers.py`
- `libs/storage/migrations/versions/20260411_000001_phase1_discovery.py`
- `libs/schemas/discovery.py`
- `libs/schemas/papers.py`
- `libs/core/event_types.py`
- `libs/adapters/embeddings/router.py`
- `libs/adapters/sources/__init__.py`, `base.py`, `internal_corpus.py`, `arxiv_live.py`, `dedupe.py`
- `libs/adapters/reranker/__init__.py`, `base.py`, `local_cross_encoder.py`, `no_op.py`
- `libs/discovery/__init__.py`, `ranking.py`, `views.py`, `metadata_analysis.py`, `rerank_strategy.py`, `evaluation.py`, `reports.py`
- `libs/discovery/skill_support.py`
- `libs/discovery/operators/__init__.py`, `_common.py`, `intake.py`, `search.py`, `rerank.py`, `analyze.py`, `finalize.py`
- `libs/core/services/discovery_service.py`
- `apps/api/routers/discovery.py`
- `apps/cli/commands/corpus.py`
- `apps/cli/commands/discovery.py`

### Modified backend / library files

- `apps/api/main.py` — mount discovery router
- `apps/cli/main.py` — register `corpus` and `discovery` Typer subcommands
- `apps/worker/executor.py` — register the five Phase 1 operators
- `libs/storage/models/__init__.py` — export new ORM models
- `libs/adapters/embeddings/__init__.py` — export the new router

### New configs and skills

- `configs/discovery/defaults.yaml`
- `configs/models.yaml` — `embeddings:` block added
- `skills/literature/problem_scoping/skill.md`
- `skills/literature/title_abstract_triage/skill.md`
- `skills/literature/shortlist_critique/skill.md`
- `skills/literature/escalation_rationale/skill.md`

### Frontend

- `apps/web/src/api/client.ts` — discovery types and fetchers
- `apps/web/src/api/hooks.ts` — discovery TanStack Query hooks
- `apps/web/src/routes/charters/$charterId/discovery/new.tsx`
- `apps/web/src/routes/discovery/$sessionId/index.tsx`
- `apps/web/src/routes/discovery/$sessionId/report.tsx`
- `apps/web/src/routes/charters/$charterId.tsx` — Start discovery CTA
- `apps/web/src/routeTree.gen.ts`

### Tests and fixtures

- `tests/unit/test_rrf.py`
- `tests/unit/test_dedupe.py`
- `tests/unit/test_views.py`
- `tests/unit/test_rerank_strategy.py`
- `tests/unit/test_metadata_analysis_schema.py`
- `tests/unit/test_arxiv_live_parser.py`
- `tests/unit/test_evaluation_metrics.py`
- `tests/unit/test_discovery_common.py`
- `tests/unit/test_discovery_search.py`
- `tests/fixtures/arxiv_sample.jsonl`

### Tooling

- `pyproject.toml` — added `pgvector` runtime dep, optional `reranker` extra (`sentence-transformers`), and a `B008` ruff exception for `apps/cli/**` (Typer's `Option`/`Argument` defaults are idiomatic)

---

## Verification Status

The repository passes the Phase 1 code-level quality gates after the remediation pass:

- `uv run ruff check .` — passes
- `UV_CACHE_DIR=/tmp/uv-cache uv run pyright` — `0 errors, 0 warnings, 0 informations`
- `uv run pytest` — `44 passed`
- `cd apps/web && npm run build` — passes

---

## What Remains Before Phase 1 Can Be Called Fully Verified

The remaining gaps are integration / environment-dependent rather than code-level:

1. **Run the new corpus import paths end-to-end against the 56 GB JSONL.**
   - `synthetos corpus import-arxiv --path artifacts/arxiv-embedded.jsonl` now has a copy-oriented cold-load path and DB-backed checkpoints for resume mode, but those paths have not yet been timed against a real Postgres instance and the full corpus.
2. **Stand up a query-time embedding endpoint that serves `Alibaba-NLP/gte-modernbert-base`.**
   - The internal corpus adapter calls `EmbeddingsRouter` for query-time embeddings; without an OpenAI-compatible endpoint at the configured `base_url`, the dense leg degrades to lexical-only. Adding `text-embeddings-inference` or `vllm` to `docker-compose.yml` is the cleanest path.
3. **Run one full discovery smoke against a real charter and configured models.**
   - From the UI: open a charter → "Start discovery" → watch the SSE event stream show `discovery.papers_discovered`, optional `discovery.rerank_skipped`/`rerank_completed`, `discovery.paper_metadata_analyzed`, `discovery.session_finalized` or `discovery.session_failed` → view the rendered report.
   - From the orchestrator API: `POST /api/v1/charters/{id}/discovery` → subscribe to `/api/v1/events/stream?cycle_id=…` → `GET /api/v1/discovery/{id}/report`.
4. **Cross-encoder model warm-up.**
   - First run will trigger a ~1 GB download for `BAAI/bge-reranker-v2-m3`. The strategy chain handles the missing-model case cleanly by emitting `discovery.rerank_skipped` and falling back to no-op, so this is not blocking.
5. **Validate the skill-guided LLM steps against the configured gateway.**
   - `discovery_intake`, `discovery_analyze`, and `discovery_finalize` now consume the literature skills through the registry, but those prompt layers have only been validated at the code/test level so far, not against a live planning/metadata/evaluation model stack.

None of these are blocking for Phase 1 *being implemented and corrected*; they are blocking for Phase 1 being *fully exercised end-to-end against real data on this machine*.

---

## What Is Explicitly Still Out of Scope

- Full-text fetch (HTML/PDF), structure-aware chunking, and the typed paper graph (Phase 2)
- Evidence cards, hypothesis cards, experiment specs, and the execution sandbox (Phase 3)
- Auto-remediation, directional signal, and frontier tracking (Phase 4)
- Autonomous loop, gating, and completion reports (Phase 5)
- Cross-charter pattern memory (Phase 6)
- Re-embedding the corpus or supporting alternate embedding models — Phase 1 is locked to `gte-modernbert-base` / 768
- Semantic Scholar / OpenAlex / Crossref source adapters — deferred
- An OpenAPI codegen pipeline for the web client — types stay manual for now

---

## Current Runbook

```bash
# Python dependencies (include the optional reranker extra)
uv sync --extra dev --extra reranker

# Database
docker compose up -d postgres
uv run synthetos db init   # runs alembic upgrade head; lands Phase 1 schema

# (One-time) import the pre-embedded arXiv mirror — ~56 GB JSONL, ~3M records
uv run synthetos corpus import-arxiv --path artifacts/arxiv-embedded.jsonl

# If interrupted, resume from the last DB checkpoint
uv run synthetos corpus import-arxiv --path artifacts/arxiv-embedded.jsonl --resume

# (Optional) sanity check the import
uv run synthetos corpus stats

# Backend API
uv run uvicorn apps.api.main:app --port 8000 --reload

# Worker (must be running for the discovery operator chain to advance)
uv run python -m apps.worker

# Frontend
cd apps/web
npm install
npm run dev

# Headless discovery from the CLI (alternative to the web UI)
uv run synthetos discovery run \
  --charter-id <uuid> \
  --query "your scoped problem statement" \
  --view both
```

If local Postgres is not using the repo defaults, set `LAB_DB_URL` first so the API, worker, and Alembic all target the same database. The query-time embedding endpoint configured in `configs/models.yaml` (`embeddings.default.base_url`) must be reachable for hybrid retrieval; without it the internal corpus adapter degrades to lexical-only.
