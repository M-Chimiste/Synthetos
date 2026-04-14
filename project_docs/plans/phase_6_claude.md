# Phase 6 — Cross-Charter Pattern Memory and Pilot Hardening

## Context

Phases 1–5 delivered the single-charter research loop through Phase 5's autonomous loop and completion reports. Every artifact (postmortems, remediation actions, directional signals, frontiers, loop decisions) is scoped to one `charter_id` — nothing crosses charter boundaries, and the system has no memory that survives a cycle.

Phase 6 turns accumulated experience into reusable **canonical patterns** that influence planning across cycles, hardens the skill trust model at the true runtime boundary, and closes the remaining product gaps (stale job recovery, orchestrator contract tests, pilot harness, readable reports) needed for day-to-day use.

Reference: [co_scientist_phased_implementation_plan.md §11](project_docs/co_scientist_phased_implementation_plan.md#L722).

---

## Scope Summary

Five workstreams, roughly in dependency order:

1. Canonical pattern memory — entity, consolidation operator, storage + retrieval.
2. Pattern reuse — inject into retrieval, hypothesis generation, remediation priors, verification/planning.
3. Skill & pattern trust hardening — runtime capability enforcement, pattern trust tiers, staleness decay.
4. Pilot harness & fixtures — problem fixtures, evaluation scripts, end-to-end runners.
5. Recovery & product hardening — stale-job reclaim, contract tests, timeline UI, report readability, resume.

---

## 1. Canonical Pattern Memory

### 1.1 Schema

New Alembic migration adds two tables via new file `libs/storage/models/patterns.py`:

- **`canonical_patterns`**
  - `id` (UUIDv7 PK), `pattern_type` (`failure`, `remediation`, `signal_trajectory`, `successful_line`, `retrieval_heuristic`)
  - `content_key` (text, NOT NULL) — stable dedupe hash; **unique constraint `(pattern_type, content_key)`**. Computed per `pattern_type` by `libs/patterns/content_key.py`:
    - `failure` → `sha256(failure_class | normalized_root_cause)`
    - `remediation` → `sha256(failure_class | strategy | outcome)`
    - `signal_trajectory` → `sha256(method_family | primary_metric_name | direction_bucket)`
    - `successful_line` → `sha256(method_family | primary_metric_name | problem_domain)`
    - `retrieval_heuristic` → `sha256(heuristic_kind | normalized_parameters_json)`
  - `title`, `summary` (text), `structured_body` (JSONB — type-specific payload)
  - `embedding` (vector(768), nullable — gte-modernbert matching the corpus)
  - `evidence_count` (int), `confidence` (float 0–1), `trust_tier` (`auto`, `curated`, `deprecated`)
  - `first_observed_at`, `last_observed_at`, `last_reinforced_at`, `staleness_score` (float)
  - `source_charter_ids` (UUID[]), `consolidation_version` (int)

The consolidation operator's upsert uses `ON CONFLICT (pattern_type, content_key)` — no invented key at execution time.
- **`pattern_observations`**
  - `id`, `pattern_id` FK, `charter_id`, `cycle_id`, `source_artifact_type` (`postmortem`, `remediation_action`, `directional_signal`, `metric_frontier`, `loop_decision`), `source_artifact_id`, `contribution` (JSONB), `observed_at`

Observations give auditable "why does this pattern exist" lineage; staleness decays on observation age, not row age.

### 1.2 Consolidation operator

New module [libs/patterns/](libs/patterns/) mirroring `libs/remediation/`:

- `libs/patterns/consolidation.py` — pure functions taking raw artifact rows and clustering them into pattern candidates:
  - **failure** — group `FailurePostmortem` by `(failure_class, root_cause)` with text-similarity clustering on `contributing_factors`.
  - **remediation** — group `RemediationAction` by `(failure_class, strategy, outcome)` with success rate as confidence.
  - **signal trajectory** — aggregate `DirectionalSignal.history_window` + `MetricFrontier` into method-family tendencies.
  - **successful line** — hypothesis → metric delta chains where `runs_since_improvement == 0` and signal is `breakthrough`/`advancing`.
- `libs/patterns/operators/consolidate.py` — `consolidate_patterns_operator` (follows [libs/core/operators.py](libs/core/operators.py) `OperatorInput`/`OperatorResult` contract). Idempotent, re-runnable, emits `pattern.consolidated`.
- `libs/patterns/embedding.py` — reuses the `libs/adapters/embeddings/` adapter.

### 1.3 Consolidation trigger — single canonical path

**Decision: async enqueue from `loop_report`, identical operator invocation from CLI/API.**

The only writer of patterns is the `consolidate_patterns_operator`. There is exactly one path to run it — the standard job queue. Three triggers enqueue jobs, no one runs inline:

- **End-of-cycle** — [libs/autonomy/operators/loop_report.py](libs/autonomy/operators/loop_report.py) (currently at line 38 generates the report and closes the cycle in one path) is modified to enqueue a `consolidate_patterns` job as its final side effect, **after** the completion artifact is written and the cycle state is advanced. The enqueue is a single `job_service.enqueue(...)` call; its failure does not block cycle close. The report path returns as before.
- **CLI** — `synthetos patterns consolidate [--charter <id>]` enqueues the same job.
- **API** — `POST /api/v1/patterns/consolidate` enqueues the same job and returns the `job_id` for tracking via the existing events stream.

**Why:** latency stays low (loop_report already does LLM work), failure is isolated (consolidation is retryable without redoing completion reports), idempotency is inherent to the operator (it upserts by `(pattern_type, content_key)`).

### 1.4 Retrieval

`libs/patterns/retrieval.py` — `find_relevant_patterns(charter_id, current_cycle_id, problem_profile, pattern_types, min_confidence, max_staleness, *, cross_charter_only=False)`:
- pgvector cosine by problem-profile embedding,
- filters `trust_tier != "deprecated"`,
- **excludes patterns whose observations are *entirely* from `current_cycle_id`** (prevents circular reinforcement of in-flight work). SQL shape: a pattern is retained iff `EXISTS (SELECT 1 FROM pattern_observations o WHERE o.pattern_id = p.id AND o.cycle_id <> :current_cycle_id)`. Patterns that have observations from both the current cycle and prior cycles remain retrievable — only "born this cycle" patterns are filtered out.
- decays confidence by `staleness_score`,
- returns ranked `PatternMatch` dataclasses.

**Cross-charter scope — explicit rule:** retrieval includes **all charters by default** (same-charter + cross-charter). Same-charter matches are allowed so within-project learnings reinforce themselves, but the `source_charter_ids` array is surfaced on every result and the injection helper (§2) boosts cross-charter evidence weight so a pattern seen across multiple charters outranks a same-charter-only pattern at equal raw confidence. Current-cycle exclusion is the retrieval layer's responsibility (not the injection helper's) so every caller gets the guarantee automatically.

### 1.5 Staleness decay

`libs/patterns/decay.py` — decays effective confidence based on days since `last_reinforced_at`. Past threshold, a pattern's `trust_tier` transitions: `auto` → `curated` (requires review to re-activate) → `deprecated` (excluded from retrieval).

**Scheduling — pinned:** the repo has no general scheduler today, and Phase 6 does not add one. Decay runs on the **worker periodic loop** alongside stale-job reclaim (§5.1): the worker's periodic tick (default 30s) enqueues a `decay_patterns` job at most once every `LAB_PATTERN_DECAY_INTERVAL_H` hours (default 24h), gated by a row in a lightweight `periodic_job_state` table tracking `last_run_at` per job kind. This reuses the existing job queue, keeps operational footprint unchanged, and gives natural observability through `DomainEvent`s. The same operator is invocable on demand via `synthetos patterns decay` and `POST /api/v1/patterns/decay`.

---

## 2. Pattern Reuse — Injection Points and Auto-Apply Policy

### 2.1 Auto-apply policy — aligned with the roadmap

Per §11.2.B of the plan ("automatic when thresholds are met" / "optional curation for higher-risk or stale patterns"):

- `trust_tier == "auto"` **and** `effective_confidence >= policy.patterns.min_confidence_auto` → pattern applies automatically, injected into operator context. An audit `DomainEvent` (`pattern.applied`) is emitted every time.
- `trust_tier == "curated"` → requires an explicit opt-in via `PatternApproval` (see §2.2) before it can be injected. Curated patterns are the "higher-risk or stale" path.
- `trust_tier == "deprecated"` → never injected.
- Patterns auto-demote from `auto` → `curated` on staleness or when evidence_count drops below threshold after source artifact pruning.

This inverts the previous wording: high-confidence auto patterns apply freely; only higher-risk/stale ones need review.

### 2.2 PatternApproval — new minimal approval surface

The repo has no generic approval subsystem today — autonomy's pause/resume ([apps/api/routers/autonomy.py](apps/api/routers/autonomy.py) line 177) is a narrow gate-resume path, not reusable. Rather than overfitting that path, add a purpose-scoped table:

- **`pattern_approvals`** — `id`, `pattern_id` FK, `charter_id` (nullable for global), `decision` (`approve`, `reject`), `actor_type`, `actor_id`, `rationale`, `expires_at` (nullable), `created_at`.
- API: `POST /api/v1/patterns/{id}/approve`, `POST /api/v1/patterns/{id}/reject`.
- Injection helper (§2.3) checks for a non-expired approve row when `trust_tier == "curated"`.

If a broader approval subsystem emerges later it can subsume this table — the shape is intentionally generic enough to migrate.

### 2.3 Injection points

A shared helper `libs/patterns/injection.py` exposes `inject_patterns(context, types, charter_id, current_cycle_id, policy) -> list[PatternMatch]`. `current_cycle_id` is passed through to `find_relevant_patterns` so the current-cycle exclusion rule fires automatically for every caller. Each operator below calls it with narrow scope; no structural rewrites.

| Injection point | File | How patterns feed in |
|---|---|---|
| Discovery retrieval guidance | [libs/discovery/operators/](libs/discovery/operators/) ranking/view operators | `retrieval_heuristic` patterns → scoring features + query expansions |
| Hypothesis generation | [libs/ideation/operators/](libs/ideation/operators/) generate operator | `successful_line` + `failure` patterns → prompt context |
| Remediation priors | [libs/remediation/operators/remediation.py](libs/remediation/operators/remediation.py) | `remediation` patterns with matching `failure_class` → strategy re-rank |
| Verification & planning | [libs/verification/operators/](libs/verification/operators/) and [libs/autonomy/operators/loop_decide.py](libs/autonomy/operators/loop_decide.py) | `signal_trajectory` patterns → bias continue/vary/pivot |

---

## 3. Skill & Pattern Trust Hardening

### 3.1 Skill runtime enforcement — at the real boundary

The actual runtime boundary today is **[libs/skills/lineage.py](libs/skills/lineage.py) `record_skill_usage`** — every operator that binds a skill calls this function at execution time. [libs/skills/registry.py](libs/skills/registry.py) only persists/queries definitions and [libs/skills/validator.py](libs/skills/validator.py) only validates at discovery time, so neither is the right enforcement site.

Plan:

- Rename/extend `record_skill_usage` in `libs/skills/lineage.py` so it:
  1. Loads the `SkillDefinition` (already does).
  2. Loads the active `ResearchCycle.config` skill policy.
  3. Enforces: if the skill's manifest declares any of the existing `ELEVATED_CAPABILITIES` set (from `validator.py`), the current `trust_tier` must satisfy the cycle policy (`skills.require_first_party_for_execution: bool`, default false locally, overridable to true for pilots/CI).
  4. On violation: raise a typed `SkillTrustViolation` and emit a `skill.blocked` audit event; do not create the `SkillBinding`.
  5. On success: emit `skill.invoked` (new) for every elevated-capability binding.
- Extract the enforcement logic to `libs/skills/enforcement.py` so it can be unit-tested in isolation; `lineage.record_skill_usage` becomes a thin wrapper that calls it.
- Validator checks stay in place for discovery-time feedback; runtime is the authoritative gate.

### 3.2 Pattern trust tiers

Mirror the skill trust model on the pattern side (see §2.1 and §2.2). Surface tier on every API response and in the UI patterns route.

### 3.3 Policy knobs in `ResearchCycle.config`

- `skills.require_first_party_for_execution: bool` (default false)
- `patterns.min_confidence_auto: float` (default 0.7)
- `patterns.max_staleness_days: int` (default 90)
- `patterns.cross_charter_weight_boost: float` (default 1.15)

### 3.4 Docs & examples

- Populate `skills/` with at least one user-local example that exercises an elevated capability, demonstrating the runtime gate.
- Add `skills/README.md` with trust-tier guidance and a worked example of a blocked invocation.

---

## 4. Patterns API — locked-down surface

Under `apps/api/routers/patterns.py`, with schemas in `libs/schemas/patterns.py`:

| Method | Path | Scope | Body / Query | Returns |
|---|---|---|---|---|
| GET | `/api/v1/patterns` | `patterns.read` | `pattern_type`, `trust_tier`, `min_confidence`, `charter_id`, `limit`, `cursor` | `PatternList` (paginated) |
| GET | `/api/v1/patterns/{id}` | `patterns.read` | — | `PatternDetail` (pattern + recent observations) |
| GET | `/api/v1/patterns/{id}/observations` | `patterns.read` | `limit`, `cursor` | `ObservationList` |
| POST | `/api/v1/patterns/consolidate` | `patterns.write` | `{charter_id?: UUID, pattern_types?: [str]}` | `{job_id: UUID}` |
| POST | `/api/v1/patterns/decay` | `patterns.write` | `{force?: bool}` | `{job_id: UUID}` |
| POST | `/api/v1/patterns/{id}/approve` | `patterns.write` | `{rationale: str, expires_at?: datetime, charter_id?: UUID}` | `PatternApproval` |
| POST | `/api/v1/patterns/{id}/reject` | `patterns.write` | `{rationale: str}` | `PatternApproval` |
| PATCH | `/api/v1/patterns/{id}/trust-tier` | `patterns.write` | `{trust_tier: str, rationale: str}` | `PatternDetail` |
| POST | `/api/v1/patterns/{id}/retrieve-preview` | `patterns.read` | `{problem_profile: ProblemProfile}` | `[PatternMatch]` (debug aid) |

Pydantic models go in `libs/schemas/patterns.py`: `PatternSummary`, `PatternDetail`, `PatternObservation`, `PatternMatch`, `PatternList`, `ObservationList`, `PatternApproval`. Scopes (`patterns.read`, `patterns.write`) are added to the existing flat scope set in [apps/api/auth.py](apps/api/auth.py). Contract tests in §5.2 snapshot these.

---

## 5. Recovery & Product Hardening

### 5.1 Stale job reclaim

[apps/worker/main.py](apps/worker/main.py) + [libs/core/services/job_service.py](libs/core/services/job_service.py) have no recovery if the worker crashes mid-execution.

Add `reclaim_stale_jobs(session, heartbeat_timeout_s, max_reclaims)` to `job_service.py`:
- Any job with `status in ("claimed", "running")` and `heartbeat_at` older than the timeout is reset to `pending` with incremented `reclaim_count`.
- After `max_reclaims` hits, the job transitions to `failed` with a structured error.
- Emits `job.reclaimed` / `job.reclaim_exhausted` events.
- Called from the worker at startup and every 30s thereafter.
- Configurable thresholds in settings (`LAB_JOB_HEARTBEAT_TIMEOUT_S`, `LAB_JOB_MAX_RECLAIMS`).

### 5.2 Orchestrator contract tests

`tests/integration/` and `tests/e2e/` are empty. Add `tests/contract/`:
- `test_openapi_stability.py` — snapshots `/openapi.json`; diff gate fails on breaking changes (missing paths, removed required fields, scope tightenings).
- `test_cycle_lifecycle.py` — black-box: external client creates charter → cycle → subscribes to SSE → drives through a minimal cycle via HTTP only.
- `test_pattern_api.py` — exercises every endpoint in §4 including consolidate → poll events → list → approve → retrieve-preview.

### 5.3 Timeline view & report readability

- `apps/web/src/routes/cycles/$cycleId/timeline.tsx` — chronological event stream with operator/phase grouping, run lineage, remediation chains, frontier progression. Subscribes to the existing SSE in [apps/api/routers/events.py](apps/api/routers/events.py).
- Replace raw `<pre>` markdown with `react-markdown` so completion reports, postmortems, and analysis packets render rich.
- Postmortem detail view linked from run pages.
- New `apps/web/src/routes/patterns/` — list + detail + approval actions.

### 5.4 Long-cycle resume

- Integration test that kills the worker mid-loop and restarts; confirms stale reclaim + idempotent `loop_decide` / `loop_report` resume cleanly.
- Extend [apps/worker/heartbeat.py](apps/worker/heartbeat.py) to refresh a cycle-level `last_activity_at` for dashboarding.

---

## 6. Pilot Harness & End-to-End Exercises

### 6.1 Fixture contract

A pilot fixture lives in `configs/problems/<problem_id>/` with:

- `charter.yaml` — required: `title`, `problem_statement`, `domain`, `success_criteria`, `expected_runtime_bucket` (one of: `ci_safe`, `workstation_cpu`, `workstation_gpu`).
- `autonomy.yaml` — required: `mode` (supervised/autonomous), budgets (`max_total_runs`, `max_wall_clock_hours`, compute cap).
- `seeds.yaml` — required: deterministic seeds for any stochastic operator invocation.
- `expected.yaml` — optional: reference metrics, expected frontier trajectories, pattern-reuse expectations for evaluation diff.
- `README.md` — required: human description, hardware prerequisites, run cost estimate.

Validator in `libs/pilot/fixture.py` enforces this contract before any pilot runs.

### 6.2 CI-safe vs workstation tiers

- **`ci_safe`** pilots (at least 1): run on CPU in under 5 minutes, no network, no GPU, seeded. Exercised on every CI run. Used to prove the full chain without real ML workload.
- **`workstation_cpu`** pilots (at least 1): small public benchmark, CPU-only, under ~30 minutes. Run locally or on nightly workstation CI.
- **`workstation_gpu`** pilots (at least 1): real small-scale ML problem (e.g., small HF dataset + tiny model), GPU-required. Run by the researcher; results checked into `artifacts/pilot/` for review. **Not** run in CI.

Phase 6 ships: 1 of each tier minimum (3 fixtures total).

### 6.3 Pilot runner

- `apps/cli/commands/pilot.py` — `synthetos pilot run <problem_id> [--tier <tier>] [--dry-run]`. Validates the fixture, creates charter, runs full chain under the fixture's budgets, writes evaluation JSON.
- `libs/pilot/runner.py` — orchestrates the run; reuses existing service layer (no new state machine paths).
- `libs/pilot/evaluation.py` — compares runs across discovery configs (Stable vs Discovery, rerank on/off), analysis coverage, autonomy behavior (budget burn, pivot frequency, frontier progression). Output: `artifacts/pilot/<problem_id>/<timestamp>/evaluation.{json,md}`.
- `synthetos pilot compare <run_a> <run_b>` — diff two pilot evaluations.

---

## Critical Files

**New**
- `libs/storage/models/patterns.py`
- `libs/storage/migrations/versions/<next>_phase6_patterns.py`
- `libs/patterns/{consolidation,embedding,retrieval,decay,injection}.py`
- `libs/patterns/operators/consolidate.py`
- `libs/skills/enforcement.py`
- `libs/schemas/patterns.py`
- `apps/api/routers/patterns.py`
- `apps/cli/commands/patterns.py`, `apps/cli/commands/pilot.py`
- `libs/pilot/{runner,evaluation,fixture}.py`
- `apps/web/src/routes/cycles/$cycleId/timeline.tsx`
- `apps/web/src/routes/patterns/{index,$patternId}.tsx`
- `configs/problems/<three_fixtures>/`
- `tests/contract/{test_openapi_stability,test_cycle_lifecycle,test_pattern_api}.py`
- `tests/unit/test_pattern_*.py`, `tests/unit/test_job_reclaim.py`, `tests/unit/test_skill_runtime_gate.py`
- `tests/integration/test_phase6_pilot.py`

**Modified**
- [libs/autonomy/operators/loop_report.py](libs/autonomy/operators/loop_report.py) — enqueue consolidation job as final side effect
- [libs/skills/lineage.py](libs/skills/lineage.py) — runtime trust-tier enforcement via `libs/skills/enforcement.py`
- [libs/discovery/operators/](libs/discovery/operators/) — call `inject_patterns`
- [libs/ideation/operators/](libs/ideation/operators/) — call `inject_patterns`
- [libs/remediation/operators/remediation.py](libs/remediation/operators/remediation.py) — pattern-aware strategy ranking
- [libs/autonomy/operators/loop_decide.py](libs/autonomy/operators/loop_decide.py) — pattern-biased decisions
- [libs/core/services/job_service.py](libs/core/services/job_service.py) — stale reclaim
- [apps/worker/main.py](apps/worker/main.py) — reclaim loop at startup + periodic
- [apps/worker/heartbeat.py](apps/worker/heartbeat.py) — cycle `last_activity_at` touch
- [apps/api/auth.py](apps/api/auth.py) — add `patterns.read`/`patterns.write` scopes
- `apps/web/src/routes/*` — markdown rendering upgrade

---

## Reused Existing Pieces

- `OperatorInput`/`OperatorResult` contract ([libs/core/operators.py](libs/core/operators.py)).
- Embedding adapter ([libs/adapters/embeddings/](libs/adapters/embeddings/)) for pattern embeddings.
- `DomainEvent` + SSE stream for pattern events and skill audit.
- `record_skill_usage` in [libs/skills/lineage.py](libs/skills/lineage.py) — true runtime boundary; extended, not replaced.
- `ELEVATED_CAPABILITIES` set in [libs/skills/validator.py](libs/skills/validator.py) — reused by runtime gate.
- `MetricFrontier` / `DirectionalSignal` / `FailurePostmortem` / `RemediationAction` / `LoopDecision` rows — raw inputs to consolidation; no schema changes.
- Job queue infra ([libs/core/services/job_service.py](libs/core/services/job_service.py)) — consolidation runs on the same queue as everything else.

---

## Verification

1. **Unit** — `uv run pytest tests/unit/test_pattern_*.py tests/unit/test_job_reclaim.py tests/unit/test_skill_runtime_gate.py`
2. **Integration** — `uv run pytest tests/integration/test_phase6_pilot.py` drives the `ci_safe` fixture end-to-end, asserts patterns are consolidated and injected on the next cycle.
3. **Contract** — `uv run pytest tests/contract/` with OpenAPI snapshot gate.
4. **Pilot** — `uv run synthetos pilot run <ci_safe_fixture>` in CI; `uv run synthetos pilot run <workstation_gpu_fixture>` on the researcher box; confirm completion report references reused patterns in `source_charter_ids`.
5. **Recovery** — kill worker mid-run (`kill -9`); restart; confirm `job.reclaimed` events fire and cycle resumes cleanly.
6. **UI** — `cd apps/web && npm run dev`; drive a cycle; confirm timeline route renders events live, markdown reports render rich, patterns route shows trust tiers and approval actions.
7. **Exit criteria** match §11.4 of the phased plan: cross-charter pattern reuse works, auto-apply thresholds honored, stale decay visible, full cycle completes across the fixture set, orchestrator-only drive works via API with observability and policy control.

---

## Explicit Non-Goals

- No multi-user/multi-tenant auth — still single-user local.
- No distributed worker scale-out — single worker, crash-resilient is enough.
- No general-purpose approval subsystem — `PatternApproval` is scoped to patterns; autonomy gate-resume is unchanged.
- No retroactive pattern extraction from external corpora — only this system's own postmortems/remediations/signals/frontiers/loop decisions.
- No pattern editing UI beyond trust-tier toggles and approval actions — authoring remains an emergent, system-driven process.
