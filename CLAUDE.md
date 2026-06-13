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
cd apps/web && npm run lint              # Frontend lint (ESLint)
cd apps/web && npm run build            # Frontend type check + build
cd apps/web && npm run test             # Frontend tests (vitest)
```

## Architecture

### Runtime Model

- **Postgres** runs in Docker via docker-compose. Extensions (pgvector, Apache AGE) are loaded by `docker/init-extensions.sql`. AGE is optional—falls back to relational tables if unavailable.
- **API, worker, CLI** run on the host with hot reload. They share `libs/` but run as separate processes.
- **API is async** (async SQLAlchemy sessions); **worker and CLI are sync** (sync session factory). Don't mix session types.
- **Experiment containers** are spawned as sibling Docker containers with GPU passthrough (`libs/adapters/container/docker_runner.py`, used by `libs/execution/`).

### Core Pattern: Queue-Driven Operator Execution

The system is a **job queue + operator** architecture, not an agent framework:

1. **API/CLI** receives user requests → calls a **service** (`libs/core/services/`) → enqueues a **job** in Postgres.
2. **Worker** polls for jobs using `SELECT FOR UPDATE SKIP LOCKED` (ordered by priority DESC, created_at; jobs with a future `not_before` are skipped), claims one, builds an `OperatorInput`, and calls the appropriate **operator**.
3. **Operators** (`libs/discovery/operators/`, `libs/analysis/operators/`) do the actual work (LLM calls, data processing) and return an `OperatorResult` containing events, state patches, and artifacts.
4. **Worker** persists events, applies state patches, and updates job status—all atomically. A `JobSupervisor` thread (`apps/worker/heartbeat.py`, 5s interval) heartbeats, polls for cancellation, and watches the wall-clock deadline during execution.

Key contracts are in `libs/core/operators.py`: `OperatorInput` (frozen dataclass) and `OperatorResult` (events + state_patch + artifacts + summary + optional `failure` detail).

### Job Reliability: Retry, Cancellation, Timeouts

- **Error taxonomy** (`libs/core/errors.py`): operator exceptions classify as `transient | permanent | cancelled | timeout` via `classify_exception()`. Unknown types are **permanent** (never blindly re-run an hour-long job on a logic bug); operators opt in to retry by raising `RetryableOperatorError`; other layers register transient types via `register_transient()`.
- **Job retry**: transient/timeout failures requeue with exponential backoff (`Job.attempt_count`/`max_attempts`/`not_before`; settings `LAB_JOB_DEFAULT_MAX_ATTEMPTS` etc.). Session-failure side effects and goal-advance run only on FINAL failure. Full tracebacks land in `Job.error_detail` (see `synthetos jobs show <id>`).
- **Kill switch**: `POST /api/v1/jobs/{id}/cancel` (or `synthetos jobs cancel <id>`) sets `cancel_requested` for running jobs; the supervisor trips a `CancelToken` (`libs/core/run_context.py`, exposed via ContextVar) within 5s; the LLM reliability layer cancels the in-flight HTTP request (vLLM/llama.cpp abort generation on disconnect); the operator unwinds with `OperationCancelled` and the job is marked cancelled, not failed.
- **Per-job deadline**: `LAB_JOB_DEFAULT_TIMEOUT_S` (4h default, per-type overrides) trips the same token with reason=timeout (retryable).

### LLM Reliability Layer

ALL LLM calls flow through `ModelRouter.complete/complete_structured` → `ReliableLLMClient` (`libs/adapters/llm/reliability.py`). Adapters are deliberately dumb (one provider request, light JSON repair, typed `LLMValidationError`/`LLMTruncationError`); the reliability layer owns, per call:

- transport retry with backoff/jitter (timeouts on a smaller separate budget),
- truncation re-call (`finish_reason == "length"` → grow max_tokens before last-resort brace repair),
- validation feedback retry (re-prompt with the bad output + pydantic error; original messages stay a byte-identical prefix for vLLM prefix-cache reuse),
- per-endpoint concurrency caps (`providers.<name>.max_concurrent_requests`; default 2 for local servers),
- opt-in per-role `fallback:` chain (e.g. escalate one call to Anthropic after local budgets exhaust),
- cancellation racing, and one `llm_calls` transcript row per logical call.

Per-role knobs in `configs/models*.yaml`: `timeout_s`, `context_window` (MUST match the serving window, not the model card), `retry: {...}` (deep-merged with defaults), `sampling: {top_p, seed, stop}`, `fallback: {...}`. The `llm_calls` table records role/model/outcome/attempts/latency/tokens (prompt text only when `LAB_LLM_LOG_PROMPTS=true`); `libs/core/services/llm_call_service.role_success_rates()` aggregates per-role success rates.

### Prompt Templates

System prompts live in `prompts/<domain>/<name>/v<N>.md` (frontmatter + jinja2 body), loaded via `libs/prompts` (`render_prompt("ideation.hypothesis_generate", ...)`). Each structured-output prompt carries ONE compact JSON example that `tests/unit/test_prompt_schema_sync.py` validates against the declared pydantic `response_schema` — change prompt and schema together. Per-model variants (`v<N>.<model-slug>.md`) override the base file when the caller passes a model. See `prompts/README.md`.

User messages stay code-assembled and are trimmed to the role's `context_window` via `libs/core/tokens.py` (`ContextSection` + `trim_to_budget` + `prompt_budget`) — priority 0 sections are never dropped.

### Protocol Compile Decomposition

`protocol_compile` runs a per-hypothesis chain (`libs/protocols/operators/compile.py`): one flat `ExperimentPlan` call (role `protocol_drafting`), then one `CodePlanOutput` call (role `coding`); the Dockerfile is synthesized deterministically from dependencies (no LLM) unless a custom build is needed. A failed card chain is skipped, not fatal. `max_specs_per_compile` (cycle protocol config, default 2) bounds wall-time; the loop path compiles exactly one spec.

### Services Convention

Services in `libs/core/services/` emit events within the session but **do not commit**—the caller is responsible for committing the transaction. This keeps service methods composable.

### State Machine

Cycles follow a strict DAG of status transitions defined in `libs/core/state_machine.py`:
`created → discovery_ready → discovery_screened → analysis_ready → evidence_ready → portfolio_ready → protocol_ready → running → verifying → (loop_deciding) → reporting → closed`

The worker validates transitions before applying them.

`loop_deciding` is a Phase 5 state entered only in autonomous mode — the `recommend` operator targets `loop_deciding` (instead of `reporting`) when `ResearchCycle.config.autonomy.mode == "autonomous"`, and the `loop_decide` operator transitions to `running` (to continue/vary/pivot) or `reporting` (to stop). Supervised mode skips `loop_deciding` entirely.

### Autonomous Loop (Phase 5)

Opt-in via `ResearchCycle.config.autonomy.mode = "autonomous"`. When set, the `recommend` operator enqueues a `loop_decide` job instead of terminating at `reporting`. `loop_decide` consumes the `RunRecommendation` and acts on it:

- `continue_current` → new `RunRecord` for the same spec → `execution_setup`
- `parameter_variation` → enqueue `protocol_compile` with `variation_context` + `from_loop=true`
- `hypothesis_pivot` → deprioritize current card, select next viable card by rank, enqueue execution or compilation
- `halt` / budget exhausted / gate triggered / no viable hypotheses → enqueue `loop_report`, transition to `reporting`

Budget tracking (`libs/autonomy/budget.py`) covers run count, wall-clock time, and runs-per-hypothesis — dollar-cost budgets are deferred. Checkpoint gates (`libs/autonomy/gates.py`) are all off by default; when one fires, `loop_decide` sets its own Job row to `JobStatus.paused` and the worker's existing pause-handling logic takes over. The `POST /cycles/{id}/autonomy/resume` endpoint re-enqueues the paused job.

Hypothesis lifecycle statuses (`active|promising|stalled|deprioritized|validated`) are set by `loop_decide` via direct ORM writes — the `HypothesisCardUpdate` PATCH schema is unchanged and still only accepts `candidate|selected|rejected|deferred`. Phase 5 statuses are system-managed.

Spec repetition detection (`libs/autonomy/repetition.py`) fingerprints `(code_plan, controls, metrics, baseline)` and escalates `continue_current → vary_parameters` on exact duplicates, or to `pivot_hypothesis` on 3+ near-duplicates in a row. Context summaries are generated every `summary_interval` runs (default 5) and fed into variation prompts.

### Pattern Memory (Phase 6 / "Mnemosyne")

Cross-cycle distilled memory in `libs/patterns/`. The `consolidate_patterns` operator mines completed-cycle artifacts (`FailurePostmortem`, `RemediationAction`, `MetricFrontier`, `LoopDecision`, `HypothesisCard`) into `CanonicalPattern` rows, deduplicated by a stable `content_key` (SHA-256 of normalized attributes per pattern type: failure / remediation / signal_trajectory / successful_line / retrieval_heuristic) via upsert, with provenance in `PatternObservation`. Patterns carry a 768-dim embedding for semantic retrieval and a `confidence` that the `decay_patterns` operator ages over time.

Operators bias their prompts by calling `inject_patterns()` (`libs/patterns/injection.py`) — callers today include discovery search, ideation generate, verification check, remediation, and `loop_decide`. Injection applies an approval policy: `auto` patterns pass when `effective_confidence >= min_confidence_auto` (0.7 default); `curated` patterns require a `PatternApproval` row (charter-scoped or global).

`decay_patterns` is enqueued by the worker's periodic loop (`apps/worker/periodic.py`), gated idempotently via `PeriodicJobState` (`pattern_decay_interval_h`). That same loop reclaims stale jobs whose worker died mid-execution. Local-model presets for this workflow live in `configs/models.mnemosyne.yaml` (and `models.mnemosyne-e2e.yaml`).

### Goal Mode

`libs/goals/` adds multi-attempt research objectives on top of the cycle machinery. A `ResearchGoal` (with JSONB `success_criteria`) spawns successive `GoalAttempt` rows, each bound 1:1 to a cycle. Operators: `goal_advance` (start the next attempt cycle), `goal_evaluate` (grade a finished cycle against the criteria), `goal_report` (synthesize the cross-attempt ledger). Goal-advance side effects fire only on a job's FINAL failure (see Job Reliability). Service logic is in `libs/core/services/goal_service.py`; drive it via `synthetos goal`.

### Pilot Harness

`libs/pilot/` runs seeded problems through the full loop end-to-end for correctness testing. `fixture.py` loads/validates a `configs/problems/<id>/` fixture (charter + autonomy + seeds + `expected.yaml`), `runner.py` idempotently creates the charter/cycle and enqueues discovery, and `evaluation.py` grades final cycle state against `expected.yaml`. Driven by `synthetos pilot run|evaluate <problem_id>`.

### Event Sourcing

All state changes emit `DomainEvent` rows (`libs/core/events.py`, `libs/storage/models/events.py`). Events carry charter_id, cycle_id, actor info, and JSON payloads. The API exposes an SSE stream for live telemetry.

### LLM Integration

`libs/adapters/llm/` implements a hexagonal adapter pattern:
- `base.py` defines the `LLMAdapter` protocol: `complete()`, `complete_structured(response_model)`, `close()`
- `router.py` (`ModelRouter`) reads `configs/models.yaml`, maps roles to providers, lazily instantiates and caches adapters
- Provider adapters: `anthropic_adapter.py`, `openai_adapter.py`, `openai_compat.py` (for LMStudio/Ollama/VLLM), `google_adapter.py`
- Model roles (defined in `configs/models.yaml`): planning, retrieval_synthesis, metadata_analysis, coding, summarization, evaluation, report_writing, hypothesis_generation, protocol_drafting. Some roles (metadata_analysis, coding, summarization) default to `local` provider (Ollama/vLLM on port 11434); others use Anthropic.

### Skill System

File-based skill discovery: `libs/skills/loader.py` walks `LAB_SKILL_PATHS` directories for `skill.md` files with YAML frontmatter. Skills are validated (`libs/skills/validator.py`), registered (`libs/skills/registry.py`), and tracked with SHA-256 content hashes. Trust tiers: `first-party` vs `user-local`.

### Configuration

`libs/core/config.py` uses pydantic-settings with `LAB_` env prefix and `.env` fallback. Singleton via `get_settings()`. Key settings: `LAB_DB_URL`, `LAB_ENV` (dev bypasses browser auth), `LAB_DATA_ROOT`, `LAB_MODEL_CONFIG`, `LAB_SKILL_PATHS`.

### Database

PostgreSQL with pgvector (768-dim embeddings) and Apache AGE (graph storage). Alembic migrations in `libs/storage/migrations/versions/`. SQLAlchemy models in `libs/storage/models/`. Dual session factories: async for API, sync for worker/CLI. All primary keys use UUIDv7 (time-sortable, via `uuid_utils`).

The async DB URL requires `postgresql+psycopg://` prefix (not plain `postgresql://`).

## Monorepo Layout

- `apps/api/` — FastAPI server, routers mount under `/api/v1`, auth in `auth.py`, deps in `deps.py`
- `apps/worker/` — Polling worker with `claimer.py` (job locking), `heartbeat.py` (`JobSupervisor`), `executor.py` (operator dispatch/registration), `periodic.py` (stale-job reclaim + pattern-decay enqueue)
- `apps/cli/` — Typer CLI, entry point is `synthetos` command, subcommands in `commands/`
- `apps/web/` — React 19 + TypeScript + Vite + TanStack Router (file-based, auto-generates `routeTree.gen.ts`) + TanStack Query + Tailwind CSS 4. Vite proxies `/api` to `localhost:8000`.
- `libs/schemas/` — Pydantic v2 request/response models (API boundary)
- `libs/core/` — Domain logic: config, events, operators, state machine, services
- `libs/storage/` — SQLAlchemy models, Alembic migrations, session management
- `libs/adapters/` — Hexagonal adapters: `llm/`, `embeddings/`, `sources/`, `reranker/`, `ingestion/`, `graph/`
- `libs/discovery/` — Discovery loop operators and supporting logic (ranking, evaluation, views, metadata analysis)
- `libs/analysis/` — Analysis loop operators (coverage, graph QA, reports)
- `libs/ideation/` — Hypothesis generation, critique, and ranking operators (Phase 3)
- `libs/protocols/` — Protocol compiler (hypotheses → `ExperimentSpec`). Accepts `variation_context` and `from_loop` payload keys when driven by the autonomous loop
- `libs/execution/` — Workspace setup, containerized run, capture, and telemetry operators
- `libs/verification/` — Verification check and failure postmortem operators
- `libs/remediation/` — Phase 4 auto-remediation, directional signal, frontier, and recommendation operators
- `libs/autonomy/` — Phase 5 autonomous loop: policy, budget, gates, hypothesis lifecycle, repetition detection, context summarization, completion reporting, `loop_decide`/`loop_report` operators
- `libs/patterns/` — Phase 6 canonical pattern memory: `consolidate_patterns`/`decay_patterns` operators, content-key dedup, embedding retrieval, `inject_patterns()` (see Pattern Memory above)
- `libs/goals/` — Goal mode: `goal_advance`/`goal_evaluate`/`goal_report` operators over `ResearchGoal`/`GoalAttempt` (see Goal Mode above)
- `libs/pilot/` — Fixture-driven end-to-end harness (`fixture.py`/`runner.py`/`evaluation.py`); see Pilot Harness above
- `libs/orchestration/` — Reserved namespace (only `__init__.py` today)
- `libs/prompts/` — Versioned prompt template loader (frontmatter + jinja2); resolves `<domain>.<name>` → `prompts/<domain>/<name>/vN.md`, preferring per-model `vN.<model-slug>.md` variants
- `libs/skills/` — Skill loader, parser, validator, registry
- `skills/` — First-party skill.md packages
- `configs/` — YAML configs (`models.yaml` + `models.mnemosyne*.yaml` variants, `discovery/`, `policies/`, `problems/` pilot fixtures, `skills/`)
- `prompts/` — Versioned system-prompt templates (`<domain>/<name>/v<N>.md`); see `prompts/README.md`

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
