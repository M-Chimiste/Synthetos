# Phase 4: Remediation, Directional Signal, and Frontier Tracking

## Context

Phase 3 delivered a complete hypothesis-to-verification pipeline, but the execution loop treats every failure as terminal — a failed run goes straight to LLM-generated postmortem and stops. Phase 4 makes the loop resilient (auto-remediate mechanical failures before spending LLM tokens on postmortem) and research-aware (classify whether progress is being made, track the best-known result per hypothesis line, and recommend what to do next). This bridges Phase 3's deterministic lab with Phase 5's autonomous decision-making.

The roadmap's exit criteria require that:
- Common mechanical failures are retried through remediation before postmortem
- Successful runs receive directional signal classification
- Frontier state is visible and updates correctly
- Recommendations distinguish mechanical recovery vs parameter variation vs hypothesis pivots
- Resolved mechanical failures don't pollute scientific failure memory

---

## Pipeline Change

Current (Phase 3):
```
verification_check(failed)  →  verification_postmortem  →  reporting
verification_check(passed)  →  reporting
```

Phase 4:
```
FAILED PATH:
verification_check(failed)  →  auto_remediate  →  retry (new RunRecord → execution_setup → ...)
                                     OR         →  verification_postmortem  →  recommend  →  reporting

PASSED PATH:
verification_check(passed)  →  signal_classify  →  recommend  →  reporting
```

Both terminal paths converge on `recommend` → `reporting`. The `recommend` operator is the single gateway to the `reporting` state — it always runs last, whether the run succeeded or failed.

- **Passed runs**: `verification_check` → `signal_classify` → `recommend` → reporting
- **Failed + remediated**: `auto_remediate` creates retry → goes through full pipeline again
- **Failed + exhausted/non-remediable**: `auto_remediate` → `verification_postmortem` → `recommend` → reporting

The existing `verification_postmortem` operator currently sets `state_patch={cycle_status: "reporting"}`. Phase 4 changes it to enqueue `recommend` instead and return without a state_patch. The `recommend` operator is the one that sets `state_patch={cycle_status: "reporting"}`.

Remediation operates entirely within existing cycle states (`verifying` → `running` on retry, `verifying` → `reporting` when exhausted). No state machine changes needed.

---

## 1. Primary Metric Selection Rule

The current ExperimentSpec.metrics is a list of `{name, direction, threshold?, min?, max?}` with no explicit primary designation. Phase 4 needs a single optimization target for signal classification and frontier tracking.

**Rule**: The first metric in the spec's `metrics` list is the primary metric. All others are constraint metrics. This is consistent with ML convention (optimize accuracy, constrain memory/latency).

**Enforcement**: Add an optional `primary: bool` field to the metric dict in the protocol compilation prompt so the LLM can be explicit. If no metric has `primary: true`, fall back to `metrics[0]`. Validation in `validate_spec()` warns if no metric is marked primary.

**Schema change**: Add `primary_metric_index: int = 0` to `ExperimentSpec` (nullable, defaults to 0 for existing specs). This is a non-breaking addition.

---

## 2. Database Tables

### New table: `remediation_actions`
| Column | Type |
|---|---|
| id | UUID PK |
| run_record_id | FK → run_records (the failed run) |
| retry_run_id | FK → run_records, nullable (the retry run, if created) |
| charter_id, cycle_id, experiment_spec_id | FK refs for querying |
| failure_class | String(50) |
| strategy | String(50): install_deps, increase_memory, extend_timeout, fix_artifact_output, debug_broad, skip |
| strategy_tier | String(20): "focused" or "broad" |
| action_detail | JSONB (what changed: packages added, memory delta, patched files) |
| outcome | String(50): retry_created, skipped, exhausted |
| attempt_number | Integer (1-indexed in run lineage) |
| max_attempts | Integer (default 3) |
| reasoning | Text |
| created_at | DateTime |

Indexes: `(run_record_id)`, `(cycle_id, experiment_spec_id)`, `(retry_run_id)`

### New table: `directional_signals`
| Column | Type |
|---|---|
| id | UUID PK |
| run_record_id, charter_id, cycle_id, experiment_spec_id | FK refs |
| signal | String(50): advancing, stalled, regressing, noisy, breakthrough |
| primary_metric_name | String(200) |
| primary_metric_value | Float |
| primary_metric_delta | Float, nullable (delta from previous run) |
| primary_metric_direction | String(20): maximize or minimize |
| constraint_metrics | JSONB, nullable: `[{name, value, within_bounds}]` |
| history_window | JSONB: `[{run_id, value, created_at}]` |
| reasoning | Text |
| created_at | DateTime |

Indexes: `(run_record_id)`, `(experiment_spec_id, created_at)`, `(cycle_id)`

### New table: `metric_frontiers`

Keyed by `(charter_id, hypothesis_card_id)` — per hypothesis line, not per spec. A hypothesis line may produce multiple specs over time (e.g., after remediation patches or protocol recompilation), but the frontier tracks progress at the hypothesis level.

| Column | Type |
|---|---|
| id | UUID PK |
| charter_id | FK → research_charters |
| hypothesis_card_id | FK → hypothesis_cards |
| primary_metric_name | String(200) |
| primary_metric_direction | String(20) |
| best_run_id | FK → run_records |
| best_experiment_spec_id | FK → experiment_specs (which spec produced the best run) |
| best_metric_value | Float |
| best_achieved_at | DateTime |
| total_runs | Integer (all runs in the line, including failed) |
| successful_runs | Integer |
| runs_since_improvement | Integer |
| updated_at, created_at | DateTime |

Indexes: `(charter_id, hypothesis_card_id)` UNIQUE, `(best_run_id)`

### New table: `run_recommendations`
| Column | Type |
|---|---|
| id | UUID PK |
| run_record_id | FK → run_records |
| charter_id, cycle_id, experiment_spec_id | FK refs |
| recommendation_type | String(50): mechanical_recovery, parameter_variation, hypothesis_pivot, continue_current, halt |
| action | Text (specific next-step recommendation) |
| reasoning | Text (why this recommendation, citing signal + frontier + history) |
| inputs_summary | JSONB: snapshot of signal, frontier state, remediation count, postmortem patterns used to produce this |
| created_at | DateTime |

Indexes: `(run_record_id)`, `(cycle_id)`

### Modified table: `run_records`
Add column: `parent_run_id UUID FK(run_records.id, nullable)` for retry lineage tracking.

### Modified table: `experiment_specs`
Add column: `primary_metric_index Integer, nullable, default 0`

### Modified table: `verification_reports`
Add columns:
- `directional_signal_id UUID FK(directional_signals.id, nullable)` — set by signal_classify operator
- `recommendation_id UUID FK(run_recommendations.id, nullable)` — set by recommend operator

VerificationReport is the canonical owner of these relationships — the signal and recommendation rows do NOT point back. This avoids circular FKs. To find the signal for a report, join on `verification_reports.directional_signal_id`. To find a report for a signal, query `verification_reports WHERE directional_signal_id = ?`.

---

## 3. Operators

### `auto_remediate` (libs/remediation/operators/remediate.py)

**Two-tier remediation**: focused first, then broad debug.

1. Load failed RunRecord, ExperimentSpec, and all RemediationAction rows for this lineage
2. Count attempts (follow parent_run_id chain). If >= max_attempts → outcome=exhausted, enqueue `verification_postmortem`
3. **Tier 1 — Focused remediation** (deterministic, no LLM):
   - `dependency`: parse stderr for missing module names → patch build_recipe to `pip install` them
   - `oom`: double memory_limit in resource_limits (up to configurable cap)
   - `timeout`: increase timeout by 50% (up to configurable cap)
   - `invalid_artifact`: compare expected_artifacts vs manifest, patch code_plan if naming/path mismatch
   - `metric_parse`: not auto-remediable → skip directly to postmortem
4. **Tier 2 — Broad debug** (LLM-assisted): activates when a focused strategy was already tried for this failure_class and the retry failed again with the same class. Sends error trace + prior remediation history + code_plan to LLM (ModelRole.evaluation) and asks for a code fix. The `strategy_tier` column distinguishes "focused" from "broad" attempts.
5. **Escalation rule**: attempt 1 always tries focused. If attempt 2 has the same failure_class as attempt 1 → escalate to broad. If attempt 2 has a different failure_class → use focused for the new class. Max 3 attempts total (configurable).
6. Create new RunRecord (parent_run_id=failed_run.id, run_number+1) with patched overrides in job payload
7. Persist RemediationAction row with strategy_tier
8. Enqueue `execution_setup` with `remediation_overrides` in payload
9. Emit `RemediationEvents.retry_created` or `RemediationEvents.exhausted`

Override delivery: patches go via job payload key `remediation_overrides` — ExperimentSpec stays immutable. `execution_setup` reads and merges. The override shape is `{code_plan?: dict, build_recipe?: dict, run_resource_limits?: dict}`. Note: `resource_limits` lives on RunRecord (not ExperimentSpec), so for oom/timeout remediation, `auto_remediate` sets the patched limits directly on the new RunRecord it creates. `execution_setup` only needs to merge `code_plan` and `build_recipe` overrides from the payload.

### `signal_classify` (libs/remediation/operators/signal.py)

1. Load all completed RunRecords for this hypothesis_card_id (across all specs in the line), ordered by completed_at
2. Identify primary metric from spec (`metrics[primary_metric_index]`)
3. Extract primary metric values across history
4. Classify using deterministic rules:
   - `breakthrough`: improvement >= 2 stddev from mean of prior runs (min 3 data points)
   - `advancing`: improvement over previous run (beyond 1% noise band)
   - `regressing`: wrong direction (beyond 1% noise band)
   - `noisy`: direction alternating for last 3+ consecutive runs
   - `stalled`: delta within noise band for last 3+ consecutive runs
   - First successful run → `advancing` (no comparison needed)
5. Check constraint metrics: each non-primary metric with min/max bounds → `{name, value, within_bounds}`
6. Persist DirectionalSignal row
7. Upsert MetricFrontier row (keyed on charter_id + hypothesis_card_id)
8. Set `VerificationReport.directional_signal_id` = new signal's ID (VerificationReport owns this FK)
9. Enqueue `recommend` operator
10. Emit `SignalEvents.signal_classified` and `SignalEvents.frontier_updated`/`frontier_created`

### `recommend` (libs/remediation/operators/recommend.py)

Produces a `RunRecommendation` after every terminal run (both successful and failed-then-exhausted paths).

**Inputs gathered:**
- DirectionalSignal for this run (if passed)
- MetricFrontier for this hypothesis line
- All RemediationAction rows for this spec (remediation history)
- All FailurePostmortem rows for this spec (postmortem patterns)
- Run count and success rate from frontier

**Decision rules** (deterministic, no LLM):

| Signal | Frontier | Remediation | → Recommendation |
|---|---|---|---|
| breakthrough | any | any | `continue_current` — keep running, this approach is working |
| advancing | improving | none/resolved | `continue_current` — on track |
| advancing | improving | unresolved | `parameter_variation` — tweak to avoid recurring failures |
| stalled | runs_since_improvement >= 5 | any | `hypothesis_pivot` — diminishing returns, try new hypothesis |
| stalled | runs_since_improvement < 5 | any | `parameter_variation` — try different hyperparams/controls |
| regressing | any | any | `parameter_variation` — recent changes hurt, revert or adjust |
| noisy | any | any | `parameter_variation` — reduce variance (larger samples, seeds) |
| N/A (failed) | any | exhausted | `hypothesis_pivot` — mechanical issues intractable for this approach |
| N/A (failed) | any | resolved | `continue_current` — recovered, proceed |

For edge cases or when the deterministic rules are ambiguous (e.g., conflicting constraint metrics), fall back to `parameter_variation` with explanatory reasoning.

**Output:**
1. Persist RunRecommendation row
2. Set `VerificationReport.recommendation_id` = new recommendation's ID (VerificationReport owns this FK)
3. Return state_patch={cycle_status: "reporting"}
4. Emit `SignalEvents.recommendation_produced`

**For failed-then-exhausted runs** (arrived via `verification_postmortem` → `recommend`): the `recommend` payload includes `{failed: true}`. In this case there is no DirectionalSignal — the operator uses only frontier state, remediation history, and postmortem history to produce the recommendation. The VerificationReport still gets `recommendation_id` set.

---

## 4. Modifications to Existing Code

### libs/verification/operators/check.py
- **Failed runs** (lines ~170, ~312-318): change enqueue target from `verification_postmortem` to `auto_remediate`
- **Passed/inconclusive runs** (line ~326-332): instead of returning with state_patch reporting, enqueue `signal_classify` and return without state_patch (signal_classify → recommend will set reporting)

### libs/execution/operators/run.py
- Add `invalid_artifact` to `_classify_failure()`: if exit_code == 0 but stderr contains "FileNotFoundError" or "artifact" signals → `invalid_artifact`

### libs/execution/operators/setup.py
- Read optional `remediation_overrides` from `op_input.payload`
- Merge overrides into spec's `code_plan` (patched files) and `build_recipe` (extra deps)
- Resource limits (memory/timeout) are already set directly on the RunRecord by `auto_remediate`, so `execution_setup` reads them from the run as it does today

### libs/protocols/validation.py
- Add warning if no metric has `primary: true` field

### apps/worker/executor.py
- Add `_register_remediation_operators()` block registering: `auto_remediate`, `signal_classify`, `recommend`

### libs/verification/operators/postmortem.py
- Remove `state_patch={"cycle_status": CycleStatus.reporting.value}` from the return
- Instead, enqueue `recommend` with `{run_record_id, failed: true}` in payload
- The `recommend` operator now owns the transition to `reporting`

### libs/schemas/experiment.py
- Add `parent_run_id: UUID | None = None` to `RunRecordRead`
- Add `primary_metric_index: int = 0` to `ExperimentSpecRead`
- Add `directional_signal_id: UUID | None = None` and `recommendation_id: UUID | None = None` to `VerificationReportRead`

### libs/storage/models/experiment.py
- Add `parent_run_id` column to `RunRecord`
- Add `primary_metric_index` column to `ExperimentSpec`
- Add `directional_signal_id` and `recommendation_id` columns to `VerificationReport`

### libs/core/event_types.py
- Add `RemediationEvents` and `SignalEvents` StrEnum classes (see section 5)

---

## 5. Event Types

```python
class RemediationEvents(StrEnum):
    remediation_started = "remediation.started"          # auto_remediate begins evaluation
    retry_created = "remediation.retry_created"          # new RunRecord created for retry
    strategy_escalated = "remediation.strategy_escalated"  # focused → broad debug
    skipped = "remediation.skipped"                      # failure class not remediable
    exhausted = "remediation.exhausted"                  # max attempts reached

class SignalEvents(StrEnum):
    signal_classified = "signal.classified"              # directional signal assigned
    frontier_created = "signal.frontier_created"         # first frontier for hypothesis line
    frontier_updated = "signal.frontier_updated"         # frontier best_run/value changed
    recommendation_produced = "signal.recommendation_produced"  # next-step recommendation
```

All events go to the main `/events/stream` SSE endpoint (they follow the existing pattern: `emit_event_sync` with charter_id + cycle_id + payload). The SSE consumer in the web app filters by prefix, so `remediation.*` and `signal.*` will be visible to any client listening for those prefixes.

---

## 6. New Files

| File | Purpose |
|---|---|
| `libs/remediation/__init__.py` | Package |
| `libs/remediation/operators/__init__.py` | `register()` for auto_remediate, signal_classify, recommend |
| `libs/remediation/operators/_common.py` | Lineage helpers (count attempts, load chain, load frontier) |
| `libs/remediation/operators/remediate.py` | auto_remediate operator |
| `libs/remediation/operators/signal.py` | signal_classify operator |
| `libs/remediation/operators/recommend.py` | recommend operator |
| `libs/remediation/strategies.py` | Strategy selection per failure_class, tier escalation, patch generation |
| `libs/remediation/signal_classification.py` | Pure-function signal algorithm (testable in isolation) |
| `libs/remediation/frontier.py` | Frontier upsert logic |
| `libs/remediation/recommendations.py` | Deterministic recommendation rules (signal × frontier × history → type) |
| `libs/storage/models/remediation.py` | RemediationAction, DirectionalSignal, MetricFrontier, RunRecommendation models |
| `libs/schemas/remediation.py` | Pydantic read schemas for all 4 new entities |
| `libs/storage/migrations/versions/20260414_000001_phase4_remediation_signal.py` | Migration |
| `apps/api/routers/remediation.py` | API routes |
| `apps/web/src/api/remediation.ts` | Frontend API client for remediation/signal/frontier/recommendation |
| `tests/unit/test_signal_classification.py` | Signal algorithm tests |
| `tests/unit/test_remediation_strategies.py` | Strategy selection + escalation tests |
| `tests/unit/test_frontier.py` | Frontier upsert tests |
| `tests/unit/test_recommendations.py` | Recommendation rule tests |

---

## 7. API Endpoints (apps/api/routers/remediation.py)

| Method | Path | Description |
|---|---|---|
| GET | /api/v1/runs/{run_id}/remediation | Remediation actions for a run |
| GET | /api/v1/runs/{run_id}/signal | Directional signal for a run |
| GET | /api/v1/runs/{run_id}/recommendation | Recommendation for a run |
| GET | /api/v1/runs/{run_id}/lineage | Full retry chain (parent_run_id walk + remediation actions) |
| GET | /api/v1/specs/{spec_id}/signal-history | All signals for a spec |
| GET | /api/v1/hypotheses/{card_id}/frontier | MetricFrontier for a hypothesis line |
| GET | /api/v1/charters/{charter_id}/frontiers | All frontiers for a charter |

---

## 8. Web UI Changes

### apps/web/src/routes/experiment/index.tsx (experiment list page)

Add a **Frontier Summary** section below the existing Runs section:
- Table showing each hypothesis card's frontier: best metric, best run link, runs since improvement, signal trend icon (arrow up/down/flat/oscillating/star for breakthrough)
- Color-coded: green for advancing, yellow for stalled, red for regressing, orange for noisy, gold for breakthrough

### apps/web/src/routes/experiment/$runId.tsx (run detail page)

1. **Remediation History** section (below Failure Postmortem, if any remediation_actions exist):
   - List of remediation attempts: attempt #, strategy, tier (focused/broad), outcome, action_detail summary
   - Link to retry run if retry_run_id exists

2. **Directional Signal** section (below Verification Report, for passed/inconclusive runs):
   - Signal badge (advancing/stalled/regressing/noisy/breakthrough) with color
   - Primary metric value + delta from previous
   - Constraint metrics status (within bounds / out of bounds)
   - Mini sparkline or history list showing metric trend

3. **Recommendation** section (below Directional Signal or Postmortem):
   - Recommendation type badge (mechanical_recovery / parameter_variation / hypothesis_pivot / continue_current / halt)
   - Action text
   - Reasoning text
   - Collapsible inputs_summary showing the data that fed the recommendation

4. **Run Lineage** (in run header, if parent_run_id exists):
   - "Retry of Run #N" link to parent run
   - "Retried as Run #M" link to child run (if any)

### apps/web/src/api/remediation.ts (new file)

TypeScript types and fetch functions for: RemediationAction, DirectionalSignal, MetricFrontier, RunRecommendation, RunLineage. Plus React Query hooks.

---

## 9. Implementation Order

### Step 1: Foundation (parallel)
- [ ] A. Migration file (4 new tables + 3 column additions to existing tables)
- [ ] B. SQLAlchemy models (`libs/storage/models/remediation.py`)
- [ ] C. Pydantic schemas (`libs/schemas/remediation.py`)
- [ ] D. Add parent_run_id to RunRecord, primary_metric_index to ExperimentSpec, signal/recommendation FKs to VerificationReport
- [ ] E. Add RemediationEvents + SignalEvents to event_types.py

### Step 2: Signal classification + frontier (lower risk, build & test first)
- [ ] F. Pure signal classification function (`libs/remediation/signal_classification.py`) + tests
- [ ] G. Frontier upsert logic (`libs/remediation/frontier.py`) + tests
- [ ] H. signal_classify operator
- [ ] I. Register signal_classify, wire verification_check success path to it

### Step 3: Recommendation logic
- [ ] J. Deterministic recommendation rules (`libs/remediation/recommendations.py`) + tests
- [ ] K. recommend operator
- [ ] L. Wire signal_classify → recommend → reporting
- [ ] L2. Modify verification_postmortem to enqueue `recommend` instead of transitioning to reporting

### Step 4: Failure classification refinement
- [ ] M. Add invalid_artifact to _classify_failure()
- [ ] N. Add artifact-presence check in execution_capture

### Step 5: Remediation layer
- [ ] O. Strategy selection + tier escalation module (`libs/remediation/strategies.py`) + tests
- [ ] P. Lineage helpers (`libs/remediation/operators/_common.py`)
- [ ] Q. auto_remediate operator
- [ ] R. Modify execution_setup to merge code_plan/build_recipe from remediation_overrides in payload
- [ ] S. Wire verification_check failure path to auto_remediate
- [ ] T. Register all 3 operators in executor

### Step 6: API and CLI
- [ ] U. Service functions in experiment_service.py (query remediation_actions, signals, frontiers, recommendations)
- [ ] V. API router (`apps/api/routers/remediation.py`) + mount in main.py
- [ ] W. CLI commands under `synthetos experiment` (remediation, signal, frontier, recommendation subcommands)

### Step 7: Web UI
- [ ] X. Frontend API client (`apps/web/src/api/remediation.ts`)
- [ ] Y. Run detail page: remediation history, signal, recommendation, lineage sections
- [ ] Z. Experiment index page: frontier summary section

---

## 10. Verification Plan

1. **Unit tests** (pure functions, no DB):
   - Signal classification: all 5 signals + edge cases (1 data point, 2 data points, empty history)
   - Recommendation rules: all cells in the decision matrix
   - Strategy selection: all failure classes + tier escalation logic
   - Frontier upsert: create, update-improved, update-not-improved

2. **Operator tests** (mock DB):
   - auto_remediate: creates correct RunRecord + RemediationAction for each failure class
   - auto_remediate: escalates from focused to broad on same-class re-failure
   - auto_remediate: exhausts after max_attempts and routes to postmortem
   - signal_classify: produces correct signal and updates frontier
   - recommend: produces correct recommendation type given various inputs

3. **Quality gates**: `uv run ruff check .` && `uv run pyright` && `uv run pytest` && `cd apps/web && npm run build`

4. **Integration smoke test** (requires Postgres):
   - Create spec → start run → simulate dependency failure → verify remediation creates retry
   - Simulate successful run → verify signal classification + frontier creation
   - Simulate 5 stalled runs → verify recommendation = hypothesis_pivot
   - Verify UI renders all new sections

5. **Regression**: existing Phase 3 tests continue to pass (the verification_check routing change is the riskiest modification)
