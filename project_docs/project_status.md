# Project Status

**Product:** Synthetos (ML Laboratory Co-Scientist)
**Date:** 2026-04-13
**Phase:** 3 — Hypotheses, Protocols, and Execution Lab MVP
**Status:** Phase 3 implementation complete, including the post-review remediation pass. All code-level quality gates are green (`ruff check`, `pyright`, `pytest` — 84 tests, and web build). Phase 3 now turns Phase 2 evidence into runnable ML experiments with real run control, live telemetry, deterministic verification, and recorded skill/model lineage. The main remaining work is live integration testing with real Postgres, real Docker containers, configured model endpoints, and GPU hardware.

---

## Phase 3 Session Summary

Phase 3 completes the transition from literature understanding to experimental execution. Evidence cards from Phase 2 are synthesized into ranked hypothesis portfolios, compiled into fully executable experiment specifications (with generated code), executed in isolated Docker containers, verified against deterministic metric contracts, and analyzed via LLM-generated failure postmortems when runs fail.

The implementation followed the approved plan at `/Users/c/.claude/plans/streamed-prancing-plum.md`.

Key design decisions:
- **Generated-then-committed code provenance**: `protocol_compile` generates code → `execution_setup` writes files to a git worktree and commits → commit SHA is the durable lineage anchor
- **Deterministic metric contract**: containers write `/artifacts/metrics.json` → `parse_metrics()` validates types/presence → `classify_metric()` compares against thresholds → VerificationReport
- **Four run control actions**: pause (docker pause/SIGSTOP), resume (docker unpause/SIGCONT), cancel (docker kill), retry (new immutable RunRecord) — enforced by canonical action rules table
- **Two-tier telemetry**: domain events (low-frequency, in main SSE stream) for orchestrators + `run_telemetry` rows (high-frequency, per-run SSE) for drill-in UI
- **Skill lineage recording**: `record_skill_usage()` writes `skill_bindings` rows, `record_model_call()` writes `model_call_records` rows — closing the lineage gap from Phases 1-2

The main outcomes were:

- Added 7 new database tables via Alembic migration: `hypothesis_sessions`, `hypothesis_cards`, `experiment_specs`, `run_records`, `run_telemetry`, `verification_reports`, `failure_postmortems`
- Built 3 hypothesis operators (generate, critique, rank) with structured LLM output and weighted composite scoring (novelty 0.3, feasibility 0.4, impact 0.3)
- Built protocol compilation operator with spec completeness validation (baseline, metrics, stop conditions, code_plan required)
- Built execution runtime: git worktree management, Docker SDK runner with GPU passthrough via `DeviceRequest`, log streaming with telemetry callback, failure classification (oom/timeout/dependency/runtime/metric_parse)
- Built deterministic verification pipeline: metric parsing → per-metric classification → artifact contract checking → verdict (passed/failed/inconclusive) → optional LLM postmortem
- Added worker failure cascading for all Phase 3 job prefixes (`hypothesis_*`, `protocol_*`, `execution_*`, `verification_*`)
- Added 19 API endpoints under `/api/v1` for hypotheses, protocols, runs, run control, telemetry (list + SSE stream), and verification
- Added 12 CLI commands under `synthetos experiment`
- Added run control service with canonical action rules enforcement (409 on illegal transitions)
- Added per-run telemetry SSE endpoint with terminal-status auto-close
- Added skill lineage helpers and 4 Phase 3 skill packages
- Added `hypothesis_generation` and `protocol_drafting` model role configs
- Built web frontend: TypeScript API client, experiment dashboard page, run detail page with metrics/verification/postmortem/telemetry/controls
- Remediated the Phase 3 execution gaps: active pause/resume/cancel/retry behavior, incremental telemetry commits, `execution.run_progress` heartbeats, wired skill usage in operators, deterministic `output_contract` and `metric_sanity`, scoped hypothesis selection, and mandatory commit provenance
- Added targeted Phase 3 unit coverage for runtime control, telemetry, verification, and lineage
- All code-level quality gates pass: `ruff`, `pyright`, `pytest` (`84 passed`), and web build

---

## What Was Added in Phase 3

### 1. Schema, migrations, and core types

- New ORM models (`libs/storage/models/experiment.py`):
  - `HypothesisSession` — one hypothesis-generation run per cycle, with status/budget/stats/step_log
  - `HypothesisCard` — candidate hypothesis with evidence lineage, critique, scores (novelty/feasibility/impact), rank, status lifecycle
  - `ExperimentSpec` — compiled protocol with baseline, controls, metrics, expected_artifacts, stop_conditions, code_plan, hardware_profile, base_image
  - `RunRecord` — one execution of a spec, with workspace/container/image tracking, metrics_output, artifact_manifest, resource_usage, failure classification
  - `RunTelemetry` — high-frequency streaming rows (log/metric/resource/status_change)
  - `VerificationReport` — baseline comparison, artifact checks, output contract, metric sanity, verdict (passed/failed/inconclusive)
  - `FailurePostmortem` — root cause, contributing factors, error trace, next step recommendation, lessons
- Pydantic schemas (`libs/schemas/experiment.py`):
  - `HypothesisBudget`, `HypothesisSessionStartRequest/Read/Response`, `HypothesisCardRead/Update`
  - `ExperimentSpecCompileRequest/Read/Response`, `RunStartRequest/Response`, `RunControlRequest`, `RunRecordRead`
  - `RunTelemetryRead`, `VerificationReportRead`, `FailurePostmortemRead`
- Alembic migration:
  - `20260413_000001_phase3_hypotheses_execution.py` — creates 7 tables with indexes, FK constraints, Vector(768) columns
- Event types:
  - `IdeationEvents` (6), `ProtocolEvents` (5), `ExecutionEvents` (9), `VerificationEvents` (3) — 23 new events namespaced under `ideation.*`, `protocol.*`, `execution.*`, `verification.*`

### 2. Hypothesis pipeline (`libs/ideation/`)

- `operators/generate.py` — loads evidence cards, calls `hypothesis_generation` model role with structured output, creates `HypothesisCard` rows
- `operators/critique.py` — calls LLM in critique mode, fills novelty/feasibility/impact scores and critique payload
- `operators/rank.py` — weighted composite scoring, assigns ranks, marks session completed, transitions cycle → `portfolio_ready`
- `operators/_common.py` — shared helpers (session loading, step log, stats, enqueue, mark_failed)

### 3. Protocol compilation (`libs/protocols/`)

- `operators/compile.py` — loads selected hypotheses, calls `protocol_drafting` model role, generates `ExperimentSpec` rows with code_plan, validates completeness, rejects under-specified specs with detailed reasons, transitions cycle → `protocol_ready`
- `validation.py` — spec completeness checker (baseline, metrics with direction, code_plan with entry_point and files, stop conditions)

### 4. Execution runtime

- `libs/adapters/git/worktree.py` — `create_worktree()`, `commit_worktree()`, `cleanup_worktree()` via git CLI
- `libs/adapters/container/docker_runner.py` — `DockerRunner` class using Docker SDK: `build_image()`, `run()` with GPU passthrough via `DeviceRequest`, log streaming, timeout handling, `pause()`/`unpause()`/`kill()` for run control
- `libs/execution/metrics.py` — `parse_metrics()` (validates /artifacts/metrics.json: presence, JSON validity, type coercion, NaN/inf rejection) and `classify_metric()` (per-metric pass/fail against spec thresholds/baseline)
- `libs/execution/operators/setup.py` — creates git worktree, writes generated code files, commits, resolves/builds Docker image
- `libs/execution/operators/run.py` — launches container, streams logs with telemetry callback, classifies failures (oom/timeout/dependency/runtime), enqueues capture or verification
- `libs/execution/operators/capture.py` — collects artifact manifest with SHA-256 hashes, parses metrics via `parse_metrics()`, fails run on metric parse errors before verification

### 5. Verification (`libs/verification/`)

- `baseline.py` — `compare_to_baseline()` produces per-metric `MetricVerdict` list
- `contracts.py` — `check_artifact_contract()` verifies expected artifacts against manifest
- `operators/check.py` — creates `VerificationReport` with verdict logic: all pass + thresholds → "passed", all pass but no thresholds → "inconclusive", any fail → "failed"
- `operators/postmortem.py` — calls `evaluation` model role with error trace + metrics, creates `FailurePostmortem`, transitions cycle → `reporting`

### 6. Worker integration

- All 9 Phase 3 operators registered in `apps/worker/executor.py` via 4 registration blocks (ideation, protocols, execution, verification)
- `_mark_ideation_job_failed()` — marks linked hypothesis session failed
- `_mark_execution_job_failed()` — marks linked run record failed
- Both integrated into the worker failure path alongside existing discovery/analysis cascades

### 7. Service layer (`libs/core/services/experiment_service.py`)

- `start_hypothesis_session()` — validates `evidence_ready` cycle status, creates session + enqueues `hypothesis_generate`
- `compile_protocols()` — validates `portfolio_ready`, enqueues `protocol_compile` with hypothesis session reference
- `start_run()` — validates spec is `validated`, creates RunRecord, enqueues `execution_setup`, transitions cycle → `running`
- `control_run()` — enforces canonical action rules table (pause/resume/cancel/retry with status-specific legality, 409 on violations)
- Query functions for all entities: sessions, cards, specs, runs, telemetry, verification reports, postmortems

### 8. API (`apps/api/routers/experiment.py`)

19 endpoints under `/api/v1`:
- Hypotheses: `POST /hypotheses/sessions`, `GET /hypotheses/sessions`, `GET /hypotheses/sessions/{id}`, `GET /hypotheses/cards`, `GET /hypotheses/cards/{id}`, `PATCH /hypotheses/cards/{id}`
- Protocols: `POST /protocols/compile`, `GET /protocols/specs`, `GET /protocols/specs/{id}`
- Runs: `POST /runs`, `GET /runs`, `GET /runs/{id}`, `POST /runs/{id}/control`
- Telemetry: `GET /runs/{id}/telemetry`, `GET /runs/{id}/telemetry/stream` (SSE)
- Verification: `GET /runs/{id}/verification`, `GET /runs/{id}/postmortem`, `GET /verifications`

### 9. Skills

- `skills/ideation/hypothesis_generation/skill.md` — guidance for hypothesis generation and critique
- `skills/ideation/experiment_planning/skill.md` — guidance for compiling hypotheses into executable specs
- `skills/coding/experiment_coding/skill.md` — code structure, metric reporting, artifact output conventions
- `skills/verification/run_evaluation/skill.md` — verification checks, failure classification, postmortem analysis

### 10. Lineage

- `libs/skills/lineage.py` — `record_skill_usage()` writes `skill_bindings` rows, `record_model_call()` writes `model_call_records` rows
- Model config: added `hypothesis_generation` and `protocol_drafting` role entries to `configs/models.yaml`

### 11. CLI (`apps/cli/commands/experiment.py`)

12 commands under `synthetos experiment`:
- `hypothesize`, `hypotheses`, `compile`, `specs`, `run`, `runs`, `status`, `pause`, `resume`, `cancel`, `retry`, `verify`, `postmortem`

### 12. Frontend

- `apps/web/src/api/experiment.ts` — full TypeScript API client with types for all Phase 3 entities
- `apps/web/src/routes/experiment/index.tsx` — dashboard showing hypotheses, specs, and runs with polling
- `apps/web/src/routes/experiment/$runId.tsx` — run detail page with metrics, verification report, failure postmortem, telemetry tail, and run control buttons (pause/resume/cancel/retry)

---

## Files Touched in Phase 3

### New backend / library files

- `libs/storage/models/experiment.py` — 7 SQLAlchemy models
- `libs/storage/migrations/versions/20260413_000001_phase3_hypotheses_execution.py`
- `libs/schemas/experiment.py` — 15+ Pydantic schemas
- `libs/ideation/__init__.py`, `operators/__init__.py`, `operators/_common.py`, `operators/generate.py`, `operators/critique.py`, `operators/rank.py`
- `libs/protocols/__init__.py`, `operators/__init__.py`, `operators/_common.py`, `operators/compile.py`, `validation.py`
- `libs/execution/__init__.py`, `metrics.py`, `operators/__init__.py`, `operators/_common.py`, `operators/setup.py`, `operators/run.py`, `operators/capture.py`
- `libs/verification/__init__.py`, `baseline.py`, `contracts.py`, `operators/__init__.py`, `operators/_common.py`, `operators/check.py`, `operators/postmortem.py`
- `libs/adapters/git/__init__.py`, `worktree.py`
- `libs/adapters/container/docker_runner.py`
- `libs/skills/lineage.py`
- `libs/core/services/experiment_service.py`
- `apps/api/routers/experiment.py`
- `apps/cli/commands/experiment.py`

### Modified backend / library files

- `pyproject.toml` — added `docker>=7,<8`
- `libs/core/event_types.py` — added `IdeationEvents`, `ProtocolEvents`, `ExecutionEvents`, `VerificationEvents`
- `libs/storage/models/__init__.py` — registered 7 new models
- `apps/worker/executor.py` — registered 4 operator chains (ideation, protocols, execution, verification)
- `apps/worker/main.py` — added `_mark_ideation_job_failed`, `_mark_execution_job_failed` + failure cascade integration
- `apps/api/main.py` — mounted experiment router
- `apps/cli/main.py` — registered `experiment` Typer subcommand
- `configs/models.yaml` — added `hypothesis_generation` and `protocol_drafting` role entries

### New skills

- `skills/ideation/hypothesis_generation/skill.md`
- `skills/ideation/experiment_planning/skill.md`
- `skills/coding/experiment_coding/skill.md`
- `skills/verification/run_evaluation/skill.md`

### Frontend

- `apps/web/src/api/experiment.ts` — TypeScript API client
- `apps/web/src/routes/experiment/index.tsx` — experiment dashboard
- `apps/web/src/routes/experiment/$runId.tsx` — run detail page
- `apps/web/src/routeTree.gen.ts` — route registration (auto-generated)

---

## Verification Status

The repository passes code-level quality gates after Phase 3:

- `uv run ruff check .` — passes
- `UV_CACHE_DIR=/tmp/uv-cache uv run pyright` — passes
- `uv run pytest` — `84 passed`
- `cd apps/web && npm run build` — passes

---

## What Remains Before Phase 3 Can Be Called Fully Verified

1. **Run the migration against a live Postgres instance.**
   - `alembic upgrade head` should create the 7 Phase 3 tables alongside the existing Phase 0+1+2 schema.
2. **Validate the full hypothesis → protocol → execution → verification pipeline end-to-end.**
   - Start from a cycle with evidence cards, run `synthetos experiment hypothesize`, watch the worker process the 3-operator hypothesis chain, then `compile`, then `run`.
3. **Validate Docker container execution with real GPU hardware.**
   - Test with a simple PyTorch script on the 2x RTX 6000 Blackwell GPUs. Confirm `DeviceRequest` GPU passthrough works, metrics are written to `/artifacts/metrics.json`, and the verification pipeline produces a correct verdict.
4. **Validate run control actions against a running container.**
   - Pause a running container (verify `docker pause` works), resume it, cancel it, retry it. Confirm the canonical action rules table is enforced correctly (409 on illegal transitions).
5. **Test failure paths.**
   - Force an OOM failure (exit code 137), a timeout, a dependency error (missing import), and a metric parse error (corrupt metrics.json). Verify each produces the correct `failure_class` and generates an LLM postmortem.
6. **Validate configured model endpoints.**
   - The `hypothesis_generation`, `protocol_drafting`, `coding`, and `evaluation` model roles must all be reachable for the full pipeline.
7. **Run a true end-to-end live experiment smoke.**
   - Confirm the full hypothesis → protocol → execution → verification path works with real artifacts, real metrics, and the expected verification verdict under live conditions.

---

## What Is Explicitly Still Out of Scope

- Auto-remediation, directional signal, and frontier tracking (Phase 4)
- Autonomous loop, gating, and completion reports (Phase 5)
- Cross-charter pattern memory (Phase 6)
- Re-embedding the corpus or supporting alternate embedding models — locked to `gte-modernbert-base` / 768
- Semantic Scholar / OpenAlex / Crossref source adapters — deferred
- An OpenAPI codegen pipeline for the web client — types stay manual for now

---

## Current Runbook

```bash
# Python dependencies (include the optional reranker extra)
uv sync --extra dev --extra reranker

# Database
docker compose up -d postgres
uv run synthetos db init   # runs alembic upgrade head; lands Phase 0+1+2+3 schema

# (One-time) import the pre-embedded arXiv mirror — ~56 GB JSONL, ~3M records
uv run synthetos corpus import-arxiv --path artifacts/arxiv-embedded.jsonl

# Backend API
uv run uvicorn apps.api.main:app --port 8000 --reload

# Worker (must be running for discovery, analysis, and experiment operator chains)
uv run python -m apps.worker

# Frontend
cd apps/web
npm install
npm run dev

# Phase 1: Headless discovery
uv run synthetos discovery run \
  --charter-id <uuid> \
  --query "your scoped problem statement" \
  --view both

# Phase 2: Analyze a shortlisted paper
uv run synthetos analysis run \
  --paper-id <uuid> \
  --charter-id <uuid> \
  --cycle-id <uuid>

# Phase 3: Generate hypotheses from evidence
uv run synthetos experiment hypothesize \
  --cycle-id <uuid> \
  --charter-id <uuid>

# Phase 3: Compile protocols (after hypotheses are ranked)
uv run synthetos experiment compile \
  --cycle-id <uuid> \
  --charter-id <uuid>

# Phase 3: Run an experiment (after specs are validated)
uv run synthetos experiment run \
  --spec-id <uuid> \
  --gpu

# Phase 3: Check run status and verification
uv run synthetos experiment status --run-id <uuid>
uv run synthetos experiment verify --run-id <uuid>
uv run synthetos experiment postmortem --run-id <uuid>

# Phase 3: Run control
uv run synthetos experiment pause --run-id <uuid>
uv run synthetos experiment resume --run-id <uuid>
uv run synthetos experiment cancel --run-id <uuid>
uv run synthetos experiment retry --run-id <uuid>
```

If local Postgres is not using the repo defaults, set `LAB_DB_URL` first so the API, worker, and Alembic all target the same database. The query-time embedding endpoint configured in `configs/models.yaml` (`embeddings.default.base_url`) must be reachable for hybrid retrieval; without it the internal corpus adapter degrades to lexical-only.
