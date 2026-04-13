# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Synthetos** is a single-user ML research system for running end-to-end research loops. Researchers define problems, triage literature (arXiv), generate hypotheses, execute experiments in GPU-capable containers, verify results, and prepare submissions.

Design docs live in `project_docs/`. The phased implementation plan is in `project_docs/co_scientist_phased_implementation_plan.md`.

## Development Commands

```bash
# Infrastructure
docker compose up -d postgres          # Start Postgres (pgvector + AGE extensions)

# Backend
uv sync --extra dev                     # Install all deps including dev
uv run synthetos db init                # Run Alembic migrations
uv run uvicorn apps.api.main:app --reload  # API server (port 8000)
uv run python -m apps.worker           # Worker process (separate terminal)

# Frontend
cd apps/web && npm install && npm run dev  # Vite dev server (port 5173)

# Quality
uv run ruff check .                     # Lint
uv run ruff format .                    # Format
uv run pyright                          # Type check
uv run pytest                           # All backend tests
uv run pytest tests/unit/test_foo.py -k test_name  # Single test
cd apps/web && npm run build            # Frontend type check + build
cd apps/web && npm run test             # Frontend tests (vitest)
```

## Architecture

### Runtime Model

- **Postgres** runs in Docker via docker-compose. Extensions (pgvector, Apache AGE) are loaded by `docker/init-extensions.sql`. AGE is optional—falls back to relational tables if unavailable.
- **API, worker, CLI** run on the host with hot reload. They share `libs/` but run as separate processes.
- **API is async** (async SQLAlchemy sessions); **worker and CLI are sync** (sync session factory). Don't mix session types.
- **Experiment containers** (future) will be spawned as sibling Docker containers with GPU passthrough.

### Core Pattern: Queue-Driven Operator Execution

The system is a **job queue + operator** architecture, not an agent framework:

1. **API/CLI** receives user requests → calls a **service** (`libs/core/services/`) → enqueues a **job** in Postgres.
2. **Worker** polls for jobs using `SELECT FOR UPDATE SKIP LOCKED` (ordered by priority DESC, created_at), claims one, builds an `OperatorInput`, and calls the appropriate **operator**.
3. **Operators** (`libs/discovery/operators/`, `libs/analysis/operators/`) do the actual work (LLM calls, data processing) and return an `OperatorResult` containing events, state patches, and artifacts.
4. **Worker** persists events, applies state patches, and updates job status—all atomically. A heartbeat thread (5s interval) signals liveness during execution.

Key contracts are in `libs/core/operators.py`: `OperatorInput` (frozen dataclass) and `OperatorResult` (events + state_patch + artifacts + summary).

### Services Convention

Services in `libs/core/services/` emit events within the session but **do not commit**—the caller is responsible for committing the transaction. This keeps service methods composable.

### State Machine

Cycles follow a strict DAG of status transitions defined in `libs/core/state_machine.py`:
`created → discovery_ready → discovery_screened → analysis_ready → evidence_ready → portfolio_ready → protocol_ready → running → verifying → reporting → closed`

The worker validates transitions before applying them.

### Event Sourcing

All state changes emit `DomainEvent` rows (`libs/core/events.py`, `libs/storage/models/events.py`). Events carry charter_id, cycle_id, actor info, and JSON payloads. The API exposes an SSE stream for live telemetry.

### LLM Integration

`libs/adapters/llm/` implements a hexagonal adapter pattern:
- `base.py` defines the `LLMAdapter` protocol: `complete()`, `complete_structured(response_model)`, `close()`
- `router.py` (`ModelRouter`) reads `configs/models.yaml`, maps roles to providers, lazily instantiates and caches adapters
- Provider adapters: `anthropic_adapter.py`, `openai_adapter.py`, `openai_compat.py` (for LMStudio/Ollama/VLLM), `google_adapter.py`
- Model roles (defined in `configs/models.yaml`): planning, retrieval_synthesis, metadata_analysis, coding, summarization, evaluation, report_writing, hypothesis_generation, protocol_drafting

### Skill System

File-based skill discovery: `libs/skills/loader.py` walks `LAB_SKILL_PATHS` directories for `skill.md` files with YAML frontmatter. Skills are validated (`libs/skills/validator.py`), registered (`libs/skills/registry.py`), and tracked with SHA-256 content hashes. Trust tiers: `first-party` vs `user-local`.

### Configuration

`libs/core/config.py` uses pydantic-settings with `LAB_` env prefix and `.env` fallback. Singleton via `get_settings()`. Key settings: `LAB_DB_URL`, `LAB_ENV` (dev bypasses browser auth), `LAB_DATA_ROOT`, `LAB_MODEL_CONFIG`, `LAB_SKILL_PATHS`.

### Database

PostgreSQL with pgvector (768-dim embeddings) and Apache AGE (graph storage). Alembic migrations in `libs/storage/migrations/versions/`. SQLAlchemy models in `libs/storage/models/`. Dual session factories: async for API, sync for worker/CLI. All primary keys use UUIDv7 (time-sortable, via `uuid_utils`).

The async DB URL requires `postgresql+psycopg://` prefix (not plain `postgresql://`).

## Monorepo Layout

- `apps/api/` — FastAPI server, routers mount under `/api/v1`, auth in `auth.py`, deps in `deps.py`
- `apps/worker/` — Polling worker with `claimer.py` (job locking), `heartbeat.py`, `executor.py` (operator dispatch)
- `apps/cli/` — Typer CLI, entry point is `synthetos` command, subcommands in `commands/`
- `apps/web/` — React 19 + TypeScript + Vite + TanStack Router (file-based, auto-generates `routeTree.gen.ts`) + TanStack Query + Tailwind CSS 4
- `libs/schemas/` — Pydantic v2 request/response models (API boundary)
- `libs/core/` — Domain logic: config, events, operators, state machine, services
- `libs/storage/` — SQLAlchemy models, Alembic migrations, session management
- `libs/adapters/` — Hexagonal adapters: `llm/`, `embeddings/`, `sources/`, `reranker/`, `ingestion/`, `graph/`
- `libs/discovery/` — Discovery loop operators and supporting logic (ranking, evaluation, views, metadata analysis)
- `libs/analysis/` — Analysis loop operators (coverage, graph QA, reports)
- `libs/skills/` — Skill loader, parser, validator, registry
- `skills/` — First-party skill.md packages
- `configs/` — YAML configs (models.yaml, discovery/, policies/, problems/)
- `prompts/` — Versioned prompt assets (not yet populated)

### API Error Mapping

The API maps domain exceptions to HTTP status codes: `InvalidTransitionError` → 409, `NoResultFound` → 404. CORS is open in dev, locked down in prod.

## Key Design Principles

- **Operator-over-shared-state**: typed operators read/write shared `ResearchState`—no agent messaging or hidden prompt history.
- **Hexagonal architecture**: all external systems behind adapter interfaces in `libs/adapters/`. Core domain code must not import vendor SDKs.
- **Metadata-first triage**: title+abstract screening before full text. HTML-first full-text path, PDF+Docling as fallback.
- **Deterministic core, probabilistic edge**: LLMs for synthesis/ideation; Python+config for state, policy, lineage.
- **One active charter at a time** due to GPU constraints.

## Tooling Config

- **ruff**: line-length 100, target py312. `B008` suppressed in `apps/api/` and `apps/cli/` (idiomatic FastAPI/Typer defaults). isort knows `apps` and `libs` as first-party.
- **pyright**: standard mode, includes `apps` and `libs`, excludes `tests`.
- **pytest**: asyncio_mode = auto, testpaths = tests.

## Internal Corpus

The arXiv metadata corpus is already downloaded and embedded (gte-modernbert, 768-dim). It is incrementally updated via harvesting. Full text is fetched only for shortlisted papers.
