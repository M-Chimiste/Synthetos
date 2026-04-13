# Phase 3: Hypotheses, Protocols, and Execution Lab MVP

## Context

Phases 0-2 built the foundation (queue-driven operator runtime, event sourcing, LLM gateway), the discovery pipeline (literature triage, ranking, views), and the analysis pipeline (full-text ingestion, graph extraction, evidence cards). Phase 3 turns that evidence into *runnable ML experiments* — the first time the system produces scientific output rather than just organizing inputs.

The cycle state machine already defines the Phase 3 states: `evidence_ready → portfolio_ready → protocol_ready → running → verifying → reporting`. This plan implements the operators, services, storage, and execution runtime that drive transitions through those states.

---

## 1. New Dependencies

Add to `pyproject.toml`:
- `docker>=7,<8` — Docker SDK for Python (sibling container execution)

---

## 2. Alembic Migration

**File:** `libs/storage/migrations/versions/20260413_000001_phase3_hypotheses_execution.py`
**Down revision:** `20260412_000001`

Creates 7 tables (FK-order):

### `hypothesis_sessions`
Tracks one hypothesis-generation run (mirrors `DiscoverySession`/`AnalysisSession` pattern).

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| cycle_id | UUID FK research_cycles CASCADE | |
| charter_id | UUID FK research_charters CASCADE | |
| status | String(50) default "created" | created/generating/critiquing/ranking/completed/failed |
| budget | JSONB nullable | {max_hypotheses, max_critique_rounds} |
| stats | JSONB nullable | {generated_count, critiqued_count, ranked_count} |
| step_log | JSONB nullable | [{step, status, at, detail}] |
| error | Text nullable | |
| created_at, updated_at, started_at, completed_at | datetime | Standard pattern |

Indexes: `(cycle_id, created_at)`, `(status)`

### `hypothesis_cards`
One candidate hypothesis with evidence lineage.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| hypothesis_session_id | UUID FK hypothesis_sessions CASCADE | |
| charter_id | UUID FK research_charters CASCADE | |
| cycle_id | UUID FK research_cycles CASCADE | |
| title | String(500) | |
| statement | Text | The hypothesis text |
| rationale | Text | Why this hypothesis |
| mechanism | Text nullable | Proposed mechanism |
| supporting_evidence_ids | JSONB | [uuid strings] |
| critique | JSONB nullable | {strengths, weaknesses, failure_modes} |
| novelty_score | Float nullable | 0-1 |
| feasibility_score | Float nullable | 0-1 |
| impact_score | Float nullable | 0-1 |
| rank | Integer nullable | Position in portfolio |
| status | String(50) default "candidate" | candidate/selected/compiled/running/verified/rejected/deferred |
| rejection_reason | Text nullable | |
| embedding | Vector(768) nullable | |
| extra_metadata | JSONB nullable (column "metadata") | |
| created_at, updated_at | datetime | |

Indexes: `(hypothesis_session_id)`, `(charter_id, status)`, `(cycle_id)`

### `experiment_specs`
Compiled protocol for one hypothesis — fully specified before execution.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| hypothesis_card_id | UUID FK hypothesis_cards CASCADE | |
| charter_id | UUID FK research_charters CASCADE | |
| cycle_id | UUID FK research_cycles CASCADE | |
| title | String(500) | |
| description | Text | |
| baseline | JSONB | {description, reference_run_id?, expected_metrics} |
| controls | JSONB | [{name, description, value}] |
| metrics | JSONB | [{name, direction, threshold?}] |
| expected_artifacts | JSONB | [{name, type, required}] |
| stop_conditions | JSONB | [{condition, threshold}] |
| code_plan | JSONB nullable | {language, entry_point, dependencies, files} |
| hardware_profile | JSONB nullable | {gpu_required, gpu_count, memory_gb, timeout_seconds} |
| base_image | String(500) nullable | Docker image reference |
| build_recipe | JSONB nullable | {dockerfile_content?, pip_requirements?} |
| status | String(50) default "draft" | draft/validated/rejected/executing/completed |
| rejection_reason | Text nullable | |
| created_at, updated_at | datetime | |

Indexes: `(hypothesis_card_id)`, `(cycle_id, status)`

### `run_records`
One execution of an ExperimentSpec.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| experiment_spec_id | UUID FK experiment_specs CASCADE | |
| charter_id | UUID FK research_charters CASCADE | |
| cycle_id | UUID FK research_cycles CASCADE | |
| run_number | Integer default 1 | Ordinal within spec |
| status | String(50) default "pending" | pending/workspace_setup/building/running/capturing/completed/failed/cancelled/paused |
| workspace_path | String(1024) nullable | Git worktree path |
| container_id | String(100) nullable | Docker container ID |
| image_ref | String(500) nullable | Resolved image tag |
| command | Text nullable | Actual command executed |
| env_vars | JSONB nullable | Sanitized env |
| resource_limits | JSONB nullable | {memory, cpu, gpu, timeout} |
| exit_code | Integer nullable | |
| stdout_path | String(1024) nullable | |
| stderr_path | String(1024) nullable | |
| metrics_output | JSONB nullable | {metric_name: value} |
| artifact_manifest | JSONB nullable | [{name, path, size_bytes, hash}] |
| resource_usage | JSONB nullable | {peak_memory_mb, gpu_util_avg, wall_time_s} |
| failure_class | String(50) nullable | dependency/oom/timeout/runtime/unknown |
| error | Text nullable | |
| started_at, completed_at, created_at, updated_at | datetime | |

Indexes: `(experiment_spec_id)`, `(cycle_id, status)`, `(container_id)`

### `run_telemetry`
High-frequency streaming rows for live UI.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| run_record_id | UUID FK run_records CASCADE | |
| timestamp | datetime default utcnow | |
| event_type | String(50) | log/metric/resource/status_change/heartbeat |
| payload | JSONB | Varies by event_type |

Indexes: `(run_record_id, timestamp)`

### `verification_reports`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| run_record_id | UUID FK run_records CASCADE | |
| charter_id | UUID FK research_charters CASCADE | |
| cycle_id | UUID FK research_cycles CASCADE | |
| verdict | String(50) | passed/failed/inconclusive |
| baseline_comparison | JSONB nullable | {metric: {baseline, actual, delta, pass}} |
| artifact_checks | JSONB nullable | [{name, expected, found, pass}] |
| output_contract | JSONB nullable | {checks: [{name, pass, detail}]} |
| metric_sanity | JSONB nullable | {checks: [{name, pass, detail}]} |
| warnings | JSONB nullable | |
| summary | Text | |
| created_at | datetime | |

Indexes: `(run_record_id)`, `(cycle_id, verdict)`

### `failure_postmortems`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| run_record_id | UUID FK run_records CASCADE | |
| verification_report_id | UUID FK verification_reports SET NULL nullable | |
| charter_id | UUID FK research_charters CASCADE | |
| cycle_id | UUID FK research_cycles CASCADE | |
| failure_class | String(50) | |
| root_cause | Text | |
| contributing_factors | JSONB nullable | [{factor, detail}] |
| error_trace | Text nullable | Last N lines of stderr |
| next_step_recommendation | Text nullable | |
| lessons | JSONB nullable | [{insight, applies_to}] |
| created_at | datetime | |

Indexes: `(run_record_id)`, `(cycle_id)`

---

## 3. SQLAlchemy Models

**New file:** `libs/storage/models/experiment.py`

7 model classes following existing patterns: `HypothesisSession`, `HypothesisCard`, `ExperimentSpec`, `RunRecord`, `RunTelemetry`, `VerificationReport`, `FailurePostmortem`.

Import in `libs/storage/models/__init__.py` so Alembic picks them up.

---

## 4. Pydantic Schemas

**New file:** `libs/schemas/experiment.py`

Key schemas:
- `HypothesisBudget` — `max_hypotheses: int = 10`, `max_critique_rounds: int = 2`
- `HypothesisSessionStartRequest`, `HypothesisSessionRead`, `HypothesisSessionStartResponse`
- `HypothesisCardRead`, `HypothesisCardUpdate` (status + rejection_reason)
- `ExperimentSpecRead`, `ExperimentSpecCompileRequest` (hypothesis_card_ids + optional hardware_profile/base_image)
- `RunRecordRead`, `RunStartRequest` (experiment_spec_id + gpu_enabled)
- `RunControlRequest` (action: pause/resume/cancel/retry)
- `RunTelemetryRead`
- `VerificationReportRead`, `FailurePostmortemRead`

---

## 5. Event Types

**Modify:** `libs/core/event_types.py` — add 4 new StrEnum classes:

```python
class IdeationEvents(StrEnum):
    session_started = "ideation.session_started"
    hypotheses_generated = "ideation.hypotheses_generated"
    hypotheses_critiqued = "ideation.hypotheses_critiqued"
    hypotheses_ranked = "ideation.hypotheses_ranked"
    session_completed = "ideation.session_completed"
    session_failed = "ideation.session_failed"

class ProtocolEvents(StrEnum):
    compilation_started = "protocol.compilation_started"
    spec_compiled = "protocol.spec_compiled"
    spec_rejected = "protocol.spec_rejected"
    compilation_completed = "protocol.compilation_completed"
    compilation_failed = "protocol.compilation_failed"

class ExecutionEvents(StrEnum):
    workspace_created = "execution.workspace_created"
    image_built = "execution.image_built"
    container_started = "execution.container_started"
    run_progress = "execution.run_progress"
    run_completed = "execution.run_completed"
    run_failed = "execution.run_failed"
    run_cancelled = "execution.run_cancelled"
    run_paused = "execution.run_paused"
    artifacts_captured = "execution.artifacts_captured"

class VerificationEvents(StrEnum):
    check_started = "verification.check_started"
    check_completed = "verification.check_completed"
    postmortem_generated = "verification.postmortem_generated"
```

---

## 6. Operator Chains

Three sub-chains, each following the established pattern (sync function, own DB session, `asyncio.run()` for LLM/async calls, returns `OperatorResult`).

### Chain A — Hypothesis Portfolio (`libs/ideation/operators/`)

Drives: `evidence_ready → portfolio_ready`

| # | Job type | Operator | What it does |
|---|----------|----------|-------------|
| 1 | `hypothesis_generate` | `generate.py` | Load EvidenceCards for cycle, call `hypothesis_generation` model role with evidence + charter context, create N `HypothesisCard` rows as "candidate" |
| 2 | `hypothesis_critique` | `critique.py` | Load candidates, call LLM in critique mode, fill critique/novelty_score/feasibility_score/impact_score |
| 3 | `hypothesis_rank` | `rank.py` | Compute weighted rank, set rank field, mark session completed, state_patch → `portfolio_ready` |

Common helpers in `_common.py`: `hypothesis_session_id_from_payload()`, `load_hypothesis_session()`, `append_step_log()`, `merge_stats()`, `enqueue_next()`, `mark_failed()`

### Chain B — Protocol Compilation (`libs/protocols/operators/`)

Drives: `portfolio_ready → protocol_ready`

| # | Job type | Operator | What it does |
|---|----------|----------|-------------|
| 4 | `protocol_compile` | `compile.py` | Load top-ranked or user-selected hypotheses, call `protocol_drafting` model role, generate ExperimentSpec rows. Validate completeness (baseline, metrics, stop conditions). Reject under-specified. State_patch → `protocol_ready` |

Supporting module: `libs/protocols/validation.py` — spec completeness checker.

### Chain C — Execution + Verification (`libs/execution/operators/`, `libs/verification/operators/`)

Drives: `protocol_ready → running → verifying → reporting`

| # | Job type | Operator | What it does |
|---|----------|----------|-------------|
| 5 | `execution_setup` | `setup.py` | Create git worktree, resolve/build Docker image, create RunRecord as "workspace_setup". Enqueue `execution_run` |
| 6 | `execution_run` | `run.py` | Launch Docker container (sibling, via Docker SDK), stream logs, capture telemetry, wait for completion/timeout. Update RunRecord with exit_code, metrics, artifacts. Enqueue `execution_capture` on success, `verification_check` on failure |
| 7 | `execution_capture` | `capture.py` | Collect artifact manifest, compute hashes, update RunRecord. State_patch → `verifying`. Enqueue `verification_check` |
| 8 | `verification_check` | `check.py` | Compare metrics to baseline, check artifact presence, validate output contracts. Create VerificationReport. Enqueue `verification_postmortem` if failed, else state_patch → `reporting` |
| 9 | `verification_postmortem` | `postmortem.py` | Call `evaluation` model role with error trace + metrics. Create FailurePostmortem. State_patch → `reporting` |

---

## 6a. Metric Contract: From Container Output to Typed Metrics

Raw container output must pass through a deterministic parsing/normalization layer before it can be trusted by verification. This boundary is the **metric contract**.

### Output protocol

Experiment containers write metrics to a well-known file: `/artifacts/metrics.json`. The protocol compiler (`protocol_compile` operator) generates the code entry point to produce this file, and the ExperimentSpec defines the expected schema.

**Required format** — a flat JSON object of `{metric_name: numeric_value}`:
```json
{"val_accuracy": 0.873, "train_loss": 0.142, "wall_time_s": 312.5}
```

### Parsing and normalization — `libs/execution/metrics.py`

New module with two functions:

```python
def parse_metrics(artifacts_dir: Path, expected_metrics: list[dict]) -> ParsedMetrics:
    """Read /artifacts/metrics.json and validate against the ExperimentSpec.metrics schema.

    Returns ParsedMetrics(values: dict[str, float], warnings: list[str], errors: list[str]).

    Rules:
    1. File must exist and be valid JSON — otherwise error "metrics file missing/corrupt"
    2. Each expected metric name must be present — missing → error per metric
    3. Each value must be a finite float (not NaN, not inf) — otherwise error per metric
    4. Extra metrics are kept but flagged as warnings
    5. Type coercion: int → float is allowed, everything else → error
    """

def classify_metric(name: str, value: float, spec_metric: dict) -> MetricVerdict:
    """Compare a single parsed metric value against its spec definition.

    spec_metric has: {name, direction: "maximize"|"minimize", threshold?: float}

    Returns MetricVerdict(name, value, baseline_value, delta, direction, passed: bool, detail: str).
    - If threshold is set and direction is "maximize": passed = (value >= threshold)
    - If threshold is set and direction is "minimize": passed = (value <= threshold)
    - If baseline exists in ExperimentSpec.baseline.expected_metrics: compute delta
    - If no threshold and no baseline: passed = True (informational only), detail notes "no threshold"
    """
```

### Integration into operator chain

1. **`execution_capture` operator** calls `parse_metrics()` after collecting artifacts. Stores `ParsedMetrics.values` as `RunRecord.metrics_output` and any parse errors as `RunRecord.error` with `failure_class = "metric_parse"`. If parse errors exist, run status becomes `"failed"` — it never reaches verification with unparseable metrics.

2. **`verification_check` operator** calls `classify_metric()` for each metric against the spec. The `VerificationReport.baseline_comparison` field stores the full `MetricVerdict` list. Verdict logic:
   - All metrics pass → `"passed"`
   - Any metric has a parse error → `"failed"` (should not happen if capture did its job)
   - Any metric fails threshold/baseline → `"failed"`
   - No thresholds defined, all metrics present → `"inconclusive"`

### Artifact contract — `libs/verification/contracts.py`

```python
def check_artifact_contract(artifact_manifest: list[dict], expected_artifacts: list[dict]) -> list[ArtifactCheck]:
    """For each expected artifact in ExperimentSpec.expected_artifacts:
    - Check it exists in manifest by name
    - If required=True and missing → failed
    - If present → passed, include size_bytes and hash
    Returns list of ArtifactCheck(name, expected, found, required, passed, detail).
    """
```

This makes the verification pipeline fully deterministic: container → `metrics.json` → `parse_metrics()` → `classify_metric()` → `VerificationReport`. No ambiguity about how raw output becomes a verdict.

---

## 6b. Run Control Contract

### Status transitions for each action

**Pause** — only valid when `RunRecord.status == "running"`:
1. Service sets `RunRecord.status = "paused"`
2. Worker's existing `pause_job()` sets `Job.status = "paused"` — the worker checks this on its next loop iteration
3. The `execution_run` operator checks `Job.status` inside its log-streaming loop (every N seconds). When it sees `paused`, it calls `docker pause <container_id>` (Docker SDK `container.pause()`, which sends `SIGSTOP` to all processes). The container stays alive but frozen — no CPU time consumed.
4. The operator returns `OperatorResult(success=True)` with the current progress snapshot in `state_patch`. The worker then calls `pause_job()` with the snapshot, so the job is resumable.
5. Emits `execution.run_paused` event.

**Resume** (from paused) — only valid when `RunRecord.status == "paused"`:
1. Service sets `RunRecord.status = "running"` and creates a new job `execution_run` with the same `run_record_id` in its payload plus `resume: true`.
2. The `execution_run` operator detects `resume: true`, looks up `RunRecord.container_id`, calls `container.unpause()` (sends `SIGCONT`), and re-enters the log-streaming loop.
3. Does **not** create a new container or worktree — the frozen container resumes in place.

**Cancel** — valid when `RunRecord.status` is `"running"` or `"paused"`:
1. Service sets `RunRecord.status = "cancelled"` and calls `cancel_job()` on the associated job.
2. If the container is paused: `container.unpause()` then `container.kill()`.
3. If the container is running: the worker's existing cancellation path (checks `current_job.status == JobStatus.cancelled` after execution) handles it. The `execution_run` operator also checks cancellation in its streaming loop and calls `container.kill()` + `container.remove()` early.
4. Workspace is cleaned up (`cleanup_worktree()`).
5. Emits `execution.run_cancelled` event.
6. No verification or postmortem is created for cancelled runs.

**Retry** — valid when `RunRecord.status` is `"failed"` or `"cancelled"`:
1. Service creates a **new** `RunRecord` with `run_number = old.run_number + 1`, same `experiment_spec_id`. The old record is immutable.
2. Enqueues a fresh `execution_setup` job. A new worktree and container are created from scratch.
3. Returns the new `RunRecordRead` and `job_id`.
4. The old run's artifacts, logs, and metrics remain intact for comparison.

### Canonical action rules

This is the single source of truth. The API, CLI, and service layer all enforce exactly these rules.

| Current status | Allowed actions |
|----------------|-----------------|
| pending | cancel |
| workspace_setup | cancel |
| building | cancel |
| running | pause, cancel |
| paused | resume, cancel |
| capturing | *(none — wait for completion)* |
| completed | *(none — terminal)* |
| failed | retry |
| cancelled | retry |

**Four actions exist:** `pause`, `resume`, `cancel`, `retry`. No other actions are accepted.

- `completed` is a success terminal — no retry (use a new experiment spec iteration instead).
- `failed` and `cancelled` allow retry (creates a new RunRecord).
- `pending`/`workspace_setup`/`building` allow cancel (job hasn't produced container state worth pausing).
- `capturing` allows no actions (brief step between container exit and artifact collection).

`control_run()` raises `HTTPException(409)` for any action not in the table above.

---

## 6c. Code Provenance: Where Executable Code Comes From

In Phase 3, experiment code follows a **generated-then-committed** model:

### Code generation flow

1. **`protocol_compile` operator** generates experiment code. The `ExperimentSpec.code_plan` field contains:
   ```json
   {
     "language": "python",
     "entry_point": "run_experiment.py",
     "dependencies": ["torch>=2.4", "numpy", "wandb"],
     "files": {
       "run_experiment.py": "<generated source>",
       "model.py": "<generated source>",
       "requirements.txt": "torch>=2.4\nnumpy\nwandb\n"
     }
   }
   ```
   The LLM (via `protocol_drafting` role) generates the actual file contents based on the hypothesis, evidence, and any coding skill prompt. The `code_plan.files` dict is the single source of truth for what will be executed.

2. **`execution_setup` operator** materializes the code:
   - Creates a git worktree from the repo's current HEAD: `git worktree add {data_root}/workspaces/{run_id} --detach`
   - Writes each file from `code_plan.files` into the worktree
   - Creates a commit in the worktree capturing the generated code: `git add . && git commit -m "experiment {spec.title} run {run_number}"`
   - Records the commit SHA in `RunRecord` as part of `env_vars.commit_sha`
   - This commit is the **durable lineage anchor** — it captures exactly what was executed, and `git diff HEAD~1` shows the generated code.

3. **`execution_run` operator** mounts the worktree into the container at `/workspace` (read-write). The container executes `code_plan.entry_point` inside `/workspace`.

4. **`execution_capture` operator** after the run:
   - Copies `/artifacts/*` from the container's artifact mount to `{data_root}/artifacts/{run_id}/`
   - Records the final worktree commit SHA (in case the experiment modified files during execution)
   - The worktree itself is preserved until explicitly cleaned up, so the full execution state is inspectable

### What this means for lineage

- Every run has a git commit SHA linking to the exact code that ran
- `ExperimentSpec.code_plan.files` stores the generated source in the DB (JSONB)
- The worktree preserves the full filesystem state
- `RunRecord.workspace_path` points to the worktree for post-hoc inspection
- Artifacts are copied out to a durable path independent of the worktree

### Phase 3 scope boundary

Phase 3 generates code from scratch for each experiment. It does not patch existing repo code or apply diffs. Future phases may add incremental modification (remediation patching), but Phase 3 always starts from a clean worktree + generated files.

---

## 7. Execution Runtime

### Git worktrees — `libs/adapters/git/worktree.py`

```
create_worktree(repo_root, run_id, branch?) → Path
    # git worktree add {data_root}/workspaces/{run_id} --detach
    # Returns worktree path

cleanup_worktree(worktree_path) → None
    # git worktree remove --force {path}
```

Uses `subprocess.run` (git CLI) — simple, no library needed.

### Docker execution — `libs/adapters/container/docker_runner.py`

Uses the `docker` Python SDK to manage sibling containers on the host Docker daemon.

Key design:
- `RunSpec` dataclass: workspace_path, image, command, env, gpu_enabled, gpu_count, memory_limit, timeout_seconds, artifact_output_path, network_mode ("none" for sandbox)
- `DockerRunner.build_image(dockerfile_content, tag, context_path) → str` — on-demand builds
- `DockerRunner.run(spec, telemetry_callback) → RunOutcome` — creates container, mounts workspace → /workspace and artifacts → /artifacts, adds GPU via `device_requests=[DeviceRequest(count=N, capabilities=[['gpu']])]`, streams logs with telemetry callback, waits with timeout, collects exit code, removes container
- `DockerRunner.stop(container_id)` / `DockerRunner.kill(container_id)` — for pause/cancel

---

## 7a. Telemetry Integration with Domain Events

The existing SSE stream (`apps/api/routers/events.py`) polls `domain_events` every 500ms and filters by charter/cycle. Phase 3 introduces two levels of telemetry, and both must be accessible through the **existing** event stream to avoid forcing clients to subscribe to two truth sources.

### Two-tier telemetry model

**Tier 1: Domain events** (low frequency, durable) — written to `domain_events` table. These are the events that external orchestrators and the main SSE stream consume. All Phase 3 operators emit domain events for state changes:
- `execution.workspace_created`, `execution.container_started`, `execution.run_completed`, `execution.run_failed`, etc.
- These carry `charter_id` and `cycle_id`, so the existing `/events/stream?charter_id=X` filter works immediately.

**Tier 2: Run telemetry** (high frequency, ephemeral) — written to `run_telemetry` table. Log lines, per-second metrics, GPU utilization snapshots. Too noisy for the main event stream but needed for the run detail UI.

### Bridge: periodic domain events from high-frequency telemetry

The `execution_run` operator emits a **`execution.run_progress`** domain event every 30 seconds (configurable) during container execution. This event carries a summary payload:
```json
{
  "run_record_id": "...",
  "wall_time_s": 142,
  "last_metric": {"train_loss": 0.23},
  "status": "running"
}
```

This means the main SSE stream shows run progress at 30s granularity — sufficient for orchestrators and the charter-level dashboard. The per-run SSE endpoint (`/runs/{id}/telemetry/stream`) provides second-by-second detail when a user drills into a specific run.

### SSE endpoint for run telemetry

`GET /runs/{id}/telemetry/stream` — follows the same pattern as the existing event SSE:
- Polls `run_telemetry` table by `run_record_id` with a `since` cursor (UUIDv7 time-sortable IDs)
- Poll interval: 1s (higher frequency than the 500ms domain event stream, since this is per-run)
- Same SSE format: `id: {telemetry.id}\ndata: {json}\n\n`
- Closes when `RunRecord.status` is terminal (completed/failed/cancelled)

### External monitoring contract

An orchestrator that only subscribes to the main event stream (`/events/stream?charter_id=X`) will see:
- `execution.workspace_created` — run starting
- `execution.container_started` — container up
- `execution.run_progress` — periodic heartbeat with latest metric
- `execution.run_completed` or `execution.run_failed` — terminal
- `verification.check_completed` — verdict
- `verification.postmortem_generated` — if applicable

No need to subscribe to the per-run telemetry stream unless they want log-level detail.

---

## 7b. Skill Lineage Recording

Today, skills are loaded via `load_skill_prompt()` (from `libs/discovery/skill_support.py`) but skill usage is only recorded in `step_log` JSON — not in the `skill_bindings` or `model_call_records` tables. Phase 3 operators must close this gap since the implementation plan requires skill usage in run lineage.

### Recording mechanism

New helper in `libs/skills/lineage.py`:

```python
def record_skill_usage(
    session: Session,
    *,
    skill_id: str,
    cycle_id: UUID,
    operator_type: str,
    job_id: UUID,
    config: dict[str, Any] | None = None,
) -> UUID:
    """Record a SkillBinding row when an operator loads and uses a skill.

    Also writes a ModelCallRecord if the skill triggered an LLM call.
    Returns the binding ID.
    """
```

This writes to the existing `skill_bindings` table (already has `skill_def_id`, `cycle_id`, `operator_type`, `bound_at`, `config` columns).

### Where it's called

Every Phase 3 operator that uses a skill calls `record_skill_usage()` after `load_skill_prompt()` returns a non-None prompt:

1. `hypothesis_generate` — records usage of `ideation.hypothesis_generation` skill
2. `hypothesis_critique` — records usage of `ideation.hypothesis_generation` skill (critique mode)
3. `protocol_compile` — records usage of `ideation.experiment_planning` skill
4. `execution_setup` / `execution_run` — records usage of `coding.experiment_coding` skill (if loaded)
5. `verification_check` / `verification_postmortem` — records usage of `verification.run_evaluation` skill

### ModelCallRecord integration

When an operator makes an LLM call through the `ModelRouter`, the router (or a wrapper) records a `ModelCallRecord` with:
- `cycle_id` from the operator input
- `job_id` from the operator input
- `provider`, `model_id`, `role` from the adapter/route
- `input_tokens`, `output_tokens` from the `CompletionResponse`

This is a cross-cutting concern. Implementation: add a `record_call()` helper that operators call after each `router.complete()` / `router.complete_structured()` call. Phase 3 operators are the first to use it consistently, but the helper is generic enough for Phases 1-2 operators to adopt later.

### Lineage in artifacts

`RunRecord` stores lineage references:
- `experiment_spec_id` → links to hypothesis → links to evidence → links to papers (full provenance chain)
- `env_vars.commit_sha` → exact code executed
- Skill bindings are queryable by `cycle_id` + `operator_type`
- Model call records are queryable by `job_id`

---

## 8. Service Layer

**New file:** `libs/core/services/experiment_service.py`

Key async functions (called by API routers, following `analysis_service.py` pattern):

- `start_hypothesis_session(db, cycle_id, charter_id, budget)` → `(HypothesisSessionRead, job_id)` — validates cycle is in `evidence_ready`, creates session + enqueues `hypothesis_generate`
- `list_hypothesis_cards(db, cycle_id, status?)` → paginated list
- `update_hypothesis_card(db, card_id, body)` → updated card (for select/reject/defer)
- `compile_protocols(db, cycle_id, charter_id, hypothesis_card_ids?, hardware_profile?)` → `(list[ExperimentSpecRead], job_id)` — validates `portfolio_ready`, enqueues `protocol_compile`
- `start_run(db, experiment_spec_id, gpu_enabled)` → `(RunRecordRead, job_id)` — creates RunRecord, enqueues `execution_setup`, transitions cycle to `running` if needed
- `control_run(db, run_id, action)` — pause/resume/cancel/retry (validates against canonical action rules table, 409 on illegal)
- `list_run_telemetry(db, run_id, since?, limit?)` → telemetry rows
- Query functions: `get_hypothesis_session`, `get_hypothesis_card`, `list_experiment_specs`, `get_experiment_spec`, `get_run_record`, `list_run_records`, `get_verification_report`, `get_failure_postmortem`

---

## 9. API Router

**New file:** `apps/api/routers/experiment.py`
**Mount in:** `apps/api/main.py` under `/api/v1`

```
POST   /hypotheses/sessions                → start_hypothesis_session
GET    /hypotheses/sessions                → list (query: charter_id?, cycle_id?)
GET    /hypotheses/sessions/{id}           → get
GET    /hypotheses/cards                   → list (query: cycle_id, status?)
GET    /hypotheses/cards/{id}              → get
PATCH  /hypotheses/cards/{id}              → update (select/reject/defer)

POST   /protocols/compile                  → compile_protocols
GET    /protocols/specs                    → list (query: cycle_id, status?)
GET    /protocols/specs/{id}               → get

POST   /runs                               → start_run
GET    /runs                               → list (query: cycle_id?, spec_id?, status?)
GET    /runs/{id}                          → get
POST   /runs/{id}/control                  → control_run (pause/resume/cancel/retry)
GET    /runs/{id}/telemetry                → list telemetry (query: since?, limit?)
GET    /runs/{id}/telemetry/stream         → SSE stream
GET    /runs/{id}/verification             → get_verification_report
GET    /runs/{id}/postmortem               → get_failure_postmortem
```

All endpoints follow existing pattern: `Depends(require_scope(...))`, `Depends(get_db)`, service call, `HTTPException` on error.

---

## 10. CLI Commands

**New file:** `apps/cli/commands/experiment.py`
**Register in:** `apps/cli/main.py`

```
synthetos experiment hypothesize   --cycle-id UUID --charter-id UUID [--wait/--no-wait]
synthetos experiment hypotheses    --cycle-id UUID [--status STATUS]
synthetos experiment compile       --cycle-id UUID --charter-id UUID [--wait/--no-wait]
synthetos experiment specs         --cycle-id UUID
synthetos experiment run           --spec-id UUID [--gpu] [--wait/--no-wait]
synthetos experiment runs          --cycle-id UUID
synthetos experiment status        --run-id UUID
synthetos experiment pause          --run-id UUID
synthetos experiment resume         --run-id UUID
synthetos experiment cancel        --run-id UUID
synthetos experiment verify        --run-id UUID
synthetos experiment postmortem    --run-id UUID
```

Follows existing CLI patterns: Typer app, `asyncio.run()` for service calls, polling loop for `--wait`, output via `typer.echo()`.

---

## 11. Worker Integration

**Modify:** `apps/worker/executor.py` — add 4 registration blocks:

```python
def _register_ideation_operators() -> None:
    from libs.ideation.operators import register as register_ideation
    register_ideation(register_operator)
_register_ideation_operators()

def _register_protocol_operators() -> None:
    from libs.protocols.operators import register as register_protocols
    register_protocols(register_operator)
_register_protocol_operators()

def _register_execution_operators() -> None:
    from libs.execution.operators import register as register_execution
    register_execution(register_operator)
_register_execution_operators()

def _register_verification_operators() -> None:
    from libs.verification.operators import register as register_verification
    register_verification(register_operator)
_register_verification_operators()
```

**Modify:** `apps/worker/main.py` — add failure cascade functions for Phase 3 job prefixes (`hypothesis_`, `protocol_`, `execution_`, `verification_`), following the `_mark_discovery_job_failed` / `_mark_analysis_job_failed` pattern.

---

## 12. Model Config

**Modify:** `configs/models.yaml` — add role entries for `hypothesis_generation` and `protocol_drafting` (roles already exist in the `ModelRole` enum):

```yaml
  hypothesis_generation:
    provider: anthropic
    model: claude-sonnet-4-20250514
    temperature: 0.7

  protocol_drafting:
    provider: anthropic
    model: claude-sonnet-4-20250514
    temperature: 0.3
```

---

## 13. Skills

4 new skill.md files:

| Skill ID | Directory | Phase | Operators |
|----------|-----------|-------|-----------|
| `ideation.hypothesis_generation` | `skills/ideation/hypothesis_generation/` | ideation | hypothesis_generate, hypothesis_critique |
| `ideation.experiment_planning` | `skills/ideation/experiment_planning/` | ideation | protocol_compile |
| `coding.experiment_coding` | `skills/coding/experiment_coding/` | execution | execution_setup, execution_run |
| `verification.run_evaluation` | `skills/verification/run_evaluation/` | verification | verification_check, verification_postmortem |

---

## 14. Implementation Order

Each step produces testable output before the next begins.

### Step 1: Foundation
- Alembic migration (7 tables)
- SQLAlchemy models (`libs/storage/models/experiment.py`)
- Update `libs/storage/models/__init__.py`
- Pydantic schemas (`libs/schemas/experiment.py`)
- Event types (4 new enums in `libs/core/event_types.py`)
- Add `docker>=7,<8` to `pyproject.toml`
- **Verify:** migration runs, `uv run synthetos db init`, models import, schemas validate

### Step 2: Hypothesis pipeline
- `libs/ideation/__init__.py`
- `libs/ideation/operators/__init__.py`, `_common.py`, `generate.py`, `critique.py`, `rank.py`
- Register in `apps/worker/executor.py`
- `libs/core/services/experiment_service.py` (hypothesis functions)
- **Verify:** enqueue hypothesis_generate manually, worker processes chain, cards appear in DB

### Step 3: Protocol compilation
- `libs/protocols/__init__.py`
- `libs/protocols/operators/__init__.py`, `_common.py`, `compile.py`
- `libs/protocols/validation.py`
- Register in executor
- Add protocol service functions to `experiment_service.py`
- **Verify:** compile specs from ranked hypotheses, under-specified rejected

### Step 4: Execution runtime
- `libs/adapters/git/worktree.py`
- `libs/adapters/container/__init__.py`, `docker_runner.py`
- `libs/execution/__init__.py`
- `libs/execution/metrics.py` (metric parsing/normalization layer)
- `libs/execution/operators/__init__.py`, `_common.py`, `setup.py`, `run.py`, `capture.py`
- Register in executor
- Add run service functions to `experiment_service.py`
- **Verify:** run a simple Python script in Docker container that writes `metrics.json`, confirm `parse_metrics()` produces typed output, confirm artifacts captured

### Step 5: Verification
- `libs/verification/__init__.py`
- `libs/verification/baseline.py` (per-metric classification via `classify_metric()`)
- `libs/verification/contracts.py` (artifact contract checker via `check_artifact_contract()`)
- `libs/verification/operators/__init__.py`, `_common.py`, `check.py`, `postmortem.py`
- Register in executor
- Add verification service functions
- **Verify:** verify a completed run with known metrics → `"passed"`, verify a run with missing metrics → `"failed"`, generate postmortem for failed run

### Step 6: Worker failure cascading
- Add `_mark_hypothesis_job_failed`, `_mark_protocol_job_failed`, `_mark_execution_job_failed` to `apps/worker/main.py`
- **Verify:** fail a hypothesis job, confirm session marked failed + event emitted

### Step 7: API + CLI
- `apps/api/routers/experiment.py`, mount in `main.py`
- `apps/cli/commands/experiment.py`, register in `main.py`
- **Verify:** full API flow via curl/CLI from hypothesis start to verification report

### Step 8: Telemetry + Controls
- SSE endpoint for run telemetry (`/runs/{id}/telemetry/stream`)
- Telemetry callback in `DockerRunner.run()` writing `run_telemetry` rows
- Periodic `execution.run_progress` domain events (30s interval) bridging to main SSE stream
- All 4 run control actions in service + API + CLI: pause (docker pause), resume (docker unpause), cancel (docker kill), retry (new RunRecord)
- Canonical action rules enforced in `control_run()` per section 6b table — 409 on illegal
- **Verify:** start run, see progress in main event stream, drill into per-run telemetry, pause mid-run, resume, cancel, retry creates new RunRecord

### Step 9: Skills + Lineage + Config
- 4 skill.md files
- `libs/skills/lineage.py` (record_skill_usage + record_model_call helpers)
- Integrate `record_skill_usage()` into all Phase 3 operators after `load_skill_prompt()`
- Integrate `record_model_call()` after each `ModelRouter` call
- Model config entries in `configs/models.yaml`
- **Verify:** `synthetos skill list` shows new skills, `skill_bindings` rows appear after operator runs, `model_call_records` rows appear after LLM calls

### Step 10: Web frontend
- API client functions (`apps/web/src/api/experiment.ts`)
- React Query hooks
- Route pages: hypothesis list, experiment specs, run detail with telemetry, verification report
- **Verify:** full flow in browser

---

## Files Modified (existing)

| File | Change |
|------|--------|
| `pyproject.toml` | Add `docker>=7,<8` dependency |
| `libs/core/event_types.py` | Add 4 event enum classes |
| `libs/storage/models/__init__.py` | Import experiment models |
| `apps/worker/executor.py` | Register 4 operator chains |
| `apps/worker/main.py` | Add Phase 3 failure cascade functions |
| `apps/api/main.py` | Mount experiment router |
| `apps/cli/main.py` | Register experiment subcommand |
| `configs/models.yaml` | Add hypothesis_generation + protocol_drafting role configs |

## Files Created (new)

| File | Contents |
|------|----------|
| `libs/storage/migrations/versions/20260413_000001_phase3_hypotheses_execution.py` | Migration for 7 tables |
| `libs/storage/models/experiment.py` | 7 SQLAlchemy models |
| `libs/schemas/experiment.py` | All Phase 3 Pydantic schemas |
| `libs/ideation/__init__.py` | Package init |
| `libs/ideation/operators/__init__.py` | Register function |
| `libs/ideation/operators/_common.py` | Session helpers |
| `libs/ideation/operators/generate.py` | hypothesis_generate operator |
| `libs/ideation/operators/critique.py` | hypothesis_critique operator |
| `libs/ideation/operators/rank.py` | hypothesis_rank operator |
| `libs/protocols/__init__.py` | Package init |
| `libs/protocols/operators/__init__.py` | Register function |
| `libs/protocols/operators/_common.py` | Session helpers |
| `libs/protocols/operators/compile.py` | protocol_compile operator |
| `libs/protocols/validation.py` | Spec completeness checker |
| `libs/execution/__init__.py` | Package init |
| `libs/execution/operators/__init__.py` | Register function |
| `libs/execution/operators/_common.py` | Run record helpers |
| `libs/execution/operators/setup.py` | execution_setup operator |
| `libs/execution/operators/run.py` | execution_run operator |
| `libs/execution/operators/capture.py` | execution_capture operator |
| `libs/execution/metrics.py` | Metric parsing/normalization (container output → typed metrics) |
| `libs/adapters/git/worktree.py` | Git worktree create/cleanup |
| `libs/adapters/container/__init__.py` | Package init |
| `libs/adapters/container/docker_runner.py` | Docker SDK runner |
| `libs/verification/__init__.py` | Package init |
| `libs/verification/operators/__init__.py` | Register function |
| `libs/verification/operators/_common.py` | Helpers |
| `libs/verification/operators/check.py` | verification_check operator |
| `libs/verification/operators/postmortem.py` | verification_postmortem operator |
| `libs/verification/baseline.py` | Metric classification (per-metric pass/fail against spec) |
| `libs/verification/contracts.py` | Artifact contract checker |
| `libs/skills/lineage.py` | Skill usage + model call recording helpers |
| `libs/core/services/experiment_service.py` | All Phase 3 service functions |
| `apps/api/routers/experiment.py` | API router |
| `apps/cli/commands/experiment.py` | CLI commands |
| `apps/web/src/api/experiment.ts` | Frontend API client |
| `skills/ideation/hypothesis_generation/skill.md` | Hypothesis skill |
| `skills/ideation/experiment_planning/skill.md` | Protocol skill |
| `skills/coding/experiment_coding/skill.md` | Coding skill |
| `skills/verification/run_evaluation/skill.md` | Verification skill |
