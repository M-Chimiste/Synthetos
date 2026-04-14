# Project Status

**Product:** Synthetos (ML Laboratory Co-Scientist)
**Date:** 2026-04-14
**Phase:** 5 — Autonomous Loop and Configurable Gating
**Status:** Phase 5 implementation is complete end-to-end (backend, API, CLI, and frontend) and all code-level quality gates are green (`ruff check`, `pyright` — 0 errors, `pytest` — 230 tests passed, web build). The autonomous loop, budget tracking, checkpoint gates, hypothesis lifecycle, repetition detection, context summarization, completion reporting, API endpoints, CLI commands, and autonomy dashboard UI are all in place. The remaining work is live integration testing of the full loop against real Postgres, Docker, and model endpoints.

---

## Phase 5 Session Summary

Phase 5 closes the research loop. Previously, every run terminated after a single `RunRecommendation` was produced and the cycle transitioned to `reporting`. Now, in autonomous mode, recommendations are consumed by a new `loop_decide` operator that continues, varies, or pivots the loop subject to budget limits and optional checkpoint gates. Supervised mode is completely unchanged.

Key design decisions:
- **New `loop_deciding` cycle state** between `verifying` and `reporting`. Makes the decision point visible in the state machine instead of hiding it inside `verifying`. Only one conditional in Phase 4 `recommend` operator changes (the target status).
- **Budget model tracks run count and wall-clock time, not dollar cost.** `RunRecord.resource_usage` lacks a dollar field and `ModelCallRecord.cost_estimate` is nullable and unreliable. A mixed-source cost budget would silently misenforce. Cost budgets deferred to a future iteration; the `AutonomyBudget` table and `AutonomyPolicy` model are designed to accommodate them without breaking changes.
- **Gate pause/resume uses the existing worker pause contract.** `loop_decide` sets its own Job row to `JobStatus.paused` directly; the worker sees `current_job.status == JobStatus.paused` on return and handles `pause_job()` + event emission. Resume hits the existing `resume_job()` service. When the re-pending job runs again, `loop_decide` detects the existing `LoopDecision(decision="stop_gate")` for the same `run_record_id` and treats it as gate-approved.
- **Hypothesis lifecycle coexists with Phase 3 statuses.** PATCH validation unchanged (`candidate|selected|rejected|deferred`); Phase 5 statuses (`active|promising|stalled|deprioritized|validated`) are system-managed by `loop_decide` via ORM writes, not through the API schema. No migration needed since the column is `String(50)`.
- **`regenerate_hypotheses` deferred from v1.** Re-entering the ideation pipeline mid-loop would require state-machine transitions through `evidence_ready -> portfolio_ready -> protocol_ready` conflicting with the cycle being in `running`/`loop_deciding`. When all hypotheses are exhausted, the loop stops with `stop_exhausted` and the completion report recommends manual regeneration.
- **Variation via `protocol_compile` payload.** Added `variation_context` and `from_loop` payload keys to `protocol_compile_operator`. When `from_loop=true`, the compile operator skips its own `protocol_ready` transition and instead creates a RunRecord and enqueues `execution_setup` directly, keeping the cycle in `running` throughout.
- **Repetition detection escalates.** Exact duplicate (same code_plan+controls+metrics+baseline fingerprint) forces `continue_current` -> `vary_parameters`. Near-duplicate detection compares controls for numeric drift within 1% tolerance.
- **Context summarization at run boundaries.** Every `summary_interval` runs (default 5), `loop_decide` generates a structured summary (hypotheses tried, frontier progression, failure patterns, remediation summary, repeated approaches) and writes it to disk. The summary is loaded into the `variation_context` when recompiling specs so the LLM stays aware of the full loop history.

The main outcomes:

- Added 2 new database tables via Alembic migration: `autonomy_budgets`, `loop_decisions`
- Added 1 new `CycleStatus` enum value (`loop_deciding`) and 2 new state-machine transitions
- Built 7 new pure-logic modules in `libs/autonomy/`: policy, budget, gates, hypothesis_lifecycle, repetition, context_summary, completion_report
- Built 2 new operators: `loop_decide` (core loop logic) and `loop_report` (completion report)
- Modified `recommend` operator to conditionally route to `loop_deciding` + enqueue `loop_decide` in autonomous mode
- Modified `protocol_compile` to accept `variation_context` and `from_loop` payload keys
- Added 7 new API endpoints under `/cycles/{id}/autonomy/*`: policy GET/PUT, budget, decisions list/detail, resume, stop
- Added 5 new CLI subcommands under `synthetos autonomy`: policy, budget, decisions, resume, stop
- Added 12 new event types in `AutonomyEvents` enum
- Added 89 new unit tests (16 state-machine, 10 policy, 10 budget, 21 lifecycle, 18 gates, 14 repetition)
- All code-level quality gates pass: `ruff` clean, `pyright` 0 errors, `pytest` 230 passed, web build succeeds

---

## What Was Added in Phase 5

### 1. Schema, migrations, and core types

- New ORM models (`libs/storage/models/autonomy.py`):
  - `AutonomyBudget` — one per cycle, tracks total_runs, wall_clock_elapsed_s, per-hypothesis run counts
  - `LoopDecision` — audit log row per loop iteration with decision vocabulary, budget snapshot, gate info, next_action, context_summary_path
- Column additions: none (Phase 5 lifecycle statuses are plain strings in existing `HypothesisCard.status` field)
- Pydantic schemas (`libs/schemas/autonomy.py`): `AutonomyPolicyRead`, `AutonomyPolicyUpdate`, `CheckpointGateConfigRead`, `AutonomyBudgetRead`, `LoopDecisionRead`
- Alembic migration: `20260415_000001_phase5_autonomy.py` creates both tables with full downgrade support
- State machine: added `loop_deciding` to `CycleStatus`, added `verifying -> loop_deciding` and `loop_deciding -> [running, reporting]` transitions
- Event types: added `AutonomyEvents` (12 events: loop_started, loop_decision_made, budget_updated, budget_exceeded, gate_triggered, gate_resumed, hypothesis_status_changed, hypothesis_selected, repetition_detected, context_summarized, loop_completed, loop_stopped_manual)

### 2. Autonomy policy and budget (`libs/autonomy/policy.py`, `budget.py`)

- `AutonomyPolicy` stored in `ResearchCycle.config["autonomy"]`:
  - `mode`: supervised | autonomous
  - `max_total_runs`, `max_wall_clock_hours`, `max_runs_per_hypothesis`, `max_wall_time_per_run_s`
  - `summary_interval` (default 5)
  - `checkpoint_gates`: after_every_run, after_every_n_runs, before_hardware_escalation, before_result_promotion, before_network_execution
- `load_or_create_budget()`, `increment_budget()`, `check_budget()`, `check_per_hypothesis_budget()`
- All gate config and budget limits default to None/False/empty — completely backwards-compatible

### 3. Hypothesis lifecycle (`libs/autonomy/hypothesis_lifecycle.py`)

Transition rules:
- `compiled|deferred -> active`: first loop iteration
- `active -> promising`: signal is advancing or breakthrough
- `active|promising -> stalled`: `runs_since_improvement >= 5`
- `active|stalled -> deprioritized`: recommendation is hypothesis_pivot
- `promising -> validated`: frontier meets spec's `stop_conditions[0].threshold` (supports both maximize and minimize directions)
- `rejected`, `deprioritized`, `validated`, `candidate` are terminal for the loop

### 4. Checkpoint gates (`libs/autonomy/gates.py`)

- `GateContext` and `GateResult` dataclasses
- `evaluate_gates()` checks gates in priority order, returns the first that fires
- Hardware escalation detection checks GPU count and memory increases
- Gate pause works against existing worker contract: `loop_decide` sets Job row to `JobStatus.paused` directly, worker handles the rest

### 5. Repetition detection (`libs/autonomy/repetition.py`)

- `fingerprint_spec()` produces a stable SHA-256 of canonicalized `(code_plan, controls, metrics, baseline)`
- `detect_repetition()` queries validated specs in the cycle, returns `RepetitionResult(is_duplicate, is_near_duplicate, prior_spec_id, match_type)`
- Near-duplicate detection: same code_plan+metrics+baseline but controls differ only by numeric values within 1% relative tolerance

### 6. Context summarization (`libs/autonomy/context_summary.py`)

- `should_generate_summary()` triggers at run count boundaries (5, 10, 15, ...)
- `generate_summary()` produces `LoopContextSummary` with hypotheses_tried, frontier_progression, failure_patterns, remediation_summary, repeated_approaches
- `write_summary()` writes JSON to `{data_root}/reports/cycles/{cycle_id}/summaries/summary_{iteration}.json`
- Loaded into `variation_context.context_summary` by `loop_decide` when enqueuing recompilations

### 7. Operators (`libs/autonomy/operators/`)

- `loop_decide` — the core orchestrator. Loads recommendation + policy + budget, checks for gate-resume, evaluates budget limits and gates, generates context summary at interval boundaries, updates hypothesis lifecycle, then dispatches based on recommendation type:
  - `continue_current` with repetition check (exact duplicate -> escalate to vary, 3+ near-duplicates -> escalate to pivot)
  - `parameter_variation` -> enqueue `protocol_compile` with `variation_context` + `from_loop=true`
  - `hypothesis_pivot` -> deprioritize current, select next viable card (ordered by rank), enqueue execution_setup or protocol_compile
  - `halt` -> stop loop
- `loop_report` — generates markdown + JSON completion report, transitions cycle to `closed`. Sections: budget summary, hypotheses explored table, loop decisions timeline, remediation summary, final decision.

### 8. Pipeline rewiring

- `recommend` operator: loads cycle config, checks `autonomy.mode == "autonomous"`. If so, sets target status to `loop_deciding` and enqueues `loop_decide` job. Otherwise unchanged (targets `reporting`).
- `protocol_compile` operator: accepts `variation_context` dict (appends to LLM prompt) and `from_loop` bool (suppresses state_patch, creates RunRecord inline, enqueues `execution_setup`).

### 9. API (`apps/api/routers/autonomy.py`)

7 endpoints under `/api/v1/cycles/{cycle_id}/autonomy/`:
- `GET /policy` — current policy
- `PUT /policy` — partial update (extend budget, toggle gates)
- `GET /budget` — budget consumption
- `GET /decisions` — list loop decisions (ordered by iteration)
- `GET /decisions/{decision_id}` — single decision detail
- `POST /resume` — resume gate-paused loop
- `POST /stop` — manually stop loop (cancels pending jobs, transitions to reporting, enqueues loop_report)

### 10. CLI (`apps/cli/commands/autonomy.py`)

5 subcommands under `synthetos autonomy`:
- `policy --cycle-id <uuid>` — show policy as JSON
- `budget --cycle-id <uuid>` — show consumption
- `decisions --cycle-id <uuid>` — list iterations
- `resume --cycle-id <uuid>` — resume paused loop
- `stop --cycle-id <uuid>` — stop loop

### 11. Frontend (`apps/web/src/`)

- `api/autonomy.ts` — TypeScript API client with types (`AutonomyPolicy`, `AutonomyBudget`, `LoopDecision`, `CheckpointGateConfig`) and functions for all 7 endpoints
- `components/AutonomyPanel.tsx` — autonomy dashboard panel with:
  - Mode badge (supervised/autonomous) and paused-at-gate indicator
  - Resume Gate button (visible when the last decision was `stop_gate`)
  - Stop Loop button (with confirmation, visible in autonomous mode)
  - Policy summary grid (run/time/hypothesis budgets, active gates)
  - Budget progress bars (runs used/max, wall-clock hours/max, per-hypothesis breakdown)
  - Loop decisions timeline with iteration number, decision badge, reasoning, and gate labels
- `components/StatusBadge.tsx` — added color mappings for `loop_deciding`, Phase 5 hypothesis lifecycle (`promising`, `stalled`, `deprioritized`, `validated`, `compiled`, `candidate`, `selected`, `deferred`, `rejected`), and autonomy modes (`autonomous`, `supervised`)
- `routes/charters/$charterId.tsx` — mounted `AutonomyPanel` below the Active Cycle section when an active cycle exists. Panel polls budget and decisions every 5 seconds.

---

## Files Touched in Phase 5

### New backend / library files

- `libs/autonomy/__init__.py`
- `libs/autonomy/policy.py` — AutonomyPolicy + CheckpointGateConfig Pydantic models
- `libs/autonomy/budget.py` — load/increment/check
- `libs/autonomy/gates.py` — checkpoint gate evaluation
- `libs/autonomy/hypothesis_lifecycle.py` — lifecycle transitions
- `libs/autonomy/repetition.py` — fingerprinting and near-duplicate detection
- `libs/autonomy/context_summary.py` — periodic summarization
- `libs/autonomy/operators/__init__.py`
- `libs/autonomy/operators/loop_decide.py` — core loop operator
- `libs/autonomy/operators/loop_report.py` — completion report operator
- `libs/storage/models/autonomy.py` — AutonomyBudget + LoopDecision ORM
- `libs/storage/migrations/versions/20260415_000001_phase5_autonomy.py`
- `libs/schemas/autonomy.py` — API schemas
- `apps/api/routers/autonomy.py` — 7 endpoints
- `apps/cli/commands/autonomy.py` — 5 subcommands

### Modified backend / library files

- `libs/core/types.py` — added `loop_deciding` to `CycleStatus`
- `libs/core/state_machine.py` — added `loop_deciding` transitions
- `libs/core/event_types.py` — added `AutonomyEvents` (12 events)
- `libs/remediation/operators/recommend.py` — autonomous-mode routing (~15 lines)
- `libs/protocols/operators/compile.py` — `variation_context` and `from_loop` support
- `libs/storage/models/__init__.py` — registered AutonomyBudget and LoopDecision
- `apps/worker/executor.py` — registered autonomy operators
- `apps/api/main.py` — mounted autonomy router
- `apps/cli/main.py` — registered autonomy subcommand

### Frontend

- `apps/web/src/api/autonomy.ts` — new TypeScript API client with types and 7 fetch functions
- `apps/web/src/components/AutonomyPanel.tsx` — autonomy dashboard panel (mode badge, resume/stop buttons, policy summary, budget bars, decisions timeline)
- `apps/web/src/components/StatusBadge.tsx` — added colors for `loop_deciding`, Phase 5 hypothesis lifecycle, and autonomy modes
- `apps/web/src/routes/charters/$charterId.tsx` — mounted `AutonomyPanel` below the Active Cycle section

### Tests

- `tests/unit/test_state_machine_phase5.py` — 16 tests for new transitions
- `tests/unit/test_autonomy_policy.py` — 10 tests for policy parsing
- `tests/unit/test_autonomy_budget.py` — 10 tests for budget checks
- `tests/unit/test_hypothesis_lifecycle.py` — 21 tests for lifecycle transitions
- `tests/unit/test_autonomy_gates.py` — 18 tests for gate evaluation
- `tests/unit/test_autonomy_repetition.py` — 14 tests for fingerprinting and near-duplicate detection

### Fixed regressions

- `tests/unit/test_phase4_remediation_runtime.py` — added `get()` method to `_FakeRecommendSession` to return a supervised-mode cycle stub, since `recommend` operator now loads the cycle to check autonomy mode

---

## Verification Status

The repository passes code-level quality gates after Phase 5:

- `uv run ruff check .` — passes
- `uv run pyright` — passes (0 errors, 0 warnings)
- `uv run pytest` — `230 passed` (141 existing Phase 0-4 + 89 new Phase 5)
- `cd apps/web && npm run build` — passes

---

## What Remains Before Phase 5 Can Be Called Fully Verified

1. **Run the migration against live Postgres.**
2. **End-to-end autonomous loop test.** Create cycle with `config.autonomy.mode = "autonomous"`, seed hypotheses, run through loop, verify budget increments, hypothesis lifecycle transitions, loop continuation on `continue_current`, variation on `parameter_variation`, termination on budget exhaustion, and completion report generation.
3. **Completion report rendering in UI.** The backend writes markdown + JSON to `{data_root}/reports/cycles/{cycle_id}/completion/`; the frontend currently shows the decision timeline and budget but does not yet render the final report bundle.
4. **Gate pause/resume end-to-end.** Configure `after_every_n_runs: 2`, verify loop pauses after 2 runs (job status = paused, cycle stays in `loop_deciding`), call `POST /cycles/{id}/autonomy/resume`, verify job returns to pending and loop continues.
5. **Repetition detection smoke test.** Force same spec 3 times, verify repetition detection escalates to parameter variation.
6. **Context summary integration.** Verify summary generated at iteration 5 and included in variation prompt.

---

## What Is Explicitly Still Out of Scope

- `regenerate_hypotheses` action (deferred — completion report recommends manual regeneration on `stop_exhausted`)
- Dollar-cost budgets (deferred — `AutonomyBudget` designed to accommodate them later)
- Cross-charter pattern memory (Phase 6)
- Re-embedding the corpus or supporting alternate embedding models — locked to `gte-modernbert-base` / 768
- Semantic Scholar / OpenAlex / Crossref source adapters — deferred
- An OpenAPI codegen pipeline for the web client — types stay manual for now

---

## Phase 4 Session Summary (retained for reference)

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
