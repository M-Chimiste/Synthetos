# Synthetos Phase 0 Bootstrap

This repo now has the minimum Phase 0 foundation wired up:

- Postgres-backed schema managed by Alembic
- FastAPI control plane under `/api/v1`
- Worker process with durable jobs and domain events
- React dashboard shell for charters, cycles, skills, jobs, and live telemetry

## Prerequisites

- Python 3.12+
- Node.js 20+
- Docker Desktop (for local Postgres)

## Local startup

1. Install Python dependencies:

```bash
uv sync --extra dev
```

2. Start Postgres:

```bash
docker compose up -d postgres
```

3. Apply the Phase 0 schema:

```bash
uv run synthetos db init
```

If your local Postgres uses a different host, port, user, or database name, set `LAB_DB_URL` first so Alembic and the app target the same instance.

4. Start the API:

```bash
uv run uvicorn apps.api.main:app --reload
```

5. Start the worker in a second terminal:

```bash
uv run python -m apps.worker
```

6. Start the web app in a third terminal:

```bash
cd apps/web
npm install
npm run dev
```

The dashboard will be available at `http://localhost:5173`, and the API will be available at `http://localhost:8000`.

## Smoke flow

1. Open the dashboard and create a charter.
2. Open that charter and create a cycle.
3. Confirm the charter page shows:
   - the new cycle in the cycle table
   - the current state snapshot
   - the live event stream updating without a refresh
4. To verify the worker path, insert a simple test job for the cycle from `psql`:

```sql
INSERT INTO jobs (
  id,
  cycle_id,
  job_type,
  status,
  payload,
  priority,
  created_at
) VALUES (
  '018f0e55-f0cf-7a44-9833-7b922df59f01',
  '<your-cycle-id>'::uuid,
  'echo',
  'pending',
  '{"message":"phase0 smoke test"}'::jsonb,
  0,
  now()
);
```

5. Confirm the worker claims the job, completes it, and the event stream shows `job_started` and `job_completed`.

## Quality checks

Run these before shipping Phase 0 changes:

```bash
uv run ruff check .
UV_CACHE_DIR=/tmp/uv-cache uv run pyright
uv run pytest
cd apps/web && npm run build
```

## Notes

- Apache AGE remains optional in Phase 0 and is not required for bootstrap.
- Browser auth is bypassed in `LAB_ENV=dev`, which is the intended local workflow for this phase.
