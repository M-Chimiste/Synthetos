# Phase 5 Implementation Plan: Autonomous Loop and Configurable Gating

## Context

Phase 4 (remediation, directional signal, frontier tracking) is complete. Every run now ends with a `RunRecommendation` that classifies the next step as `continue_current`, `parameter_variation`, `hypothesis_pivot`, `mechanical_recovery`, or `halt`. Phase 5 closes the loop: instead of stopping after one recommendation, the system acts on it automatically, subject to budget and policy constraints.

---

## Architecture Decision: New `loop_deciding` State

Add a `loop_deciding` cycle status between `verifying` and `reporting`. In autonomous mode, `recommend` transitions to `loop_deciding` (instead of `reporting`) and enqueues a `loop_decide` operator. This operator consumes the recommendation, checks budgets and gates, updates hypothesis lifecycle, and either loops back to `running` or proceeds to `reporting`.

Rationale:
- Makes the decision point visible in the state machine (vs hiding it inside `verifying`)
- Only one conditional changes in Phase 4 code (the target status in `recommend`)
- Supervised mode is completely unchanged (`recommend -> reporting` as before)
- Clean rollback: remove the state and the one conditional to revert

State machine additions:
```
verifying -> [reporting, running, loop_deciding]    # add loop_deciding
loop_deciding -> [running, reporting]               # new
```

---

## Implementation Steps

### Step 1: State Machine and Event Types

**Files to modify:**
- [types.py](libs/core/types.py) -- add `loop_deciding = "loop_deciding"` to `CycleStatus`
- [state_machine.py](libs/core/state_machine.py) -- add `loop_deciding` to transitions from `verifying`; add `loop_deciding: [running, reporting]`
- [event_types.py](libs/core/event_types.py) -- add `AutonomyEvents` enum

New event types:
```
autonomy.loop_started
autonomy.loop_decision_made
autonomy.budget_updated
autonomy.budget_exceeded
autonomy.gate_triggered
autonomy.gate_resumed
autonomy.hypothesis_status_changed
autonomy.hypothesis_selected
autonomy.repetition_detected
autonomy.context_summarized
autonomy.loop_completed
autonomy.loop_stopped_manual
```

Tests: verify new transitions are valid, old transitions still work.

---

### Step 2: Autonomy Policy and Budget Models (Data Layer)

**New files:**
- `libs/autonomy/__init__.py`
- `libs/autonomy/policy.py` -- Pydantic models for autonomy config

```python
class CheckpointGateConfig(BaseModel):
    after_every_run: bool = False
    after_every_n_runs: int | None = None
    before_hardware_escalation: bool = False
    before_result_promotion: bool = False
    before_network_execution: bool = False

class AutonomyPolicy(BaseModel):
    mode: Literal["supervised", "autonomous"] = "supervised"
    max_total_runs: int | None = None
    max_wall_clock_hours: float | None = None
    max_runs_per_hypothesis: int | None = None
    max_wall_time_per_run_s: int | None = None    # per-run execution budget
    checkpoint_gates: CheckpointGateConfig = CheckpointGateConfig()
    cost_budget_note: str = "Phase 5 cost budgeting is deferred."
```

Stored in `ResearchCycle.config["autonomy"]`. Loaded via `AutonomyPolicy.model_validate(cycle.config.get("autonomy", {}))`.

**Budget accounting decision:** The v1 budget tracks **run count** and **wall-clock time** as primary limits. These are authoritative: `total_runs` is incremented per completed run, `wall_clock_elapsed_s` is computed from `AutonomyBudget.started_at` to `utcnow()`. We explicitly defer LLM cost and compute cost budgets to a later iteration because:
- `RunRecord.resource_usage` has `wall_time_s` and `peak_memory_mb` but no dollar cost
- `ModelCallRecord.cost_estimate` tracks LLM cost but is nullable and not yet reliably populated
- Mixing two incomplete cost sources into a single `max_cost_usd` budget would produce unreliable enforcement

When cost budgets are added later: add `max_cost_usd` to `AutonomyPolicy`, add `total_llm_cost_usd` column to `AutonomyBudget`, and sum `ModelCallRecord.cost_estimate` per cycle. The `AutonomyBudget` table and `AutonomyPolicy` model are designed to accommodate this without breaking changes.

- `libs/storage/models/autonomy.py` -- two new SQLAlchemy models:

**`AutonomyBudget`** (one per cycle):
```
id: UUID (PK)
cycle_id: UUID (FK research_cycles, unique)
total_runs: int (default 0)
wall_clock_elapsed_s: float (default 0.0)       # snapshot updated each iteration
runs_per_hypothesis: JSONB (default {})           # {hypothesis_card_id_str: count}
started_at: datetime
last_run_completed_at: datetime | null
created_at: datetime
updated_at: datetime
```

**`LoopDecision`** (audit log, one per loop iteration):
```
id: UUID (PK)
cycle_id: UUID (FK research_cycles)
charter_id: UUID (FK research_charters)
run_record_id: UUID (FK run_records)
recommendation_id: UUID (FK run_recommendations)
iteration_number: int                             # 1-indexed loop counter
decision: String(50)                              # see decision vocabulary below
gate_triggered: String(100) | null
budget_snapshot: JSONB                            # snapshot of budget at decision time
hypothesis_card_id: UUID | null (FK)              # hypothesis that just ran
next_hypothesis_card_id: UUID | null (FK)         # hypothesis selected for next run (if any)
next_action: String(50) | null                    # "rerun_spec", "recompile_spec", "compile_new_hypothesis"
context_summary_path: String(1024) | null         # path to context summary artifact (if generated)
reasoning: Text
created_at: datetime
```

Decision vocabulary for `LoopDecision.decision`:
- `continue_current` -- rerun same spec
- `vary_parameters` -- recompile spec with variation hints
- `pivot_hypothesis` -- switch to a different existing hypothesis card
- `stop_budget` -- budget limit reached
- `stop_gate` -- checkpoint gate triggered, job paused
- `stop_halt` -- recommendation was `halt`, no viable path
- `stop_exhausted` -- no remaining viable hypotheses (regeneration deferred to future iteration)
- `stop_manual` -- user/orchestrator requested stop

Note: `regenerate_hypotheses` (re-entering the ideation pipeline mid-loop) is explicitly deferred from v1. See Step 5C for rationale. When all hypotheses are exhausted, the loop stops with `stop_exhausted` and the completion report recommends manual regeneration.

- `libs/storage/models/__init__.py` -- register new models
- Alembic migration creating both tables

**`libs/autonomy/budget.py`** -- pure functions:
- `load_or_create_budget(session, cycle_id) -> AutonomyBudget`
- `increment_budget(session, budget, hypothesis_card_id)` -- bumps `total_runs`, updates `runs_per_hypothesis`, snapshots `wall_clock_elapsed_s`
- `check_budget(policy, budget) -> BudgetCheckResult` -- returns `(exceeded: bool, limit_name: str | None, detail: str)`. Checks `max_total_runs`, `max_wall_clock_hours` (from `started_at` to now), `max_runs_per_hypothesis` (per card)

Tests: policy parsing, budget arithmetic, each limit type, per-hypothesis tracking.

---

### Step 3: Hypothesis Lifecycle

**New file:** `libs/autonomy/hypothesis_lifecycle.py`

**Compatibility with existing status model:** The current `HypothesisCard.status` field uses values `candidate`, `selected`, `compiled`, `rejected`, `deferred`. These are set by the Phase 3 ideation and compile operators. Phase 5 lifecycle statuses are a **superset** that extends the status vocabulary for cards that have entered the execution loop. The mapping:

| Phase 3 status | Meaning | Can transition to Phase 5? |
|---|---|---|
| `candidate` | Generated, not yet selected | No -- stays Phase 3 until selected by `loop_decide` |
| `selected` | Chosen for protocol compilation | Yes, but only after first run completes |
| `compiled` | Has a validated ExperimentSpec | Yes -- `loop_decide` transitions to `active` on first loop iteration |
| `rejected` | Rejected by critique/rank | No |
| `deferred` | User deferred | Yes -- `loop_decide` can reactivate if pivoting |

Phase 5 statuses (all require at least one run):
- `active` -- has at least one run, currently being explored
- `promising` -- signal is `advancing` or `breakthrough`
- `stalled` -- `runs_since_improvement >= STALL_THRESHOLD` (5)
- `deprioritized` -- `loop_decide` pivoted away (recommendation was `hypothesis_pivot`)
- `validated` -- frontier meets/exceeds target from spec's `stop_conditions`

**Where existing queries are affected:**
- [compile.py:161](libs/protocols/operators/compile.py#L161) queries `status.in_(["candidate", "selected"])`. This is fine -- Phase 5 statuses only apply to cards that have already been compiled, so they would never appear in a compile query context.
- The experiment API's `list_hypothesis_cards` endpoint accepts optional `status` filter. No schema change needed since it's a string field.
- **`HypothesisCardUpdate` schema change required:** The current schema at [experiment.py:90](libs/schemas/experiment.py#L90) constrains status via regex: `pattern="^(candidate|selected|rejected|deferred)$"`. This must be updated to also accept Phase 5 values. New pattern: `"^(candidate|selected|compiled|rejected|deferred|active|promising|stalled|deprioritized|validated)$"`. However, Phase 5 lifecycle transitions are managed by `loop_decide`, not by direct user PATCH. To prevent users from manually setting Phase 5 statuses outside the loop, the API handler should only allow users to set `candidate|selected|rejected|deferred` -- the Phase 5 statuses are system-managed. The cleanest approach: keep the existing PATCH validation as-is (only allowing the 4 user-facing statuses), and have `loop_decide` update the card status directly via the ORM without going through the API schema. The API read schemas (`HypothesisCardRead`) already return whatever string is in the `status` column, so no read-side change is needed.

**Key function:**
```python
def update_hypothesis_status(
    session: Session,
    card_id: UUID,
    signal: str | None,       # from DirectionalSignal
    frontier: MetricFrontier | None,
    recommendation_type: str, # from RunRecommendation
    spec: ExperimentSpec | None,
) -> str:
    """Returns the new status. Only updates if the transition is valid."""
```

Transition rules:
- `compiled -> active`: first loop iteration for this card
- `active -> promising`: signal is `advancing` or `breakthrough`
- `active -> stalled`: `frontier.runs_since_improvement >= 5`
- `active -> deprioritized`: recommendation is `hypothesis_pivot`
- `promising -> stalled`: `frontier.runs_since_improvement >= 5`
- `promising -> validated`: `frontier.best_metric_value` meets spec `stop_conditions[0].threshold` (if defined)
- `stalled -> deprioritized`: `loop_decide` pivots away
- `deferred -> active`: `loop_decide` selects this card during a pivot (reactivation)

Tests: each transition rule, idempotent no-ops for invalid transitions.

---

### Step 4: Checkpoint Gate Pause/Resume Contract

**New file:** `libs/autonomy/gates.py`

**How gate pausing works against the current worker model:**

The worker at [main.py:404-425](apps/worker/main.py#L404) checks `if current_job.status == JobStatus.paused` after the operator returns. If so, it calls `pause_job()` (stores the result snapshot) and emits `job_paused_at_checkpoint`. The key: **something external must have set the job's status to `paused` while the operator was running.** The existing run control mechanism (`control_run` in [experiment_service.py:487](libs/core/services/experiment_service.py#L487)) does this by directly updating the Job row to `paused` while the container is running.

For `loop_decide`, the operator itself decides whether a gate fires. Since the operator is synchronous and short-lived (no long-running container), we use a different mechanism:

**The `loop_decide` operator pauses its own job from within the operator function.** When a gate triggers:

1. `loop_decide` opens a DB session, sets the Job row status to `JobStatus.paused` directly:
   ```python
   db.execute(update(Job).where(Job.id == op_input.job_id).values(status=JobStatus.paused))
   db.flush()
   ```
2. Persists the `LoopDecision` with `decision="stop_gate"`, `gate_triggered=gate_name`
3. Emits `autonomy.gate_triggered` event
4. Returns a successful `OperatorResult` (no `state_patch` -- cycle stays in `loop_deciding`)
5. The worker sees `current_job.status == JobStatus.paused`, calls `pause_job()` with the result snapshot, and moves on

**Resume contract:**
1. The `POST /cycles/{id}/autonomy/resume` API endpoint:
   a. Finds the paused `loop_decide` job: `SELECT * FROM jobs WHERE cycle_id = :cycle_id AND job_type = 'loop_decide' AND status = 'paused' ORDER BY created_at DESC LIMIT 1`
   b. Calls `resume_job(session, job_id)` from [job_service.py:156](libs/core/services/job_service.py#L156), which sets status back to `pending` and clears `claimed_by`/`claimed_at`/`heartbeat_at`
   c. Emits `autonomy.gate_resumed` event
   d. The worker picks up the re-pending job on its next poll cycle
2. When the `loop_decide` operator runs again after resume, it detects that a `LoopDecision` already exists for this `run_record_id` with `decision="stop_gate"`. It treats this as a "gate approved" signal and proceeds with the original recommendation (continue/vary/pivot). The gate context is recovered from the existing `LoopDecision.budget_snapshot` and the `RunRecommendation` referenced in the payload.

**Gate evaluation function:**
```python
@dataclass(frozen=True)
class GateContext:
    runs_since_last_gate: int          # count of runs since last gate approval or loop start
    wall_clock_elapsed_s: float
    next_hardware_profile: dict | None # if the next spec requests different hardware
    is_result_promotion: bool          # if the run meets stop_conditions (validated)
    has_network_access: bool           # if the next spec requires network

@dataclass(frozen=True)
class GateResult:
    should_pause: bool
    gate_name: str | None
    reason: str

def evaluate_gates(policy: AutonomyPolicy, budget: AutonomyBudget, context: GateContext) -> GateResult:
```

Gate checks (all off by default):
- `after_every_run`: fires every iteration
- `after_every_n_runs`: fires when `runs_since_last_gate >= n`
- `before_hardware_escalation`: fires when `next_hardware_profile` differs from current (e.g., GPU count increase)
- `before_result_promotion`: fires when a hypothesis reaches `validated`
- `before_network_execution`: fires when the next spec's `env_vars` or `code_plan` indicates network access

Tests: each gate type, combinations, disabled-by-default, resume-after-gate flow.

---

### Step 5: Variation, Pivot, and Regeneration Contracts

**This section defines how each `loop_decide` action maps to a concrete operator chain.**

#### 5A. `continue_current` -> Rerun Same Spec

When the recommendation is `continue_current` (breakthrough or advancing), `loop_decide`:
1. Creates a new `RunRecord` linked to the same `ExperimentSpec`
2. Sets `run_number` = max existing run_number for this spec + 1
3. Enqueues `execution_setup` with `{"run_record_id": str(new_run.id)}`
4. Returns `state_patch={"cycle_status": "running"}`

This follows the exact same path as the existing manual `retry` in [experiment_service.py](libs/core/services/experiment_service.py) -- create RunRecord, enqueue setup.

#### 5B. `parameter_variation` -> Recompile with Variation Context

When the recommendation is `parameter_variation`, `loop_decide` needs a new `ExperimentSpec` with varied parameters. The current [compile.py](libs/protocols/operators/compile.py) takes `hypothesis_session_id` and optionally `hypothesis_card_ids`, then calls the LLM to produce fresh specs.

**Extension to `protocol_compile_operator`:** Add an optional `variation_context` key to the payload:

```python
# In the protocol_compile_operator payload:
{
    "hypothesis_session_id": "...",
    "hypothesis_card_ids": ["<the-same-card-id>"],
    "variation_context": {
        "prior_spec_id": "<spec-that-was-run>",
        "prior_metrics": {"accuracy": 0.82, "loss": 0.45},
        "signal": "stalled",
        "frontier_best": 0.85,
        "recommendation_action": "Try different hyperparameters...",
        "variation_number": 3     # how many variations have been tried
    }
}
```

The compile operator appends this context to the LLM prompt:

```
Previous attempt results:
- Spec: {prior_spec.title}
- Metrics achieved: {prior_metrics}
- Signal: {signal}
- Best frontier value: {frontier_best}
- Recommendation: {recommendation_action}
- This is variation #{variation_number}.

Compile a NEW experiment spec that addresses the stall/regression by varying 
hyperparameters, architecture choices, or training strategy. Do NOT repeat 
the same configuration.
```

The compile operator produces a new `ExperimentSpec` row linked to the same `HypothesisCard`. `loop_decide` then creates a `RunRecord` for the new spec and enqueues `execution_setup`.

**State transition path:** `loop_deciding -> protocol_ready -> running`. But this introduces a problem: the state machine doesn't allow `loop_deciding -> protocol_ready`. 

**Resolution:** Instead of transitioning through intermediate states, `loop_decide` directly enqueues `protocol_compile` and transitions to `running`. The protocol compile operator is modified to accept a `skip_state_transition: true` payload flag that suppresses its `state_patch` (currently it sets `protocol_ready`). The outer loop's transition to `running` covers the state semantics. This keeps the state machine simple.

Actually, a cleaner approach: `loop_deciding -> running` is already an allowed transition. `loop_decide` transitions to `running` and enqueues `protocol_compile` (which skips its own state_patch when `from_loop=true` in payload). The compile operator produces the spec, then enqueues `execution_setup` for it. The cycle is already in `running` throughout.

#### 5C. `hypothesis_pivot` -> Switch to Different Hypothesis Card

When the recommendation is `hypothesis_pivot`, `loop_decide`:
1. Sets current hypothesis card status to `deprioritized`
2. Queries for the next best viable card: `SELECT * FROM hypothesis_cards WHERE cycle_id = :cycle_id AND status IN ('candidate', 'compiled', 'deferred') ORDER BY rank ASC NULLS LAST LIMIT 1`
3. If a card is found:
   - If status is `compiled` (already has a validated spec): create a `RunRecord` for that spec, enqueue `execution_setup`, transition to `running`
   - If status is `candidate` or `deferred`: enqueue `protocol_compile` for that card (with `from_loop=true`), transition to `running`
4. If no viable card is found: decision = `stop_exhausted`, loop terminates. The completion report recommends "consider generating new hypotheses."

**Why `regenerate_hypotheses` is deferred from v1:** Re-entering the ideation pipeline (hypothesis_generate -> critique -> rank) mid-loop would require state-machine transitions through `evidence_ready -> portfolio_ready -> protocol_ready`, which conflicts with the cycle being in `running`/`loop_deciding`. The state-machine complexity is not justified for v1. Users can manually trigger a new hypothesis generation session and restart the autonomous loop. A future iteration can add a `regenerate` path if the v1 `stop_exhausted` exit proves too limiting in practice.

#### 5E. Protocol Compile Modification

**File to modify:** [compile.py](libs/protocols/operators/compile.py)

Changes:
1. Accept optional `variation_context` in payload (dict or None)
2. If present, append variation context to the LLM prompt
3. Accept optional `from_loop: true` in payload. When set, suppress the `state_patch` (don't transition to `protocol_ready`) and instead enqueue `execution_setup` directly for the newly created spec, creating a RunRecord inline
4. Accept optional `hypothesis_card_ids` as already supported (line 123)

This is additive -- the existing compile path is unchanged when these payload keys are absent.

Tests: compile with variation_context produces different prompt, compile with `from_loop=true` creates RunRecord and enqueues execution_setup.

---

### Step 6: Repetition Detection

**New file:** `libs/autonomy/repetition.py`

Functions:
- `fingerprint_spec(spec: ExperimentSpec) -> str` -- SHA-256 of canonicalized `(code_plan, controls, metrics, baseline)`. Canonicalization: sort keys, strip whitespace, normalize numeric precision to 6 decimal places
- `detect_repetition(session, cycle_id, current_spec_id) -> RepetitionResult`
  - Loads all specs in the cycle, computes fingerprints, checks for exact match
  - Near-duplicate: if only `controls` differ and only by numeric values within 1% relative tolerance
  - `RepetitionResult(is_duplicate: bool, is_near_duplicate: bool, prior_spec_id: UUID | None, match_type: str | None)`

When `loop_decide` gets a `continue_current` recommendation but repetition is detected:
- Exact duplicate: escalate to `vary_parameters` (force recompile with variation context)
- Near-duplicate (3+ near-duplicates in a row): escalate to `pivot_hypothesis`

Tests: fingerprint stability across serialization roundtrips, duplicate detection, near-duplicate detection, escalation thresholds.

---

### Step 7: Context Summarization

**New file:** `libs/autonomy/context_summary.py`

**What gets summarized:** When the loop has completed N iterations (configurable, default 5), `loop_decide` generates a context summary before making its decision. The summary condenses the loop history so far into a compact artifact that can be fed into the `protocol_compile` variation prompt, preventing the LLM from losing track of what has been tried.

**When summaries are generated:** At the start of each `loop_decide` invocation when `budget.total_runs >= summary_interval` and the run count has crossed a summary boundary (runs 5, 10, 15, ...).

**What the summary contains:**
```python
@dataclass
class LoopContextSummary:
    cycle_id: UUID
    iteration_number: int
    hypotheses_tried: list[dict]    # [{card_id, title, status, runs, best_metric, signal}]
    frontier_progression: list[dict] # [{iteration, best_value, hypothesis}]
    failure_patterns: dict           # {failure_class: count}
    remediation_summary: dict        # {total_attempts: N, resolved: N, exhausted: N}
    repeated_approaches: list[str]   # descriptions of near-duplicate specs detected
    key_findings: str                # LLM-generated 2-3 sentence summary of progress
```

**How it's generated:**
1. Query all `LoopDecision` rows for the cycle
2. Query all `MetricFrontier` rows for the charter
3. Query all `RemediationAction` rows for the cycle
4. Query all `RunRecommendation` rows for the cycle
5. Assemble the structured summary (deterministic)
6. Call LLM (ModelRole.summarization) for the `key_findings` field -- a 2-3 sentence synthesis

**Where it's stored:** Written as JSON to `{data_root}/reports/cycles/{cycle_id}/summaries/summary_{iteration}.json`. The path is stored in `LoopDecision.context_summary_path`.

**How `loop_decide` consumes it:** When enqueuing a `protocol_compile` with `variation_context`, the most recent summary is loaded and its `key_findings` + `repeated_approaches` + `frontier_progression` are included in the variation context. This gives the compile LLM awareness of the full loop history without flooding it with raw run data.

Tests: summary generation with fixture data, interval triggering logic, integration with variation context.

---

### Step 8: Modify `recommend` Operator

**File:** [recommend.py](libs/remediation/operators/recommend.py)

Minimal change (~15 lines). After persisting the recommendation, emitting the event, and before the final `return`, replace the hardcoded `reporting` target:

```python
from libs.storage.models.research import ResearchCycle

cycle = db.get(ResearchCycle, run.cycle_id)
autonomy_cfg = (cycle.config or {}).get("autonomy", {})
is_autonomous = autonomy_cfg.get("mode") == "autonomous"

if is_autonomous:
    target_status = CycleStatus.loop_deciding.value
    # Enqueue loop_decide job using the same pattern as enqueue_next_phase4
    from libs.core.services.job_service import create_job
    create_job(
        db,
        cycle_id=run.cycle_id,
        job_type="loop_decide",
        payload={
            "run_record_id": str(run.id),
            "recommendation_id": str(rec_row.id),
        },
        priority=5,
    )
else:
    target_status = CycleStatus.reporting.value
```

Then use `target_status` in the returned `state_patch`.

Tests: recommend with supervised cycle -> `reporting`; recommend with autonomous cycle -> `loop_deciding` + `loop_decide` job enqueued.

---

### Step 9: `loop_decide` Operator (Core)

**New files:**
- `libs/autonomy/operators/__init__.py` -- register function
- `libs/autonomy/operators/loop_decide.py`

Job type: `"loop_decide"`. This is a thin dispatcher calling the subsystems from steps 2-7:

```
1. Load RunRecommendation from payload.recommendation_id
2. Load AutonomyPolicy from ResearchCycle.config
3. Load/create AutonomyBudget, increment it
4. Check if this is a gate-resume (LoopDecision with decision="stop_gate" exists for this run_record_id)
   -> If yes, skip gate evaluation, proceed with the original recommendation
5. Check budget limits -> if exceeded, decision = "stop_budget", goto STOP
6. Evaluate checkpoint gates -> if triggered:
   a. Set Job status to paused (direct DB update)
   b. Persist LoopDecision(decision="stop_gate", gate_triggered=gate_name)
   c. Emit autonomy.gate_triggered event
   d. Return OperatorResult(success=True) with no state_patch
7. Optionally generate context summary (if iteration crosses summary boundary)
8. Update hypothesis lifecycle status
9. Based on recommendation_type:
   a. continue_current:
      - Check repetition against existing specs (Step 6)
      - If exact duplicate -> escalate to vary_parameters (goto 9b)
      - If 3+ near-duplicates in a row -> escalate to pivot_hypothesis (goto 9c)
      - Otherwise: create new RunRecord for same spec, enqueue execution_setup
      - decision = "continue_current", next_action = "rerun_spec"
   b. parameter_variation:
      - Enqueue protocol_compile with variation_context (prior metrics, signal,
        frontier best, recommendation action, variation number) + from_loop=true
        (see Step 5B for full variation_context structure)
      - decision = "vary_parameters", next_action = "recompile_spec"
   c. hypothesis_pivot:
      - Deprioritize current card (set status to "deprioritized")
      - Query next viable card: candidate|compiled|deferred, ordered by rank ASC NULLS LAST
      - If card found with status "compiled" (already has validated spec):
        create RunRecord, enqueue execution_setup
      - If card found with status "candidate" or "deferred":
        enqueue protocol_compile with from_loop=true for that card
      - If no viable card found: decision = "stop_exhausted", goto STOP
        (regeneration deferred from v1 -- completion report recommends manual regeneration)
      - decision = "pivot_hypothesis", next_action = "compile_new_hypothesis"
   d. halt:
      - decision = "stop_halt", goto STOP
10. Persist LoopDecision row
11. Emit autonomy.loop_decision_made event
12. Return OperatorResult(state_patch={"cycle_status": "running"})

STOP:
  - Persist LoopDecision row
  - Enqueue loop_report job
  - Emit autonomy.loop_completed event
  - Return OperatorResult(state_patch={"cycle_status": "reporting"})
```

**Register in** [executor.py](apps/worker/executor.py) following the existing pattern.

Tests: each decision path with mocked DB, gate pause flow, gate resume flow, repetition escalation, budget exhaustion. Follow `tests/unit/test_recommendations.py` pattern.

---

### Step 10: Completion Reporting

**New files:**
- `libs/autonomy/completion_report.py` -- render markdown + JSON report
- `libs/autonomy/operators/loop_report.py` -- operator that generates the report

Job type: `"loop_report"`. Enqueued when `loop_decide` stops the loop.

Report sections:
1. **Executive summary** -- LLM-generated 3-5 sentence synthesis (ModelRole.report_writing)
2. **Hypotheses explored** -- table: card title, final status, runs, best metric, signal trajectory
3. **Frontier progression** -- per-hypothesis metric timeline
4. **Loop decisions** -- chronological table: iteration, decision, hypothesis, reasoning
5. **Remediation summary** -- failure classes, attempt counts, resolution rates
6. **Budget consumption** -- total runs, wall-clock time, per-hypothesis breakdown
7. **Recommendations** -- final `RunRecommendation` reasoning plus whether regeneration is suggested

Output: markdown report + JSON bundle written to `{data_root}/reports/cycles/{cycle_id}/completion/`. Follows the pattern of [reports.py](libs/discovery/reports.py): `build_report_paths()`, `render_markdown()`, `render_json()`, `write_report_bundle()`.

Then transitions `reporting -> closed`.

Tests: report rendering with fixture data.

---

### Step 11: API Endpoints and Schemas

**New files:**
- `libs/schemas/autonomy.py` -- `AutonomyPolicyRead`, `AutonomyPolicyUpdate`, `AutonomyBudgetRead`, `LoopDecisionRead`
- `apps/api/routers/autonomy.py`

| Method | Path | Description | Scope |
|--------|------|-------------|-------|
| `GET` | `/cycles/{id}/autonomy/policy` | Read current policy | `cycles.read` |
| `PUT` | `/cycles/{id}/autonomy/policy` | Update policy (extend budget, toggle gates) | `cycles.write` |
| `GET` | `/cycles/{id}/autonomy/budget` | Read budget consumption | `cycles.read` |
| `GET` | `/cycles/{id}/autonomy/decisions` | List loop decisions (paginated) | `cycles.read` |
| `GET` | `/cycles/{id}/autonomy/decisions/{decision_id}` | Single decision detail | `cycles.read` |
| `POST` | `/cycles/{id}/autonomy/resume` | Resume gate-paused loop | `cycles.write` |
| `POST` | `/cycles/{id}/autonomy/stop` | Manually stop autonomous loop | `cycles.write` |

**Resume endpoint detail:**
1. Query `SELECT * FROM jobs WHERE cycle_id = :id AND job_type = 'loop_decide' AND status = 'paused' ORDER BY created_at DESC LIMIT 1`
2. If not found, return 404
3. Call `resume_job(session, job.id)` -- sets status to pending
4. Emit `autonomy.gate_resumed` event
5. Return 200 with the resumed job ID

**Stop endpoint detail:**
1. Cancel all pending/claimed/running jobs for the cycle
2. If cycle is in `loop_deciding`, transition to `reporting` and enqueue `loop_report`
3. Emit `autonomy.loop_stopped_manual` event
4. Persist a `LoopDecision` with `decision="stop_manual"`

**Modify:** `apps/api/main.py` -- mount autonomy router.

Tests: API endpoint tests following existing patterns.

---

### Step 12: CLI Commands

**New file:** `apps/cli/commands/autonomy.py`

- `synthetos autonomy policy --cycle-id <uuid>` -- show current policy
- `synthetos autonomy budget --cycle-id <uuid>` -- show budget consumption
- `synthetos autonomy decisions --cycle-id <uuid>` -- list loop decisions
- `synthetos autonomy resume --cycle-id <uuid>` -- resume gate-paused loop
- `synthetos autonomy stop --cycle-id <uuid>` -- stop autonomous loop

---

### Step 13: Frontend

- `apps/web/src/api/autonomy.ts` -- TypeScript API client
- Cycle detail page: autonomy mode badge, budget consumption progress bars (runs used / max, wall-clock), gate status indicator
- Loop decisions timeline view on cycle detail page
- Hypothesis lifecycle status badges on hypothesis cards
- Completion report rendering (reuse existing report viewer pattern)

---

## File Summary

### New files (~17)
| File | Purpose |
|------|---------|
| `libs/autonomy/__init__.py` | Package init |
| `libs/autonomy/policy.py` | AutonomyPolicy + CheckpointGateConfig Pydantic models |
| `libs/autonomy/budget.py` | Budget load/increment/check |
| `libs/autonomy/gates.py` | Checkpoint gate evaluation with GateContext/GateResult |
| `libs/autonomy/repetition.py` | Spec fingerprinting, duplicate/near-duplicate detection |
| `libs/autonomy/hypothesis_lifecycle.py` | Hypothesis status transitions with Phase 3 compatibility |
| `libs/autonomy/context_summary.py` | Loop context summarization at interval boundaries |
| `libs/autonomy/completion_report.py` | Completion report renderer (markdown + JSON) |
| `libs/autonomy/operators/__init__.py` | Operator registration |
| `libs/autonomy/operators/loop_decide.py` | Core loop decision operator |
| `libs/autonomy/operators/loop_report.py` | Completion report operator |
| `libs/storage/models/autonomy.py` | AutonomyBudget + LoopDecision ORM models |
| `libs/schemas/autonomy.py` | API read/write schemas |
| `apps/api/routers/autonomy.py` | API router (7 endpoints) |
| `apps/cli/commands/autonomy.py` | CLI subcommands |
| Alembic migration | Create autonomy_budgets and loop_decisions tables |

### Modified files (~8)
| File | Change |
|------|--------|
| `libs/core/types.py` | Add `loop_deciding` to CycleStatus |
| `libs/core/state_machine.py` | Add transitions for `loop_deciding` |
| `libs/core/event_types.py` | Add `AutonomyEvents` (12 event types) |
| `libs/remediation/operators/recommend.py` | Conditional target status + enqueue loop_decide (~15 lines) |
| `libs/protocols/operators/compile.py` | Accept `variation_context` and `from_loop` payload keys |
| `apps/worker/executor.py` | Register autonomy operators |
| `libs/storage/models/__init__.py` | Import autonomy models |
| `apps/api/main.py` | Mount autonomy router |

---

## Implementation Order

Build in this order for incremental testability:

1. **Step 1** (state machine + events) -- no behavior change, foundation only
2. **Step 2** (policy + budget models + migration) -- data layer, no operators
3. **Step 3** (hypothesis lifecycle) -- pure logic, testable in isolation
4. **Step 4** (gates) -- pure logic, testable in isolation
5. **Step 6** (repetition detection) -- pure logic, testable in isolation
6. **Step 7** (context summarization) -- pure logic + one LLM call
7. **Step 8** (modify recommend) -- minimal Phase 4 change, enables loop entry
8. **Step 5** (modify protocol_compile) -- additive payload handling
9. **Step 9** (loop_decide operator) -- integrates all subsystems, core of Phase 5
10. **Step 10** (completion report) -- depends on loop_decide decision vocabulary
11. **Step 11** (API) -- depends on models and operators
12. **Step 12** (CLI) -- depends on API
13. **Step 13** (frontend) -- depends on API

Steps 3-6 can be parallelized since they are independent pure-logic modules.

---

## Verification

After implementation:
1. `uv run ruff check .` passes
2. `uv run pyright` passes
3. `uv run pytest` passes (existing 141 + new ~50-60 tests)
4. `cd apps/web && npm run build` passes
5. Manual test: create cycle with `config.autonomy.mode = "supervised"`, run experiment, verify recommend -> reporting (no regression)
6. Manual test: create cycle with `config.autonomy.mode = "autonomous"`, seed hypotheses, run through loop, verify:
   - Budget increments correctly per run
   - Hypothesis lifecycle transitions (active -> promising on advancing signal)
   - Loop continues on `continue_current`, varies on `parameter_variation`
   - Loop stops on budget exhaustion
   - Completion report generated with correct sections
7. Manual test: configure `after_every_n_runs: 2` gate:
   - Verify loop pauses after 2 runs (job status = paused, cycle stays in loop_deciding)
   - Call `POST /cycles/{id}/autonomy/resume`
   - Verify job returns to pending, worker picks it up, loop continues
8. Manual test: force repetition (run same spec 3 times), verify repetition detection escalates to variation
9. Verify context summary generated at iteration 5 and included in variation prompt
