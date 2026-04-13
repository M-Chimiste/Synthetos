# Project Status

**Product:** Synthetos (ML Laboratory Co-Scientist)
**Date:** 2026-04-13
**Phase:** 4 — Remediation, Directional Signal, and Frontier Tracking
**Status:** Phase 4 implementation and remediation pass are complete. All code-level quality gates are green (`ruff check`, `pyright`, `pytest` — 141 tests, and web build). The remediation/signal/recommendation layer now has correct auth, lineage-scoped remediation history, truthful retry-lineage reads in the API and UI, deterministic focused `invalid_artifact` repair before broad debug, and idempotent per-run signal and recommendation artifacts. The main remaining work is still live integration testing against real Postgres, Docker containers, and configured model endpoints.

---

## Phase 4 Session Summary

Phase 4 bridges the deterministic execution lab (Phase 3) with the autonomous loop (Phase 5). Previously, every failed run went straight to an expensive LLM-generated postmortem and stopped. Now, mechanical failures (dependency, OOM, timeout, and deterministic artifact naming/path mismatches) are auto-remediated with focused fixes before resorting to postmortem. Successful runs are classified with a directional signal, tracked against a per-hypothesis-line metric frontier, and given a deterministic next-step recommendation that distinguishes mechanical recovery from parameter variation from hypothesis pivots.

The initial Phase 4 implementation landed, and then a follow-up remediation pass corrected the execution gaps found in review.

Key design decisions:
- **Two-tier remediation**: focused strategies first (install missing deps, double memory, extend timeout), then broad LLM-assisted debug if the same failure class recurs. Max 3 attempts in a lineage before exhaustion.
- **Lineage-scoped remediation state**: retry escalation, unresolved-failure checks, and recommendation inputs are computed from the current retry lineage, not all historical runs on the spec.
- **Single gateway to reporting**: the `recommend` operator is the sole owner of the `verifying → reporting` transition. Both terminal paths (passed runs via `signal_classify → recommend`, and failed-then-exhausted runs via `verification_postmortem → recommend`) converge on it.
- **Primary metric convention**: `metrics[0]` is the optimization target unless `primary_metric_index` is set. All others are constraint metrics with bounds checking.
- **Frontier keyed by hypothesis line**: `(charter_id, hypothesis_card_id)` not per-spec, so progress is tracked across protocol recompilations.
- **VerificationReport as canonical owner**: signal and recommendation rows don't point back to the report — the report holds outgoing FKs (`directional_signal_id`, `recommendation_id`), avoiding circular references.
- **Override delivery via job payload**: remediation patches (`code_plan`, `build_recipe`) go through the job payload key `remediation_overrides`, keeping `ExperimentSpec` immutable. Resource limits (`memory`, `timeout`) are set directly on the new `RunRecord`.
- **Per-run artifact idempotency**: `DirectionalSignal` and `RunRecommendation` are unique per `run_record_id`, and operators reuse/update the existing row when replayed.

The main outcomes were:

- Added 4 new database tables via Alembic migration: `remediation_actions`, `directional_signals`, `metric_frontiers`, `run_recommendations`
- Added 3 columns to existing tables: `run_records.parent_run_id`, `experiment_specs.primary_metric_index`, `verification_reports.directional_signal_id` + `recommendation_id`
- Built 3 new operators: `auto_remediate`, `signal_classify`, `recommend`
- Built pure-function modules: signal classification (5 signals), frontier upsert, recommendation rules (decision matrix), strategy selection with tier escalation
- Rewired the verification pipeline: `verification_check` routes failed → `auto_remediate`, passed → `signal_classify`; `verification_postmortem` routes to `recommend` instead of directly to reporting
- Added `invalid_artifact` failure class to execution classification
- Modified `execution_setup` to merge remediation overrides (code_plan patches, build_recipe extras)
- Added 7 API endpoints for remediation, signal, recommendation, lineage, signal history, and frontiers
- Added 5 CLI commands: `remediation`, `signal`, `frontier`, `recommendation` under `synthetos experiment`
- Added 9 new event types: `RemediationEvents` (5) and `SignalEvents` (4)
- Built web frontend: TypeScript API client, run detail page with signal/recommendation/remediation/lineage sections, experiment index with frontier summary
- Added Phase 4 remediation follow-up work:
  - remediation routes now use `cycles.read` scope, matching the rest of the experiment surface
  - `/runs/{id}/lineage` returns the full retry chain for any node, not only ancestors plus direct children
  - the run detail page now renders previous/next retry links plus full chain context from the lineage endpoint
  - `invalid_artifact` now has a deterministic focused artifact-path rewrite strategy before broad LLM debug
  - old resolved failures from other lineages no longer bias later successful recommendations
- Added 62 unit tests across the Phase 4 area and remediation follow-up work
- All code-level quality gates pass: `ruff`, `pyright`, `pytest` (`141 passed`), and web build

---

## What Was Added in Phase 4

### 1. Schema, migrations, and core types

- New ORM models (`libs/storage/models/remediation.py`):
  - `RemediationAction` — one remediation attempt per failed run, with strategy, tier (focused/broad), outcome, attempt tracking, and retry lineage
  - `DirectionalSignal` — signal classification (advancing/stalled/regressing/noisy/breakthrough) with primary metric, delta, constraint metrics, and history window
  - `MetricFrontier` — best-known metric state per hypothesis line (charter + hypothesis card), with best run, runs since improvement, success rate
  - `RunRecommendation` — next-step recommendation (continue_current/parameter_variation/hypothesis_pivot/mechanical_recovery/halt) with action, reasoning, and inputs snapshot
- Column additions to existing models (`libs/storage/models/experiment.py`):
  - `RunRecord.parent_run_id` — self-referential FK for retry lineage tracking
  - `ExperimentSpec.primary_metric_index` — which metric is the optimization target (default 0)
  - `VerificationReport.directional_signal_id` — FK to signal row (set by `signal_classify`)
  - `VerificationReport.recommendation_id` — FK to recommendation row (set by `recommend`)
- Pydantic schemas (`libs/schemas/remediation.py`):
  - `RemediationActionRead`, `DirectionalSignalRead`, `MetricFrontierRead`, `RunRecommendationRead`, `RunLineageRead`
- Updated schemas (`libs/schemas/experiment.py`):
  - Added `parent_run_id`, `primary_metric_index`, `directional_signal_id`, `recommendation_id` to existing read models
- Alembic migration:
  - `20260414_000001_phase4_remediation_signal.py` — creates 4 tables, adds 3 columns, with full downgrade support
- Event types:
  - `RemediationEvents` (5): `remediation.started`, `remediation.retry_created`, `remediation.strategy_escalated`, `remediation.skipped`, `remediation.exhausted`
  - `SignalEvents` (4): `signal.classified`, `signal.frontier_created`, `signal.frontier_updated`, `signal.recommendation_produced`

### 2. Signal classification (`libs/remediation/signal_classification.py`)

Pure-function module with deterministic rules:
- `breakthrough` — improvement >= 2 standard deviations from historical mean (requires 3+ prior runs)
- `advancing` — improvement over previous run beyond 1% noise band
- `regressing` — wrong direction beyond noise band
- `noisy` — direction alternating for 3+ consecutive runs
- `stalled` — within noise band for 3+ consecutive runs
- First successful run always classified as `advancing`

### 3. Frontier tracking (`libs/remediation/frontier.py`)

- `upsert_frontier()` — creates or updates `MetricFrontier` keyed on `(charter_id, hypothesis_card_id)`
- Tracks best run, best metric value, total runs, successful runs, runs since improvement
- Only successful runs can update the best value; failed runs still increment total_runs

### 4. Recommendation logic (`libs/remediation/recommendations.py`)

Deterministic decision matrix mapping (signal, frontier state, remediation history) to recommendation type:
- `continue_current` — breakthrough or advancing with no issues
- `parameter_variation` — stalled (below threshold), regressing, noisy, or advancing with unresolved failures
- `hypothesis_pivot` — stalled (>= 5 runs without improvement) or all remediations exhausted with no prior successes
- Failed path: uses frontier + remediation + postmortem history when no signal exists

### 5. Remediation strategies (`libs/remediation/strategies.py`)

Two-tier strategy selection per failure class:
- **Tier 1 — Focused** (deterministic, no LLM):
  - `dependency` → parse stderr for missing modules, patch build_recipe
  - `oom` → double memory limit (cap 64g)
  - `timeout` → increase timeout by 50% (cap 4h)
  - `invalid_artifact` → if there is exactly one clear filename/path mismatch with the same extension, rewrite references in `code_plan.files` from the produced artifact path to the expected artifact path
  - `metric_parse` → not remediable, skip to postmortem
- **Tier 2 — Broad debug** (LLM-assisted):
  - Activates when focused strategy already tried for same failure class
  - Also used when `invalid_artifact` is ambiguous and no single deterministic rewrite exists
  - Sends error trace + code plan + prior remediation history to LLM for code fix
- Escalation rule: attempt 1 = focused; attempt 2 with same failure class = broad; different class = focused for new class

### 6. Operators (`libs/remediation/operators/`)

- `auto_remediate` — loads failed run, counts lineage attempts, selects strategy, creates new RunRecord with overrides, persists RemediationAction, enqueues `execution_setup` for retry. Routes to `verification_postmortem` when exhausted or non-remediable.
- `signal_classify` — loads run history across all specs in hypothesis line, classifies signal, persists DirectionalSignal, upserts MetricFrontier, sets VerificationReport FK, enqueues `recommend`.
- `recommend` — gathers signal + frontier + remediation + postmortem data, applies deterministic rules, persists RunRecommendation, sets VerificationReport FK, transitions cycle → `reporting`.

### 7. Pipeline rewiring

- `verification_check` (failed path): now enqueues `auto_remediate` instead of `verification_postmortem`
- `verification_check` (passed path): now enqueues `signal_classify` instead of transitioning to `reporting`
- `verification_postmortem`: now enqueues `recommend` instead of transitioning to `reporting`
- `execution_setup`: reads `remediation_overrides` from job payload, merges code_plan patches and build_recipe extras
- `execution_run`: added `invalid_artifact` failure classification heuristics

### 8. API (`apps/api/routers/remediation.py`)

7 endpoints under `/api/v1`:
- `GET /runs/{id}/remediation` — remediation actions for a run
- `GET /runs/{id}/signal` — directional signal for a run
- `GET /runs/{id}/recommendation` — recommendation for a run
- `GET /runs/{id}/lineage` — full retry chain for any node (walk to root, then include all descendants ordered oldest→newest, plus remediation actions)
- `GET /specs/{id}/signal-history` — all signals for a spec
- `GET /hypotheses/{id}/frontier` — metric frontier for a hypothesis line
- `GET /charters/{id}/frontiers` — all frontiers for a charter

All remediation read routes use `cycles.read`, matching the existing experiment/discovery/analysis permission model.

### 9. CLI (`apps/cli/commands/experiment.py`)

5 new commands under `synthetos experiment`:
- `remediation --run-id <uuid>` — show remediation actions
- `signal --run-id <uuid>` — show directional signal
- `frontier --charter-id <uuid>` — list metric frontiers
- `recommendation --run-id <uuid>` — show recommendation

### 10. Frontend

- `apps/web/src/api/remediation.ts` — TypeScript API client with types for all Phase 4 entities
- `apps/web/src/routes/experiment/$runId.tsx` — run detail page gains: run lineage links, directional signal badge with delta and constraint metrics, recommendation badge with action/reasoning, remediation history with strategy/tier/outcome and retry links
- `apps/web/src/routes/experiment/index.tsx` — experiment index gains: frontier summary section showing best metric, runs since improvement, success rate per hypothesis line
- `apps/web/src/api/experiment.ts` — added `parent_run_id` to `RunRecord` TypeScript type

---

## Files Touched in Phase 4

### New backend / library files

- `libs/storage/models/remediation.py` — 4 SQLAlchemy models
- `libs/storage/migrations/versions/20260414_000001_phase4_remediation_signal.py`
- `libs/schemas/remediation.py` — 5 Pydantic schemas
- `libs/remediation/__init__.py`, `signal_classification.py`, `frontier.py`, `recommendations.py`, `strategies.py`
- `libs/remediation/operators/__init__.py`, `_common.py`, `remediate.py`, `signal.py`, `recommend.py`
- `apps/api/routers/remediation.py`

### Modified backend / library files

- `libs/core/event_types.py` — added `RemediationEvents` (5) and `SignalEvents` (4)
- `libs/storage/models/experiment.py` — added `parent_run_id`, `primary_metric_index`, `directional_signal_id`, `recommendation_id` columns
- `libs/storage/models/__init__.py` — registered 4 new models
- `libs/schemas/experiment.py` — added new fields to `RunRecordRead`, `ExperimentSpecRead`, `VerificationReportRead`
- `libs/verification/operators/check.py` — rewired failed → `auto_remediate`, passed → `signal_classify`
- `libs/verification/operators/postmortem.py` — enqueues `recommend` instead of transitioning to reporting
- `libs/execution/operators/run.py` — added `invalid_artifact` failure classification
- `libs/execution/operators/setup.py` — handles `remediation_overrides` payload
- `apps/worker/executor.py` — registered Phase 4 operator chain
- `apps/api/main.py` — mounted remediation router
- `apps/cli/commands/experiment.py` — added 5 Phase 4 commands

### Frontend

- `apps/web/src/api/remediation.ts` — new TypeScript API client
- `apps/web/src/api/experiment.ts` — added `parent_run_id` to RunRecord
- `apps/web/src/routes/experiment/$runId.tsx` — signal, recommendation, remediation, lineage sections, plus previous/next retry navigation and full chain context
- `apps/web/src/routes/experiment/index.tsx` — frontier summary section

### Tests

- `tests/unit/test_signal_classification.py` — 16 tests covering all 5 signals + edge cases
- `tests/unit/test_frontier.py` — 6 tests for create/update/failed paths
- `tests/unit/test_recommendations.py` — 12 tests covering full decision matrix
- `tests/unit/test_remediation_strategies.py` — 19 tests for all failure classes + escalation + helpers
- `tests/unit/test_auth.py` — includes remediation route scope enforcement
- `tests/unit/test_phase4_remediation_runtime.py` — covers lineage-scoped recommendation behavior, idempotent signal/recommend artifacts, and full retry-chain reads

---

## Verification Status

The repository passes code-level quality gates after Phase 4:

- `uv run ruff check .` — passes
- `uv run pyright` — passes (0 errors, 0 warnings)
- `uv run pytest` — `141 passed`
- `cd apps/web && npm run build` — passes

---

## What Remains Before Phase 4 Can Be Called Fully Verified

1. **Run the migration against a live Postgres instance.**
   - `alembic upgrade head` should create the 4 Phase 4 tables and add columns to `run_records`, `experiment_specs`, and `verification_reports` alongside existing schema.
2. **Validate auto-remediation end-to-end.**
   - Force a dependency failure (missing import), verify remediation creates a retry run with the missing package added to build_recipe. Confirm the retry succeeds.
   - Force an OOM failure (exit code 137), verify memory is doubled on retry.
   - Force a timeout, verify timeout is extended.
   - Force a deterministic invalid-artifact mismatch, verify the focused artifact-path rewrite is applied before broad debug.
   - Verify max_attempts (3) is respected and remediation exhaustion routes to postmortem → recommend.
3. **Validate the broad debug escalation path.**
   - Force two consecutive dependency failures with the same missing module to trigger focused → broad escalation. Verify the LLM is called and code_plan patches are applied.
4. **Validate signal classification after successful runs.**
   - Run multiple experiments against the same hypothesis. Verify signals progress through advancing → stalled as metrics plateau. Verify frontier updates correctly.
5. **Validate recommendations.**
   - After a stalled frontier (5+ runs without improvement), verify the recommendation is `hypothesis_pivot`.
   - After a breakthrough, verify `continue_current`.
   - After remediation exhaustion with no prior successes, verify `hypothesis_pivot`.
6. **Validate UI rendering.**
   - Confirm the run detail page shows signal badge, recommendation badge, remediation history with retry links, and lineage breadcrumbs.
   - Confirm the experiment index shows frontier summary with best metric and staleness indicators.

---

## What Is Explicitly Still Out of Scope

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
uv run synthetos db init   # runs alembic upgrade head; lands Phase 0+1+2+3+4 schema

# (One-time) import the pre-embedded arXiv mirror — ~56 GB JSONL, ~3M records
uv run synthetos corpus import-arxiv --path artifacts/arxiv-embedded.jsonl

# Backend API
uv run uvicorn apps.api.main:app --port 8000 --reload

# Worker (must be running for discovery, analysis, experiment, and remediation operator chains)
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

# Phase 4: Inspect remediation, signal, frontier, recommendation
uv run synthetos experiment remediation --run-id <uuid>
uv run synthetos experiment signal --run-id <uuid>
uv run synthetos experiment recommendation --run-id <uuid>
uv run synthetos experiment frontier --charter-id <uuid>
```

If local Postgres is not using the repo defaults, set `LAB_DB_URL` first so the API, worker, and Alembic all target the same database. The query-time embedding endpoint configured in `configs/models.yaml` (`embeddings.default.base_url`) must be reachable for hybrid retrieval; without it the internal corpus adapter degrades to lexical-only.
