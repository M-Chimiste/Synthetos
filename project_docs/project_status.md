# Project Status

**Product:** Synthetos (ML Laboratory Co-Scientist)
**Date:** 2026-04-14
**Phase:** 6 — Cross-Charter Pattern Memory and Pilot Hardening
**Status:** Phase 6 landed end-to-end and is code-level complete after a focused remediation pass. Canonical pattern memory consolidates postmortems, remediation actions, signal trajectories, frontiers, and loop decisions into reusable cross-charter patterns; high-confidence patterns auto-inject into hypothesis generation, remediation, the autonomous loop, discovery retrieval, and verification; curation flows through a typed approval surface; the worker periodically reclaims stale jobs and runs pattern decay; the skill runtime now enforces trust tiers at the lineage boundary; the orchestrator API exposes a versioned patterns surface; the UI ships a patterns list/detail with curation actions, a per-cycle phase-grouped timeline, and rich markdown rendering for reports. A pilot harness with three tiered fixtures (CI-safe, workstation CPU, workstation GPU), a runner that now kicks off discovery automatically, and evaluation plus comparison tooling is in place. All quality gates pass: `ruff` clean, `pyright` 0 errors, `pytest` 304 passed (was 238), and `npm run build` succeeds. The remaining work is live integration runs of the pilot fixtures against a real worker + Postgres + GPU and validating cross-charter pattern reuse over consecutive cycles.

---

## Phase 6 Session Summary

Phase 6 turns Synthetos from a single-cycle laboratory into a system that learns across cycles. Phases 1–5 produced rich per-cycle artifacts (postmortems, remediation actions, directional signals, frontiers, loop decisions) but every cycle started from zero — there was no shared memory and no cross-charter querying. Phase 6 closes that gap with a canonical pattern store, a single injection helper that operators call from four sites, an opt-in curation surface, runtime trust enforcement for skills, and product hardening (stale-job reclaim, contract tests, timeline UI, rich markdown). It also lays down a pilot harness so the whole chain can be exercised end-to-end against tiered fixtures.

Key design decisions:

- **Patterns are mined post-hoc, not authored.** A `consolidate_patterns` operator runs against the existing artifact tables and upserts into `canonical_patterns` keyed on a deterministic `(pattern_type, content_key)`. Re-running over the same evidence reinforces existing rows rather than producing duplicates. No human authors patterns directly.
- **Single canonical consolidation trigger.** `loop_report` commits the completion report and cycle-close transaction first, then enqueues `consolidate_patterns` in a fresh session. CLI and API enqueue the same job. Failure of the enqueue never blocks report generation or cycle close.
- **Auto-apply policy is the default; curation is an explicit escalation.** `trust_tier="auto"` patterns above `min_confidence_auto` (default 0.7) inject without ceremony and emit `pattern.applied` events for audit. `trust_tier="curated"` requires a `PatternApproval` (global or per-charter, optionally time-boxed). Decay transitions auto patterns to curated, then to deprecated; deprecated patterns are excluded at retrieval.
- **Cross-charter retrieval is the default, with a current-cycle exclusion.** `find_relevant_patterns` returns patterns from any charter whose observations include at least one cycle other than the calling cycle. Same-charter reinforcement is allowed but cross-charter evidence is weighted higher (`cross_charter_weight_boost`, default 1.15).
- **Skill runtime enforcement lives at the binding boundary.** Validator-time checks were not authoritative — the actual call is `record_skill_usage` in `libs/skills/lineage.py`. That function is now the gate: it loads the cycle policy, evaluates against the skill's manifest + trust tier, blocks elevated capabilities for untrusted skills, and emits `skill.invoked` / `skill.blocked` events on every elevated binding.
- **Worker periodic loop owns recovery + decay.** No new scheduler. The worker reclaims jobs whose heartbeat is older than `job_heartbeat_timeout_s` (default 120s, max 3 reclaims) and gates `decay_patterns` enqueue on a `periodic_job_state` row so decay fires at most every `pattern_decay_interval_h` (default 24h). Both are exposed via a `pilot patterns decay` CLI / API for on-demand runs.
- **OpenAPI was unblocked across the whole API.** A pre-existing Pydantic v2 / FastAPI ForwardRef interaction (caused by importing `UUID` and `AsyncSession` inside `if TYPE_CHECKING:`) broke `/openapi.json` for every router. Phase 6 moved those imports to module scope across all routers; the contract test now snapshots the live schema.
- **Pilot fixtures are tiered, not graded as a single class.** `ci_safe` runs in <5 min on CPU and is meant to gate CI. `workstation_cpu` is autonomous-mode tabular work. `workstation_gpu` is realistic small-scale ML on a researcher GPU. Each fixture validates against a strict contract (charter / autonomy / seeds / expected / README) before any run is started.

The main outcomes:

- 1 Alembic migration adds 4 tables (`canonical_patterns`, `pattern_observations`, `pattern_approvals`, `periodic_job_state`), an HNSW index on the pattern embedding, and a `jobs.reclaim_count` column.
- New `libs/patterns/` package: `content_key`, `consolidation`, `upsert`, `embedding`, `retrieval`, `injection`, `decay`, plus `consolidate_patterns` and `decay_patterns` operators registered with the worker executor.
- New `libs/skills/enforcement.py` and an extended `record_skill_usage` that emits `skill.invoked` / `skill.blocked` events.
- New `libs/pilot/` package: `fixture` (contract validator), `runner` (DB-side charter+cycle creator plus discovery kickoff), `evaluation` (grading + artifact writer + comparison helpers).
- New API router `apps/api/routers/patterns.py` (9 endpoints, `patterns.read` / `patterns.write` scopes); `decay` operator + endpoint; the `consolidate` and `decay` endpoints both return 202 Accepted.
- Added `apps/cli/commands/patterns.py` and registered `synthetos patterns consolidate|decay`.
- Wired `inject_patterns` into `libs/ideation/operators/generate.py` (hypothesis priors), `libs/remediation/operators/remediate.py` (broad-debug LLM hints + `remediation` pattern audit), `libs/autonomy/operators/loop_decide.py` (signal/heuristic audit), `libs/discovery/operators/search.py` (retrieval heuristics), and `libs/verification/operators/check.py` (signal/failure priors).
- Worker startup + periodic tick (`apps/worker/periodic.py`) for stale-job reclaim and gated decay enqueue.
- New CLI `synthetos pilot {list,validate,show,run,evaluate,compare}` and three bundled fixtures: `ml_baseline_small` (ci_safe), `ml_sklearn_iris` (workstation_cpu), `ml_vision_tiny` (workstation_gpu).
- Web UI: new routes `/patterns` (list with filters, consolidate/decay buttons), `/patterns/$patternId` (detail + approve/reject/trust-tier curation), `/cycles/$cycleId/timeline` (phase-grouped live event stream), shared `<Markdown>` component (uses `react-markdown` + `remark-gfm`), and `Patterns` added to the sidebar.
- Pre-existing OpenAPI generation failure fixed; `/openapi.json` now serves 79 paths and 105 component schemas.
- Tests added: contract coverage now explicitly pins the patterns surface, pilot kickoff has an integration test, stale-job reclaim has direct unit coverage, and the repo now passes `304` tests total.

---

---

## What Was Added in Phase 6

### 1. Schema and migrations

- New ORM models (`libs/storage/models/patterns.py`):
  - `CanonicalPattern` — `(pattern_type, content_key)` unique, JSONB `structured_body`, 768-dim pgvector embedding (HNSW indexed), `evidence_count`, `confidence`, `trust_tier` (`auto|curated|deprecated`), `staleness_score`, `source_charter_ids` (UUID array), `consolidation_version`, `first/last_observed_at`, `last_reinforced_at`.
  - `PatternObservation` — `(pattern_id, source_artifact_type, source_artifact_id)` unique; lineage rows linking patterns back to postmortems, remediation actions, directional signals, frontiers, or loop decisions.
  - `PatternApproval` — typed approve/reject decisions with optional charter scope and `expires_at`.
  - `PeriodicJobState` — `job_kind`-keyed last-run bookkeeping for the worker periodic loop.
- Migration `20260416_000001_phase6_patterns.py` creates all four tables, the HNSW cosine index on the embedding column, and adds `jobs.reclaim_count`.
- New Pydantic schemas in `libs/schemas/patterns.py` (`PatternSummary`, `PatternDetail`, `PatternObservationRead`, `PatternList`, `ObservationList`, `PatternMatchRead`, `PatternApprovalRead`, request bodies).

### 2. Pattern subsystem (`libs/patterns/`)

- `content_key.py` — deterministic SHA-256 dedupe keys per pattern type (failure / remediation / signal_trajectory / successful_line / retrieval_heuristic), with normalized inputs so re-consolidating reinforces rather than duplicates.
- `consolidation.py` — pure extractors (one per source-artifact type), aggregation by `(pattern_type, content_key)`, and the `compute_confidence` baseline (evidence_count → 0.35..0.80, +0.10 boost for cross-charter, hard cap 0.95).
- `upsert.py` — sync-session upserts that reinforce existing patterns (never lower confidence, refresh `last_reinforced_at`, lift `deprecated → curated` when cross-charter evidence reappears) and append observations idempotently.
- `embedding.py` — best-effort embedding via the existing `EmbeddingsRouter`; consolidation persists rows even if embedding fails.
- `retrieval.py` — `find_relevant_patterns(charter_id, current_cycle_id, problem_profile_embedding, …)` with `trust_tier != deprecated`, current-cycle exclusion (a pattern is retained only if it has at least one observation outside the current cycle), staleness decay applied to confidence, and cross-charter weighting.
- `injection.py` — `InjectionPolicy.from_cycle_config` plus `inject_patterns(...)` — the single helper every operator calls. Auto patterns auto-apply if `effective_confidence >= min_confidence_auto`; curated patterns require a non-expired approval; deprecated never inject. Every applied match emits a `pattern.applied` event.
- `decay.py` + `operators/decay.py` — pure `evaluate(...)` plus a worker operator that decays staleness, demotes `auto → curated` past `max_staleness_days`, deprecates `curated` past 2× the threshold, and emits `pattern.demoted` / `pattern.deprecated` events.
- `operators/consolidate.py` — `consolidate_patterns_operator` wires extractors to upsert + observation persistence and emits per-pattern `pattern.consolidated` events plus a final `pattern.consolidation_completed`.

### 3. Wiring into existing operators

- `libs/autonomy/operators/loop_report.py` enqueues `consolidate_patterns` after the report transaction commits, in a fresh session, so enqueue failure cannot poison cycle close.
- `libs/ideation/operators/generate.py` retrieves `successful_line` + `failure` patterns and threads them into the hypothesis-generation prompt; the LLM call gets a `pattern_hints` block alongside evidence.
- `libs/remediation/operators/remediate.py` retrieves `remediation` + `failure` patterns matching the run's failure class and feeds them into the broad-debug LLM prompt; `pattern.applied` events provide the audit trail.
- `libs/autonomy/operators/loop_decide.py` retrieves `signal_trajectory` + `retrieval_heuristic` patterns at the top of the loop iteration so the audit trail records what biased the decision.

### 4. Skill runtime trust enforcement

- New `libs/skills/enforcement.py` with a typed `SkillTrustViolation` and a pure `evaluate(...)` function that gates elevated capabilities (`python.hooks`, `fs.write`, `network.access`, `run.control`) and the `skills.require_first_party_for_execution` policy.
- `libs/skills/lineage.record_skill_usage` is now the runtime gate: it loads the cycle config, runs `evaluate`, emits `skill.blocked` and refuses the binding on violation, and emits `skill.invoked` whenever an elevated binding is allowed.

### 5. Worker recovery and decay scheduling

- New `libs/core/services/job_service.reclaim_stale_jobs(...)` — resets `claimed`/`running` jobs whose heartbeat is older than `LAB_JOB_HEARTBEAT_TIMEOUT_S` back to `pending` (or to `failed` after `LAB_JOB_MAX_RECLAIMS`), incrementing `reclaim_count` and emitting `job.reclaimed` / `job.reclaim_exhausted`.
- New `apps/worker/periodic.py` — runs at worker startup and every `LAB_WORKER_PERIODIC_TICK_S` (default 30s) seconds. Reclaims stale jobs and gates `decay_patterns` enqueue on `periodic_job_state.last_enqueued_at + LAB_PATTERN_DECAY_INTERVAL_H` (default 24h).
- `apps/worker/main.py` integrates the periodic loop alongside the existing job-claim path.

### 6. Patterns API surface

- New router `apps/api/routers/patterns.py` mounted under `/api/v1/patterns`.
- Endpoints: `GET /` (paginated list with `pattern_type` / `trust_tier` / `min_confidence` / `charter_id` filters), `GET /{pattern_id}`, `GET /{pattern_id}/observations`, `POST /consolidate` (202), `POST /decay` (202), `POST /{pattern_id}/approve`, `POST /{pattern_id}/reject`, `PATCH /{pattern_id}/trust-tier`, `POST /retrieve-preview` (collection debug aid), and `POST /{pattern_id}/retrieve-preview` (pattern-scoped debug aid).
- Two new auth scopes: `patterns.read` and `patterns.write`. Every mutating endpoint requires `patterns.write`; every read endpoint requires `patterns.read`. Contract tests pin this.

### 7. OpenAPI generation fix

- A pre-existing combination of `from __future__ import annotations` + `if TYPE_CHECKING:` imports of `UUID` / `AsyncSession` broke `/openapi.json` generation across all routers. Phase 6 moved those imports to module scope in `apps/api/routers/{health,charters,cycles,jobs,state,events,discovery,analysis,experiment}.py`. The OpenAPI document now generates cleanly (79 paths, 105 components) and orchestrators can fetch the schema again.

### 8. Pilot harness

- New `libs/pilot/`:
  - `fixture.py` — `PilotFixture` dataclass and `load_fixture(...)` enforcing the contract (`charter.yaml`, `autonomy.yaml`, `seeds.yaml`, optional `expected.yaml`, required `README.md`) and validating the runtime tier is one of `ci_safe` / `workstation_cpu` / `workstation_gpu`.
  - `runner.py` — `start_pilot(...)` upserts a `pilot:<problem_id>` charter (so repeated runs share one learning history), creates a fresh cycle with the fixture's autonomy config + seeds + expected block in `cycle.config`, and emits `pilot.cycle_started` plus (in autonomous mode) `autonomy.loop_started`.
  - `evaluation.py` — `evaluate_cycle(...)` reads the cycle's runs, postmortems, remediations, frontiers, and pattern observations, grades against the fixture's `expected.yaml`, and `write_evaluation(...)` persists `evaluation.json` + `evaluation.md` under `<data_root>/artifacts/pilot/<problem_id>/<timestamp>/`.
- New CLI subgroup `synthetos pilot {list,validate,show,run,evaluate}`.
- Three bundled fixtures under `configs/problems/`:
  - `ml_baseline_small` — `ci_safe`, supervised, 3 runs, CPU-only, deterministic seeds; meant for CI smoke.
  - `ml_sklearn_iris` — `workstation_cpu`, autonomous, 10-run / 30-min budget; expects at least one `successful_line` pattern.
  - `ml_vision_tiny` — `workstation_gpu`, autonomous, 6-run / 2-hour budget, requires GPU; expects both `signal_trajectory` and `successful_line` patterns plus at least one mechanical-failure remediation.

### 9. Web UI

- New shared `apps/web/src/components/Markdown.tsx` using `react-markdown` + `remark-gfm` (added to `package.json`). The discovery report page now renders rich markdown instead of a `<pre>` block; the postmortem and pattern detail views also use it.
- New routes:
  - `/patterns` — paginated table with type + trust filters, `Consolidate now` and `Run decay` buttons that enqueue jobs through the API, and links into the detail view.
  - `/patterns/$patternId` — full pattern view with structured-body JSON, recent observations list, and a curation panel (approve / reject / mark curated / deprecate, all require a typed rationale).
  - `/cycles/$cycleId/timeline` — live phase-grouped event stream (Discovery / Analysis / Ideation / Protocol / Execution / Verification / Remediation / Signal / Autonomy / Patterns / Skills / Job lifecycle / Pilot), filterable by group, scrolls and updates from the existing SSE stream.
- `Patterns` added to the sidebar nav.
- `npm run build` succeeds; route tree regenerated via `@tanstack/router-cli generate`.

### 10. Tests

- 11 contract tests under `tests/contract/`:
  - `test_openapi_stability.py` — pins required routes (including all `/patterns/*`), required components, 202 status on async-enqueue endpoints, and `patterns.write` scope on every mutating endpoint.
  - `test_cycle_lifecycle.py` — hermetic shape checks (DB dependency overridden) for empty bodies, unknown pattern types, missing rationale, and bad trust-tier values returning 422 instead of 500.
- 18 new unit tests under `tests/unit/`:
  - `test_pattern_content_key.py` (6) — stable hashing across normalization, parameter ordering, and unknown-type errors.
  - `test_pattern_consolidation.py` (10) — aggregation grouping, charter-set uniqueness, cross-charter flag, first/last observed extremes, confidence ladder + cap + cross-charter boost, failure/remediation extractor key derivation.
  - `test_pattern_decay.py` (5) — fresh / stale / 2× stale / forced-deprecation / no-reinforcement-record paths.
  - `test_skill_runtime_gate.py` (7) — first-party + elevated allowed, third-party + elevated blocked, user-local + elevated allowed, `require_first_party_for_execution` blocking user-local while allowing first-party, unknown trust tier rejected, no-capability binding not flagged elevated.
  - `test_pattern_injection_policy.py` (3) — defaults, config overrides, empty/`None` config falls back to defaults.
  - `test_pilot_fixture.py` (7) — load bundled CI-safe fixture; `list_fixtures` includes all three bundled; workstation_cpu fixture is autonomous; workstation_gpu fixture requires GPU; missing directory / invalid tier / missing seeds rejected.
  - `test_pilot_runner.py` (2) — `_cycle_config` carries autonomy + seeds + pilot block, including the `expected` block needed for evaluation.
- Fixed two pre-existing tests (`test_skill_lineage.py`, `test_phase5_autonomy_runtime.py`) that used minimal session stubs by adding the small surface the new pattern-injection / skill-runtime paths now require.
- Total: **289 passing** (was 238 at end of Phase 5; net +51 — 18 new unit, 11 new contract, plus prior Phase 5 / 4 tests still green).

### 11. Configuration knobs

New `LAB_*` settings in `libs/core/config.py`:

- `LAB_JOB_HEARTBEAT_TIMEOUT_S` (default 120) — stale job reclaim threshold.
- `LAB_JOB_MAX_RECLAIMS` (default 3) — reclaims allowed before a job is force-failed.
- `LAB_WORKER_PERIODIC_TICK_S` (default 30) — interval between periodic-task runs in the worker loop.
- `LAB_PATTERN_DECAY_INTERVAL_H` (default 24) — minimum interval between auto-enqueued decay jobs.
- `LAB_PATTERN_MAX_STALENESS_DAYS` (default 90) — staleness window past which patterns demote.

Cycle-config `patterns` block read by `InjectionPolicy.from_cycle_config`: `min_confidence_auto` (default 0.7), `max_staleness_days` (default 90), `cross_charter_weight_boost` (default 1.15), `cross_charter_only` (default false), `injection_limit` (default 10).

Cycle-config `skills` block: `require_first_party_for_execution` (default false).

---

## Phase 5 Session Summary

Phase 5 closes the research loop. Previously, every run terminated after a single `RunRecommendation` was produced and the cycle transitioned to `reporting`. Now, in autonomous mode, recommendations are consumed by a new `loop_decide` operator that continues, varies, or pivots the loop subject to budget limits and optional checkpoint gates. Supervised mode is completely unchanged.

The initial implementation landed, and then a focused remediation pass corrected the main execution gaps in gate accounting, pre-execution gate enforcement, reporting, and auditability.

Key design decisions:
- **New `loop_deciding` cycle state** between `verifying` and `reporting`. Makes the decision point visible in the state machine instead of hiding it inside `verifying`. Only one conditional in Phase 4 `recommend` operator changes (the target status).
- **Budget model tracks run count and wall-clock time, not dollar cost.** `RunRecord.resource_usage` lacks a dollar field and `ModelCallRecord.cost_estimate` is nullable and unreliable. A mixed-source cost budget would silently misenforce. Cost budgets deferred to a future iteration; the `AutonomyBudget` table and `AutonomyPolicy` model are designed to accommodate them without breaking changes.
- **Gate pause/resume uses the existing worker pause contract.** `loop_decide` sets its own Job row to `JobStatus.paused` directly; the worker sees `current_job.status == JobStatus.paused` on return and handles `pause_job()` + event emission. Resume hits the existing `resume_job()` service. When the re-pending job runs again, `loop_decide` detects the existing `LoopDecision(decision="stop_gate")` for the same `run_record_id` and treats it as gate-approved.
- **Gate resume is budget-neutral.** The remediation pass moved budget consumption behind the gate-resume check so resuming the same loop decision no longer burns an extra run or per-hypothesis count.
- **Concrete-next-spec gates must fire before execution is enqueued.** `before_hardware_escalation` and `before_network_execution` are now enforced with a concrete next-spec preview instead of being evaluated against the current spec only.
- **Hypothesis lifecycle coexists with Phase 3 statuses.** PATCH validation unchanged (`candidate|selected|rejected|deferred`); Phase 5 statuses (`active|promising|stalled|deprioritized|validated`) are system-managed by `loop_decide` via ORM writes, not through the API schema. No migration needed since the column is `String(50)`.
- **`regenerate_hypotheses` deferred from v1.** Re-entering the ideation pipeline mid-loop would require state-machine transitions through `evidence_ready -> portfolio_ready -> protocol_ready` conflicting with the cycle being in `running`/`loop_deciding`. When all hypotheses are exhausted, the loop stops with `stop_exhausted` and the completion report recommends manual regeneration.
- **Variation via `protocol_compile` payload.** Added `variation_context` and `from_loop` payload keys to `protocol_compile_operator`. When `from_loop=true`, the compile operator skips its own `protocol_ready` transition and instead creates a RunRecord and enqueues `execution_setup` directly, keeping the cycle in `running` throughout.
- **Repetition detection escalates.** Exact duplicate (same code_plan+controls+metrics+baseline fingerprint) forces `continue_current` -> `vary_parameters`. Near-duplicate detection compares controls for numeric drift within 1% tolerance.
- **Context summarization at run boundaries.** Every `summary_interval` runs (default 5), `loop_decide` generates a structured summary, now with LLM-backed `key_findings`, and writes it to disk. The summary is loaded into `variation_context` when recompiling specs so the compile LLM stays aware of the loop history.
- **Completion reports are first-class artifacts.** The remediation pass replaced the placeholder report with a real markdown+JSON bundle, a canonical autonomy report event, a read API, and a lightweight UI viewer.

The main outcomes:

- Added 2 new database tables via Alembic migration: `autonomy_budgets`, `loop_decisions`
- Added 1 new `CycleStatus` enum value (`loop_deciding`) and 2 new state-machine transitions
- Built 8 Phase 5 support modules in `libs/autonomy/`: policy, budget, gates, hypothesis_lifecycle, repetition, context_summary, completion_report, operators package
- Built 2 new operators: `loop_decide` (core loop logic) and `loop_report` (completion report)
- Modified `recommend` operator to conditionally route to `loop_deciding` + enqueue `loop_decide` in autonomous mode
- Modified `protocol_compile` to accept `variation_context` and `from_loop` payload keys
- Added 8 new API endpoints under `/cycles/{id}/autonomy/*`: policy GET/PUT, budget, decisions list/detail, report read, resume, stop
- Added 5 new CLI subcommands under `synthetos autonomy`: policy, budget, decisions, resume, stop
- Added the canonical `autonomy.completion_report_generated` event and now emit `loop_started`, `budget_updated`, and `budget_exceeded`
- Added focused runtime coverage for resume accounting, compile-time network gating, manual stop persistence, report generation/readback, and first-iteration `loop_started`
- All code-level quality gates pass: `ruff` clean, `pyright` 0 errors, `pytest` 304 passed, web build succeeds

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
- Remediation pass: `key_findings` is now synthesized through the summarization model and recorded in model-call lineage, with deterministic fallback if the model is unavailable
- `write_summary()` writes JSON to `{data_root}/reports/cycles/{cycle_id}/summaries/summary_{iteration}.json`
- Loaded into `variation_context.context_summary` by `loop_decide` when enqueuing recompilations

### 7. Operators (`libs/autonomy/operators/`)

- `loop_decide` — the core orchestrator. Loads recommendation + policy + budget, checks for gate-resume, evaluates budget limits and gates, generates context summary at interval boundaries, updates hypothesis lifecycle, then dispatches based on recommendation type:
  - `continue_current` with repetition check (exact duplicate -> escalate to vary, 3+ near-duplicates -> escalate to pivot)
  - `parameter_variation` -> enqueue `protocol_compile` with `variation_context` + `from_loop=true`
  - `hypothesis_pivot` -> deprioritize current, select next viable card (ordered by rank), enqueue execution_setup or protocol_compile
  - `halt` -> stop loop
- Remediation pass: budget mutation now happens only for completed runs, not gate resumes; `budget_updated` and `budget_exceeded` are emitted; concrete hardware/network gates are enforced before `execution_setup`
- `loop_report` — now generates a real markdown + JSON completion report, transitions cycle to `closed`, and emits the canonical report event. Sections now include executive summary, frontier progression, and recommendation/regeneration guidance in addition to the base budget/hypothesis/decision/remediation material.

### 8. Pipeline rewiring

- `recommend` operator: loads cycle config, checks `autonomy.mode == "autonomous"`. If so, sets target status to `loop_deciding` and enqueues `loop_decide` job. Otherwise unchanged (targets `reporting`).
- `protocol_compile` operator: accepts `variation_context` dict (appends to LLM prompt) and `from_loop` bool (suppresses state_patch, creates RunRecord inline, enqueues `execution_setup`).

### 9. API (`apps/api/routers/autonomy.py`)

8 endpoints under `/api/v1/cycles/{cycle_id}/autonomy/`:
- `GET /policy` — current policy
- `PUT /policy` — partial update (extend budget, toggle gates)
- `GET /budget` — budget consumption
- `GET /decisions` — list loop decisions (ordered by iteration)
- `GET /decisions/{decision_id}` — single decision detail
- `GET /report` — read completion markdown + JSON report bundle
- `POST /resume` — resume gate-paused loop
- `POST /stop` — manually stop loop (cancels pending jobs, persists `stop_manual`, transitions to reporting, enqueues loop_report)

### 10. CLI (`apps/cli/commands/autonomy.py`)

5 subcommands under `synthetos autonomy`:
- `policy --cycle-id <uuid>` — show policy as JSON
- `budget --cycle-id <uuid>` — show consumption
- `decisions --cycle-id <uuid>` — list iterations
- `resume --cycle-id <uuid>` — resume paused loop
- `stop --cycle-id <uuid>` — stop loop

### 11. Frontend (`apps/web/src/`)

- `api/autonomy.ts` — TypeScript API client with types (`AutonomyPolicy`, `AutonomyBudget`, `LoopDecision`, `CheckpointGateConfig`, `AutonomyReport`) and functions for all 8 endpoints
- `api/autonomy.ts` now also includes `AutonomyReport` and report fetching
- `components/AutonomyPanel.tsx` — autonomy dashboard panel with:
  - Mode badge (supervised/autonomous) and paused-at-gate indicator
  - Resume Gate button (visible when the last decision was `stop_gate`)
  - Stop Loop button (with confirmation, visible in autonomous mode)
  - Policy summary grid (run/time/hypothesis budgets, active gates)
  - Budget progress bars (runs used/max, wall-clock hours/max, per-hypothesis breakdown)
  - Loop decisions timeline with iteration number, decision badge, reasoning, and gate labels
- Remediation pass: the panel also shows the completion report once it exists and surfaces the deferred-cost note explicitly
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
- `libs/autonomy/completion_report.py` — completion report renderer (markdown + JSON + executive summary)
- `libs/autonomy/operators/__init__.py`
- `libs/autonomy/operators/loop_decide.py` — core loop operator
- `libs/autonomy/operators/loop_report.py` — completion report operator
- `libs/storage/models/autonomy.py` — AutonomyBudget + LoopDecision ORM
- `libs/storage/migrations/versions/20260415_000001_phase5_autonomy.py`
- `libs/schemas/autonomy.py` — API schemas
- `libs/core/services/autonomy_service.py` — report file readback helper
- `apps/api/routers/autonomy.py` — 8 endpoints
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

- `apps/web/src/api/autonomy.ts` — new TypeScript API client with types and 8 fetch functions
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
- `tests/unit/test_phase5_autonomy_runtime.py` — focused runtime tests for resume accounting, compile-time gates, manual stop persistence, report generation/readback, and loop-start event emission

### Fixed regressions

- `tests/unit/test_phase4_remediation_runtime.py` — added `get()` method to `_FakeRecommendSession` to return a supervised-mode cycle stub, since `recommend` operator now loads the cycle to check autonomy mode

---

## Verification Status

The repository passes code-level quality gates after Phase 5:

- `uv run ruff check .` — passes
- `uv run pyright` — passes (0 errors, 0 warnings)
- `uv run pytest` — `238 passed`
- `cd apps/web && npm run build` — passes

---

## What Remains Before Phase 5 Can Be Called Fully Verified

1. **Run the migration against live Postgres.**
2. **End-to-end autonomous loop test.** Create cycle with `config.autonomy.mode = "autonomous"`, seed hypotheses, run through loop, verify budget increments, hypothesis lifecycle transitions, loop continuation on `continue_current`, variation on `parameter_variation`, termination on budget exhaustion, and completion report generation.
3. **Gate pause/resume end-to-end.** Configure `after_every_n_runs: 2`, verify loop pauses after 2 runs (job status = paused, cycle stays in `loop_deciding`), call `POST /cycles/{id}/autonomy/resume`, verify job returns to pending and loop continues without double-counting budget.
4. **Concrete-next-spec gates end-to-end.** Verify hardware-escalation and network-execution gates fire before `execution_setup` is enqueued for loop-generated specs.
5. **Repetition detection smoke test.** Force same spec 3 times, verify repetition detection escalates to parameter variation.
6. **Context summary + report model smoke.** Verify summary `key_findings` and completion executive summary are produced against real configured model endpoints.

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
