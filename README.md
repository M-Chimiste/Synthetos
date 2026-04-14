# Synthetos

A single-user ML research system for running end-to-end research loops.
Researchers define problems, triage literature (arXiv), generate hypotheses,
execute experiments in GPU-capable containers, verify results, and learn
across cycles via a canonical pattern memory.

**Status:** Phases 0–6 are code-level complete. See
[`project_docs/project_status.md`](project_docs/project_status.md) for the full
per-phase changelog and [`project_docs/co_scientist_phased_implementation_plan.md`](project_docs/co_scientist_phased_implementation_plan.md)
for the roadmap.

## What's in the box

| Phase | Capability |
|---|---|
| 0 | Postgres schema, FastAPI control plane under `/api/v1`, worker, React dashboard, skills |
| 1 | Discovery pipeline (internal corpus + arXiv live, Stable/Discovery views, rerank with graceful fallback) |
| 2 | Full paper analysis (HTML/PDF ingest, typed paper graph, graph-aware QA, coverage checks, evidence extraction) |
| 3 | Hypothesis portfolio, protocol compiler, isolated run execution, baseline verification, postmortems |
| 4 | Auto-remediation, directional signal, frontier tracking, next-step recommendations |
| 5 | Autonomous loop with budgets, configurable gates, hypothesis lifecycle, completion reports |
| 6 | Cross-charter pattern memory, runtime skill trust enforcement, stale-job reclaim, pilot harness |

## Prerequisites

- Python 3.12+
- Node.js 20+
- Docker Desktop (Postgres + pgvector + AGE; experiment containers for Phase 3)
- (Optional) A local OpenAI-compatible LLM endpoint (LMStudio / Ollama /
  vLLM) on port 11434, plus an Anthropic API key for hosted roles. See
  [`configs/models.yaml`](configs/models.yaml).
- (Optional for Phase 6 GPU pilot) An Nvidia or Apple Silicon GPU with ≥ 8 GB VRAM.

## Local startup

1. Install Python dependencies:

```bash
uv sync --extra dev
```

2. Start Postgres:

```bash
docker compose up -d postgres
```

3. Apply migrations (runs all phases 0–6):

```bash
uv run synthetos db init
```

If your local Postgres uses a different host, port, user, or database name,
set `LAB_DB_URL` first so Alembic and the app target the same instance.

4. Start the API:

```bash
uv run uvicorn apps.api.main:app --reload
```

5. Start the worker in a second terminal:

```bash
uv run python -m apps.worker
```

The worker handles all phases' operators plus the Phase 6 periodic loop
(stale-job reclaim + gated pattern decay).

6. Start the web app in a third terminal:

```bash
cd apps/web
npm install
npm run dev
```

The dashboard is at `http://localhost:5173` and the API at
`http://localhost:8000`. OpenAPI docs live at `http://localhost:8000/docs`.

## Dashboard surface

Routes exposed by the React app:

- **Dashboard** (`/`) — charter list, active jobs
- **Charters** (`/charters`) — create + drive a research charter; per-charter discovery, analysis, experiment, and autonomy panels
- **Events** (`/events`) — live SSE event stream across charters
- **Patterns** (`/patterns`) — Phase 6 canonical pattern list with filters, bulk `Consolidate now` / `Run decay` actions, plus a detail view (`/patterns/$patternId`) with approve / reject / trust-tier curation
- **Cycle timeline** (`/cycles/$cycleId/timeline`) — phase-grouped live event stream for one cycle
- **Skills** (`/skills`) — skill registry + discovery

Reports (discovery, analysis, autonomy completion) render rich markdown via
`react-markdown`.

## CLI

The `synthetos` CLI mirrors the API surface. Key subcommands:

```bash
uv run synthetos charter create "My research question"
uv run synthetos cycle create --charter-id <uuid>
uv run synthetos discovery start --charter-id <uuid> --query "..."
uv run synthetos analysis start --session-id <uuid>
uv run synthetos experiment start --run-id <uuid>
uv run synthetos autonomy policy set --cycle-id <uuid> --mode autonomous
uv run synthetos patterns list
uv run synthetos patterns consolidate
uv run synthetos patterns decay --force
uv run synthetos pilot list
uv run synthetos pilot run ml_baseline_small
uv run synthetos pilot evaluate ml_baseline_small <cycle_uuid>
uv run synthetos pilot compare <left> <right>
```

## Phase 6 pilot fixtures

Bundled fixtures under `configs/problems/` exercise the full chain:

- **`ml_baseline_small`** — `ci_safe`, CPU-only, < 5 min, supervised. Smoke fixture for CI.
- **`ml_sklearn_iris`** — `workstation_cpu`, autonomous, 10-run / 30-min budget. Classical tabular classification.
- **`ml_vision_tiny`** — `workstation_gpu`, autonomous, 6-run / 2-hour budget. Small convnet on a public image benchmark. **Not CI-safe.**

Each fixture is contract-validated
([`libs/pilot/fixture.py`](libs/pilot/fixture.py)) before a run starts.
`synthetos pilot run` creates (or reuses) a `pilot:<problem_id>` charter so
repeat runs share one pattern-learning history; the worker then drives the
full chain asynchronously. `synthetos pilot evaluate` grades the cycle
against the fixture's `expected.yaml` and writes
`artifacts/pilot/<problem_id>/<timestamp>/evaluation.{json,md}`.

## Cross-charter pattern memory (Phase 6)

Canonical patterns are consolidated from postmortems, remediation actions,
directional signals, frontiers, and loop decisions into typed rows under
`canonical_patterns`. Consolidation runs as the last side effect of cycle
close (async, failure-isolated) and on demand via the CLI / API. High-
confidence `auto`-tier patterns inject automatically into hypothesis
generation, auto-remediation, and loop decisions; `curated` patterns
require an explicit `PatternApproval`; decay demotes stale patterns
(`auto → curated → deprecated`).

## Quality gates

Run before shipping:

```bash
uv run ruff check .
uv run pyright
uv run pytest
cd apps/web && npm run build
```

Current green state: **ruff clean, pyright 0 errors, 289 pytest passed**
(unit + contract), web build OK.

## Key configuration

All `LAB_*` env vars (prefix stripped in
[`libs/core/config.py`](libs/core/config.py)):

| Var | Default | Purpose |
|---|---|---|
| `LAB_ENV` | `dev` | `dev` bypasses browser auth; `prod` requires bearer tokens |
| `LAB_DB_URL` | local docker creds | Postgres DSN (psycopg) |
| `LAB_DATA_ROOT` | `data` | Artifact / report / workspace root |
| `LAB_MODEL_CONFIG` | `configs/models.yaml` | Role → provider / model routing |
| `LAB_SKILL_PATHS` | `skills` | Colon-separated skill discovery roots |
| `LAB_JOB_HEARTBEAT_TIMEOUT_S` | `120` | Stale-job reclaim threshold |
| `LAB_JOB_MAX_RECLAIMS` | `3` | Reclaims before a job is force-failed |
| `LAB_WORKER_PERIODIC_TICK_S` | `30` | Worker periodic-loop interval |
| `LAB_PATTERN_DECAY_INTERVAL_H` | `24` | Minimum interval between auto-enqueued decay jobs |
| `LAB_PATTERN_MAX_STALENESS_DAYS` | `90` | Staleness window past which auto patterns demote |

Per-cycle pattern and skill policy lives in `ResearchCycle.config`:

```yaml
patterns:
  min_confidence_auto: 0.7
  max_staleness_days: 90
  cross_charter_weight_boost: 1.15
  cross_charter_only: false
  injection_limit: 10
skills:
  require_first_party_for_execution: false
```

## Notes

- Apache AGE is optional — Synthetos falls back to relational tables when AGE is unavailable.
- Browser auth is bypassed in `LAB_ENV=dev`; production requires bearer tokens with scoped access (`patterns.read`, `patterns.write`, `cycles.write`, etc.).
- The arXiv metadata corpus is already downloaded and embedded (`gte-modernbert`, 768-dim). Full text is fetched only for shortlisted papers.
- Only one active charter at a time is assumed due to single-GPU constraints.
