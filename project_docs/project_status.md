# Project Status

**Project:** ML Laboratory Co-Scientist
**Repository:** `Synthetos`
**Status Date:** 2026-03-22
**Overall Status:** Phase 0 foundation implemented, hardened, and verified — ready for Phase 1

## Current Summary

The repository has moved from planning-only documents through a working Phase 0 bootstrap to a hardened foundation. The control-plane foundation now exists across backend, worker, CLI, shared libraries, config assets, sample skills, and a web dashboard shell. A post-implementation inspection identified and resolved code quality, robustness, and performance issues.

The implemented vertical slice supports:

- creating a research cycle through the API
- persisting the charter, cycle, state snapshots, jobs, events, reports, skills, and orchestrator records
- enqueuing and claiming an `initialize_cycle` job
- running a worker that transitions the cycle to `ready`
- emitting append-only domain events for the cycle lifecycle
- loading first-party `skill.md` packages from the repo
- exposing a skill catalog and report retrieval endpoints
- rendering a Phase 0 web shell and building it successfully
- structured logging with cycle/job/operator correlation
- graceful worker shutdown on SIGTERM/SIGINT
- automatic reclamation of expired job leases
- model invocation recording (table and migration ready for Phase 1)

## Completed Work

### Repository bootstrap

- Created the Phase 0 monorepo shape under `apps/`, `libs/`, `configs/`, `prompts/`, `skills/`, `tests/`, and `scripts/`.
- Added top-level Python and frontend workspace config with `pyproject.toml`, `package.json`, and `pnpm-workspace.yaml`.
- Added local environment/bootstrap assets including `.env.example`, `docker-compose.yml`, `alembic.ini`, `scripts/bootstrap.sh`, and `scripts/check.sh`.

### Backend and shared contracts

- Implemented shared core contracts for:
  - public ID generation
  - cycle state transitions
  - token scopes and actor identity
  - operator input/output types
  - app configuration loading
  - structured logging (`libs/core/logging.py`)
- Added Pydantic schemas for:
  - `ResearchCharter`
  - `ResearchStateSnapshot`
  - `ResearchCycle`
  - `JobRecord`
  - `DomainEventEnvelope`
  - `ModelInvocationRecord`
  - skill and model route types
  - API request/response envelopes

### Storage and orchestration

- Added SQLAlchemy models for Phase 0 durable entities:
  - research charters and cycles
  - state snapshots
  - jobs
  - domain events
  - report bundles
  - approval events
  - skill definitions, versions, bindings, execution records, and validation issues
  - orchestrator clients, tokens, and commands
  - model invocations (added during hardening)
- Added Alembic environment with two migrations:
  - `20260322_000001_phase0.py` — initial schema (15 tables)
  - `20260322_000002_add_model_invocations.py` — model invocation tracking table
- Implemented storage services for:
  - cycle creation
  - event appends
  - report persistence
  - skill syncing
  - cycle detail assembly (with batch job lookup, no N+1 queries)
  - command recording
  - efficient event listing (scoped ID lookups instead of full-table loads)
- Implemented worker/job runtime with:
  - queue enqueue and claim logic (`FOR UPDATE SKIP LOCKED`)
  - `initialize_cycle` operator
  - job success/failure handling with exponential backoff (5s, 10s, 20s)
  - expired lease reclamation on worker startup
  - graceful shutdown via SIGTERM/SIGINT signal handling
  - structured logging for operator start/success/failure
  - state updates and report creation

### API, CLI, and web shell

- Added FastAPI control-plane endpoints for cycles, jobs, skills, reports, health, event streaming, and admin worker/model utilities.
- Added bearer-token auth with seeded local development token storage.
- SSE endpoint uses per-poll sessions (no long-held DB connections).
- Session factory is cached per `db_url` (not recreated per request).
- Added Typer CLI commands for cycle creation/list/show, cycle commands, skills listing, model probing, and worker run-once.
- Added a React + Vite + Tailwind Phase 0 dashboard shell with:
  - cycle creation form
  - cycle list
  - cycle detail panel
  - event timeline
  - report viewer
  - skill catalog

### Skills, prompts, and configs

- Added Phase 0 sample skills:
  - `literature.problem_scoping_support`
  - `literature.title_abstract_triage`
- Added YAML-frontmatter skill parsing and hook export discovery.
- Added placeholder prompt assets under `prompts/`.
- Added initial model route and policy configs under `configs/`.

### Code quality and documentation

- All 90 ruff lint violations resolved (0 remaining).
- Ruff configured with per-file ignores for FastAPI `Depends()` patterns (B008) and Alembic migrations (E501).
- Deduplicated `co-scientist_phased_implementation_plan.md` (958 → 625 lines, removed all duplicate sections).
- Structured logging configured via structlog with console renderer (dev) and JSON renderer (production).

## Verification Status

### Confirmed

- `uv run ruff check .` — 0 violations.
- `uv run pytest tests/` — 7/7 tests passed (2 integration, 5 unit).
- Frontend build succeeds with `pnpm --dir apps/web build`.
- Manual API smoke test succeeded for:
  - cycle creation
  - job enqueue
  - worker run
  - transition to `ready`
  - report retrieval
  - skill catalog retrieval
  - pause/resume cycle commands
  - event listing through the storage/event path

### Issues found and fixed

During initial implementation (by Codex):
- Renamed the SQLAlchemy `ReportBundleModel.metadata` mapped attribute to avoid the reserved declarative `metadata` name while keeping the database column name intact.
- Added a proper `[dependency-groups].dev` section in `pyproject.toml` so `uv sync --dev` installs `pytest`.
- Added `apps/web/src/vite-env.d.ts` so the frontend build recognizes `import.meta.env`.
- Adjusted the integration test setup so config env vars are applied before the FastAPI app is imported.

During hardening pass:
- Fixed session factory being recreated on every API request (now cached per `db_url`).
- Fixed SSE endpoint holding a DB session for the entire stream lifetime (now opens/closes per poll).
- Fixed N+1 queries in `build_cycle_detail()` (batch job ID lookup) and `list_events_after()` (scoped queries instead of full-table loads).
- Added `ModelInvocationRecordModel` ORM model and Alembic migration (schema existed in Pydantic but had no table).
- Added worker graceful shutdown via SIGTERM/SIGINT signal handling.
- Added expired job lease reclamation at worker startup.
- Added exponential backoff for job retries (was hardcoded 5s delay).
- Added structured logging throughout the worker runtime.
- Fixed all 90 ruff lint violations (line length, unused imports, import sorting, f-string cleanup).
- Deduplicated the phased implementation plan document.

### Still pending

- No real Postgres-backed migration run or Docker-backed verification has been completed yet in this repo state.
- SSE was validated structurally but not yet through a dedicated automated streaming test.
- pyright is not yet installed as a dev dependency (listed in tech_context.md but missing from pyproject.toml).
- Alembic is not yet the primary migration path (`Base.metadata.create_all()` still used for dev/test initialization).
- Test coverage is narrow (7 tests — no coverage of auth rejection, cycle commands, invalid transitions, or error paths).

## Current Risks / Gaps

- The app currently relies on `Base.metadata.create_all()` for immediate local initialization; Alembic exists but has not yet been exercised as the primary migration path.
- Test coverage is minimal (7 tests). Key gaps: auth/scope enforcement, cycle commands, state machine edge cases, worker error paths.
- Integration tests use SQLite which differs from production PostgreSQL (JSON column behavior, `FOR UPDATE SKIP LOCKED` not available).
- Model probing exists, but no durable model invocation recording has been wired into operator execution yet (table is ready).

## Recommended Next Steps

1. Run a local Postgres-backed verification pass with Alembic and the API/worker loop.
2. Add pyright as a dev dependency and fix any critical type errors.
3. Switch `initialize_database()` to run Alembic programmatically (keep `create_all()` for tests only).
4. Expand test coverage: auth rejection, cycle commands, invalid state transitions, worker error paths.
5. Begin Phase 1 planning: research intake, arXiv metadata adapter, title/abstract triage operator.
