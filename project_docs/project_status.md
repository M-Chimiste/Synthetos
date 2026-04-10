# Project Status

**Product:** Synthetos (ML Laboratory Co-Scientist)
**Date:** 2026-04-09
**Phase:** 0 — Foundation, Shared State, Skill Skeleton, and API Spine
**Status:** Phase 0 implementation complete (pre-migration, pre-integration-test)

---

## Session Summary

This session completed the full Phase 0 implementation, taking the repository from planning documents only to a working monorepo with all foundation services in place. The work followed a 10-step build sequence derived from the phased implementation plan.

---

## What Was Built

### 1. Repository Skeleton and Tooling (Step 1)

- Monorepo structure: `apps/`, `libs/`, `prompts/`, `skills/`, `configs/`, `tests/`
- `pyproject.toml` — Python 3.12, all backend dependencies, ruff and pyright configuration
- `docker-compose.yml` — Postgres 17 with pgvector extension
- `alembic.ini` + migration framework with autogenerate support
- Frontend scaffold: React 19, Vite, TanStack Query + Router, Tailwind CSS v4
- All linting passes cleanly (`ruff check .`)

### 2. Configuration, Logging, and Core Types (Step 2)

- `libs/core/config.py` — Pydantic Settings loading from `LAB_*` environment variables
- `libs/core/logging.py` — structlog with JSON/console output modes
- `libs/core/types.py` — UUIDv7 identity types (`CharterId`, `CycleId`, `JobId`, etc.) and domain enums (`CycleStatus`, `CharterStatus`, `JobStatus`, `ActorType`, `TrustTier`)
- `libs/core/clock.py` — Abstracted time source for testability

### 3. Database Foundation and Core Schema (Step 3)

- `libs/storage/base.py` — SQLAlchemy `DeclarativeBase` with naming conventions, sync and async engine/session factories
- 6 model modules defining 8 tables:
  - `research_charters`, `research_cycles` — core research entities
  - `jobs` — Postgres-backed job queue with claim indexes
  - `domain_events` — append-only audit trail with charter/cycle/type indexes
  - `skill_definitions`, `skill_bindings` — skill registry
  - `orchestrator_clients`, `api_tokens` — API auth
  - `model_call_records` — LLM usage lineage
- Alembic migration environment configured for autogenerate

### 4. Domain Layer (Step 4)

- `libs/core/state_machine.py` — Cycle state machine with 11 states and validated transitions (`created` → `discovery_ready` → ... → `closed`)
- `libs/core/events.py` — Domain event emitter (append to DB, caller commits)
- `libs/core/operators.py` — `OperatorInput`/`OperatorResult` typed contracts
- `libs/core/research_state.py` — `ResearchStateSnapshot` assembler (aggregates from related tables)
- Pydantic schemas for all CRUD operations: `libs/schemas/charter.py`, `cycle.py`, `events.py`, `jobs.py`, `state.py`, `skills.py`, `common.py`
- Service layer: `charter_service.py`, `cycle_service.py` (create, read, list, update, transition with event emission)

### 5. API Service Foundation (Step 5)

- FastAPI application with 21 routes under `/api/v1`:
  - `POST/GET /charters`, `GET/PATCH /charters/{id}` — charter CRUD
  - `POST/GET /cycles`, `GET /cycles/{id}`, `POST /cycles/{id}/transition` — cycle CRUD with state machine transitions
  - `GET /state/{charter_id}` — assembled research state snapshot
  - `GET /events/stream` — SSE streaming with charter/cycle filtering and `last_event_id` resume
  - `GET /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel` — job list and control
  - `GET /skills`, `GET /skills/{id}`, `POST /skills/discover` — skill catalog
  - `GET /health` — health check
- Exception handlers: `InvalidTransitionError` → 409, `NoResultFound` → 404
- CORS middleware (permissive in dev)
- Auth stub with dev bypass, scope-checking dependency factory
- OpenAPI docs auto-generated at `/docs`

### 6. Worker Runtime and Job Queue (Step 6)

- `libs/core/services/job_service.py` — synchronous job operations with `SELECT ... FOR UPDATE SKIP LOCKED` claim semantics
- `apps/worker/main.py` — worker entry point with unique worker ID, main claim loop, graceful SIGINT/SIGTERM shutdown
- `apps/worker/claimer.py` — job claim wrapper
- `apps/worker/executor.py` — operator dispatch registry with built-in "echo" placeholder operator
- `apps/worker/heartbeat.py` — background heartbeat thread for long-running jobs
- Runnable via `uv run python -m apps.worker`

### 7. Model Gateway (Step 7)

- `libs/adapters/llm/base.py` — `LLMAdapter` protocol with `complete()` and `complete_structured()` methods
- 4 provider adapters:
  - `openai_compat.py` — LMStudio, Ollama, VLLM (httpx-based, no SDK dependency)
  - `anthropic_adapter.py` — Anthropic SDK with tool-use for structured output
  - `openai_adapter.py` — OpenAI SDK with `json_schema` response format
  - `google_adapter.py` — Google GenAI SDK with `response_schema`
- `libs/adapters/llm/router.py` — role-based model router loading from `configs/models.yaml`, lazy adapter creation and caching
- `libs/adapters/embeddings/base.py` — `EmbeddingAdapter` protocol
- `libs/adapters/embeddings/openai_compat.py` — OpenAI-compatible embedding adapter
- `libs/schemas/model_gateway.py` — `ModelRole` enum (13 roles), `CompletionRequest/Response`, `EmbeddingRequest/Response`
- `configs/models.yaml` — role-to-provider mapping configuration

### 8. Skill Foundation (Step 8)

- `libs/skills/parser.py` — parse `skill.md` YAML frontmatter into `SkillManifest`
- `libs/skills/validator.py` — validate trust tier against capabilities, check for hooks.py
- `libs/skills/loader.py` — recursive filesystem discovery from configured paths with trust tier inference
- `libs/skills/registry.py` — upsert/list/get skill definitions in Postgres
- `libs/schemas/skills.py` — `SkillManifest`, `SkillDefinitionRead` schemas
- `skills/example/skill.md` — first-party example skill (verified discoverable)
- API router at `/api/v1/skills` with discover endpoint

### 9. Telemetry and SSE Wiring (Step 9)

- SSE streaming endpoint polling `domain_events` every 500ms with charter/cycle filtering and `last_event_id` resume cursor
- Job cancel endpoint (`POST /jobs/{id}/cancel`) for worker control
- UUIDv7 IDs enable cursor-based streaming without separate sequence columns

### 10. Minimal UI Shell and CLI (Step 10)

**Frontend (React + TypeScript):**
- `apps/web/src/api/client.ts` — typed API client with all endpoint functions
- `apps/web/src/api/hooks.ts` — TanStack Query hooks for every endpoint
- 7 route pages: Dashboard, Charter list/detail/create, Events, Skills
- `EventStream.tsx` — SSE-connected live event feed with connection indicator
- `StatusBadge.tsx` — color-coded status badges
- `Layout.tsx` — app shell with sidebar navigation
- TanStack Router file-based routing with auto-generated route tree

**CLI (Typer):**
- `synthetos charter create|list|show` — charter management
- `synthetos cycle create|list|show` — cycle management
- `synthetos skill discover|list|validate` — skill operations
- `synthetos db init|migrate` — database management (wraps Alembic)

---

## Design Decisions Resolved

| Decision | Resolution |
|----------|-----------|
| Package structure | Single `pyproject.toml` at root; namespace packages |
| Primary key strategy | UUIDv7 (time-sortable, native Postgres UUID type) |
| Apache AGE | Extension created in Docker but no graph features until Phase 2 |
| SSE implementation | Polling-based (500ms); LISTEN/NOTIFY deferred |
| ResearchState | Not a DB model; assembled by service function into Pydantic snapshot |
| Domain events | JSONB payload with event_type discriminator |
| Job queue | `SELECT FOR UPDATE SKIP LOCKED` row-claim on jobs table |
| Structured LLM output | Provider-specific: JSON schema (OpenAI), tool-use (Anthropic), response_schema (Google) |
| Enums | Python 3.12 `StrEnum` throughout |

---

## File Count

| Area | Files |
|------|-------|
| Backend (`apps/api/`, `apps/worker/`, `apps/cli/`) | 21 |
| Core libraries (`libs/`) | 31 |
| Frontend (`apps/web/src/`) | 16 |
| Configuration and infrastructure | 7 |
| Skills | 1 |
| Tests (scaffolding only) | 6 |
| **Total new files** | **~82** |

---

## What Remains Before Phase 0 Exit Criteria Are Met

The foundation code is in place. These steps are needed to reach the Phase 0 exit criteria:

1. **Generate and run the initial Alembic migration** — `docker compose up postgres` then `alembic revision --autogenerate` and `alembic upgrade head`
2. **Integration testing** — verify the full charter → cycle → job → event flow works against a real Postgres instance
3. **Frontend npm install and build verification** — `cd apps/web && npm install && npm run dev`
4. **Model gateway smoke test** — verify at least one hosted and one local model can be invoked through the gateway
5. **End-to-end SSE test** — verify UI receives live events when a worker processes a job

---

## What Is Explicitly Not Built Yet

- Real literature intelligence (Phase 1)
- Real experiment execution or container runtime (Phase 3)
- Strong verification logic (Phase 3)
- Rich skill hooks beyond discovery/validation (Phase 1+)
- Unit and integration test suites (test directory scaffolding exists)
- Production auth (stub only)

---

## How to Run

```bash
# Infrastructure
docker compose up postgres

# Database
uv run alembic revision --autogenerate -m "initial schema"
uv run alembic upgrade head

# Backend API
uv run uvicorn apps.api.main:app --port 8000 --reload

# Worker
uv run python -m apps.worker

# Frontend
cd apps/web && npm install && npm run dev

# CLI
uv run synthetos --help
```
