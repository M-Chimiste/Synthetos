# Project Status

**Product:** Synthetos (ML Laboratory Co-Scientist)  
**Date:** 2026-04-10  
**Phase:** 0 — Foundation, Shared State, Skill Skeleton, and API Spine  
**Status:** Phase 0 remediation implemented; codebase is build-clean and test-clean, with live DB bootstrap still pending local environment alignment

---

## Session Summary

This session closed the main Phase 0 implementation gaps identified in review. The repository already had the Phase 0 skeleton in place; the work here focused on making that foundation actually runnable, contract-consistent, and verifiable.

The main outcomes were:

- Added the initial Alembic revision and wired Alembic to use runtime settings
- Replaced the auth/scope stub with real token validation and scope enforcement, while preserving dev bypass
- Added pause/resume job controls and `paused` job state
- Fixed the worker path so operator-emitted events are persisted to `domain_events`
- Fixed SSE delivery so the React client receives live updates correctly
- Reconciled frontend API contracts with backend schemas
- Restored reproducible frontend builds and added focused unit coverage for the new Phase 0 behaviors

---

## What Was Added or Corrected

### 1. Database Bootstrap and Migration Readiness

- Added initial Alembic revision:
  - `libs/storage/migrations/versions/20260410_000001_phase0_initial_schema.py`
- Updated `libs/storage/migrations/env.py` to read the database URL from `LAB_DB_URL` / runtime settings instead of relying only on the static `alembic.ini` default
- Preserved `synthetos db init` as the canonical migration entry point
- Updated `README.md` with a Phase 0 bootstrap flow and local DB configuration note

### 2. Backend Contract Alignment

- Reconciled API and frontend expectations for:
  - cycles
  - research state snapshot
  - jobs
  - skills
- Kept the backend schema as the source of truth and updated the web client to match it
- Narrowed the UI to Phase 0-supported fields rather than carrying forward unsupported placeholders like paper/hypothesis/experiment counters
- Made skill discovery return a stable response shape:
  - `discovered`
  - `items`

### 3. Worker, Events, and Control Hooks

- Added `paused` to `JobStatus`
- Added job control endpoints:
  - `POST /api/v1/jobs/{id}/pause`
  - `POST /api/v1/jobs/{id}/resume`
  - existing `cancel` path now works alongside pause/resume
- Updated worker execution flow so it now:
  - resolves the real charter context from the attached cycle
  - persists operator-emitted events into `domain_events`
  - applies the minimal Phase 0 durable state patch for cycle status transitions
  - emits worker lifecycle events such as `job_started`, `job_completed`, `job_failed`, and pause/cancel acknowledgements
- Refined sync job service helpers so worker-side transitions can be committed coherently within the calling flow

### 4. SSE and UI Telemetry

- Changed the SSE endpoint to emit default message frames instead of custom-named events
- Updated the React event stream consumer to parse the actual event payload coming from the backend
- Preserved `last_event_id` resume support
- Updated the charter detail view and dashboard shell to show:
  - current aggregate state
  - active jobs
  - recent events
  - live event stream

### 5. Auth and Scope Enforcement

- Replaced the earlier auth stub with DB-backed token validation against `api_tokens`
- Enforced:
  - bearer token presence outside dev
  - revoked token rejection
  - expiry rejection
  - disabled client rejection
  - route-level scope checks
- Preserved dev bypass when `LAB_ENV=dev`
- Applied scope dependencies across the Phase 0 API surface:
  - charters
  - cycles
  - state
  - jobs
  - skills
  - events

### 6. Build, Type, and Quality Remediation

- Fixed the Phase 0 pyright errors in:
  - model router
  - cycle service
  - skill parser
  - worker typing edges introduced by remediation work
- Refreshed frontend dependencies and lockfile so a fresh `npm install` now supports a successful production build
- Added focused unit tests for:
  - auth and scope behavior
  - SSE frame shape
  - worker helper persistence/state transition behavior

---

## Files Touched in This Remediation Pass

### Backend and Worker

- `apps/api/auth.py`
- `apps/api/routers/charters.py`
- `apps/api/routers/cycles.py`
- `apps/api/routers/events.py`
- `apps/api/routers/health.py`
- `apps/api/routers/jobs.py`
- `apps/api/routers/skills.py`
- `apps/api/routers/state.py`
- `apps/worker/main.py`
- `libs/core/events.py`
- `libs/core/services/cycle_service.py`
- `libs/core/services/job_service.py`
- `libs/core/types.py`
- `libs/schemas/skills.py`
- `libs/skills/parser.py`
- `libs/adapters/llm/base.py`

### Database and Docs

- `libs/storage/migrations/env.py`
- `libs/storage/migrations/versions/20260410_000001_phase0_initial_schema.py`
- `README.md`

### Frontend

- `apps/web/src/api/client.ts`
- `apps/web/src/api/hooks.ts`
- `apps/web/src/components/EventStream.tsx`
- `apps/web/src/components/StatusBadge.tsx`
- `apps/web/src/routes/index.tsx`
- `apps/web/src/routes/charters/$charterId.tsx`
- `apps/web/src/routes/skills.tsx`
- `apps/web/package-lock.json`

### Tests

- `tests/unit/test_auth.py`
- `tests/unit/test_event_stream.py`
- `tests/unit/test_worker_main.py`

---

## Verification Status

The repository now passes the core Phase 0 quality gates:

- `uv run ruff check .` — passes
- `UV_CACHE_DIR=/tmp/uv-cache uv run pyright` — passes
- `uv run pytest` — passes (`9 passed`)
- `cd apps/web && npm run build` — passes
- `cd apps/web && npx tsc -b` — passes

Additional verification performed:

- `npm install` was re-run in `apps/web` and the lockfile was updated
- `synthetos db init` was exercised far enough to verify that Alembic now uses runtime DB settings rather than only the hard-coded `alembic.ini` URL

---

## What Remains Before Phase 0 Can Be Called Fully Verified

The remaining gap is now primarily environment-level rather than code-level:

1. **Live database bootstrap against the intended local Postgres**
   - `synthetos db init` is wired correctly, but local verification was blocked by machine-specific DB state:
     - the reachable Postgres on `localhost:5432` does not currently contain the expected `synthetos` role
     - the repo Docker Postgres could not be started because port `5432` is already in use
2. **End-to-end charter → cycle → job → event smoke flow against a real running Postgres**
   - the code path is implemented, but full integration validation still depends on the local DB environment being aligned
3. **Optional model gateway smoke test**
   - still useful for confidence, but no longer a blocker for the Phase 0 foundation itself

---

## What Is Explicitly Still Out of Scope

- Real literature retrieval and analysis logic (Phase 1)
- Real experiment execution/runtime containers (Phase 3)
- Strong verification logic (Phase 3)
- Rich skill execution hooks beyond discovery and registry support (Phase 1+)
- Production-grade auth lifecycle or admin management UI
- LISTEN/NOTIFY-based streaming; SSE remains polling-based in Phase 0

---

## Current Runbook

```bash
# Python dependencies
uv sync --extra dev

# Database
docker compose up -d postgres
uv run synthetos db init

# Backend API
uv run uvicorn apps.api.main:app --port 8000 --reload

# Worker
uv run python -m apps.worker

# Frontend
cd apps/web
npm install
npm run dev
```

If local Postgres is not using the repo defaults, set `LAB_DB_URL` first so the API, worker, and Alembic all target the same database.
