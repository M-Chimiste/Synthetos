# Technical Roadmap: Autonomous Learning & Experimental Signal

**Product:** ML Laboratory Co-Scientist
**Status:** Working Draft v1
**Last Updated:** 2026-03-23
**Prerequisite:** Phases 0-5.1 complete. arXiv warehouse + hybrid search operational.

---

## 1. Motivation

The co-scientist currently treats all non-ROBUST outcomes as problems requiring human attention. Mechanical failures (OOM, missing deps, timeouts) generate expensive LLM postmortems. Experimental results that move metrics in the wrong direction trigger the same pipeline as a crashed container. And every hypothesis pivot requires human approval.

This is backwards. A co-scientist should:

1. **Auto-remediate infrastructure noise** without thinking about it
2. **Interpret experimental signal** — is the metric moving in the right direction, stalling, or regressing?
3. **Pivot autonomously** when a hypothesis line is exhausted, using portfolio ranking to pick the next one
4. **Learn from experience** across charters, not just within one research problem
5. **Operate overnight** — the human sleeps, the co-scientist runs experiments

This roadmap defines four phases to get there. Each phase is scoped to be independently useful and implementable as a standalone plan.

---

## 2. Design Principles

### 2.1 Deterministic first, LLM second

The current verification system gets this right: outcome is determined by checks, the LLM explains. This principle extends to all new tiers. Auto-remediation is a lookup table. Directional signal is arithmetic on metrics. The LLM is called only when deterministic logic can't resolve ambiguity.

### 2.2 The interesting failure is a successful run with bad results

OOM is not interesting — halve batch size and retry. A run that completes, produces valid metrics, and shows the hypothesis moving the wrong direction? That's the signal the co-scientist needs to reason about. The system should spend its intelligence budget here, not on infrastructure.

### 2.3 Autonomy is the default, escalation is the exception

Inspired by autoresearch: *"do NOT pause to ask the human. The human might be asleep."* The co-scientist should have a clear autonomy policy that defines what it can do without asking. Human gates should exist only at genuine decision boundaries (portfolio exhausted, ambiguous multi-metric tradeoffs, success criteria met).

### 2.4 Memory has tiers with different lifetimes

Inspired by Hermes Agent's three-tier memory. Short-term context (current cycle), medium-term patterns (current charter), and long-term procedural knowledge (cross-charter canonical patterns) serve different purposes and decay at different rates.

### 2.5 Keep/discard is more useful than a taxonomy

Autoresearch's binary keep/discard on a single scalar is crude but decisive. Our system needs to handle multi-metric experiments, but the core question is the same: did this run advance the research goal or not? Everything else is detail.

---

## 3. Current State (What Exists)

| Component | Location | What It Does | Limitation |
|-----------|----------|-------------|------------|
| `classify_failure()` | `libs/execution/artifacts.py` | Deterministic failure class from exit code + stderr | Flat taxonomy, no auto-remediation |
| `determine_outcome()` | `libs/verification/outcome.py` | INVALID/REJECTED/TENTATIVE/ROBUST from checks | Binary pass/fail on baseline, no directional signal |
| `compare_to_baseline()` | `libs/verification/checks.py` | Delta vs declared baseline | Only checks pass/fail, ignores trend across runs |
| `compare_to_historical()` | `libs/verification/historical.py` | Delta vs prior runs | Returns raw deltas, no trend analysis or stall detection |
| `failure_postmortem_operator` | `libs/orchestration/operators.py` | LLM generates structured postmortem | Fires for all failures including trivial mechanical ones |
| `aggregate_failure_guidance()` | `libs/verification/failure_memory.py` | Collects retrieval/protocol hints from postmortems | Charter-scoped only, no cross-charter learning |
| `get_hypothesis_failure_caution()` | `libs/verification/failure_memory.py` | Portfolio penalty for repeated failures | Counts failures, doesn't distinguish mechanical from experimental |
| `build_next_step_recommendations()` | `libs/verification/recommendations.py` | Structured next-step suggestions | Recommendations only — no autonomous execution of those steps |
| Autonomy policy | `configs/policies/default.yaml` | `auto_run_profiles`, `max_retry_attempts` | No auto-pivot, no directional evaluation, no unattended loop |

---

## 4. Phase A — Auto-Remediation Layer

**Goal:** Mechanical failures never reach the LLM. Infrastructure noise is handled by a deterministic retry-with-fix loop.

**Why first:** This is the highest-ROI change. It eliminates wasted LLM calls and compute on problems with known solutions, freeing the system to focus on experimental signal.

### A.1 Two-Stage Remediation

Mechanical failures get a **fast deterministic fix first**, then **LLM-assisted debugging if the fast fix doesn't work**. The LLM is writing the experiment code, so feeding stack traces and error context back to it for a code-level fix is the natural loop.

**Stage 1 — Deterministic fix (no LLM):**

| Failure Class | Fast Fix | Max Attempts |
|---------------|----------|--------------|
| `dependency_failure` | Parse missing module from stderr, add to `requirements.txt` / build recipe, rebuild container, retry | 2 |
| `oom_or_resource_limit` | Halve batch size in experiment spec (or step up execution profile if available), retry | 2 |
| `timeout` | Double timeout limit (up to policy max), retry | 1 |
| `metric_parse_failure` | Inject metrics-writing wrapper into run script, retry | 1 |
| `invalid_artifact_output` | Inject artifact manifest writer, retry | 1 |

**Stage 2 — LLM-assisted debugging (if Stage 1 fails or isn't applicable):**

| Failure Class | LLM Action |
|---------------|-----------|
| `runtime_exception` | Feed stack trace + experiment code + stderr to coder/debugger route. LLM patches the generated code and retries. |
| `dependency_failure` (Stage 1 exhausted) | LLM analyzes the full dependency conflict, suggests version pins or alternative packages. |
| `oom_or_resource_limit` (Stage 1 exhausted) | LLM reviews the code for memory inefficiencies (e.g., loading full dataset into memory, redundant copies). |
| `metric_parse_failure` (Stage 1 exhausted) | LLM reads the experiment code's output logic and fixes the metrics serialization. |
| Any failure with stack trace | LLM gets: original experiment spec, generated code, full stderr/stack trace, and the failure class. Returns a code patch + explanation. |

This creates a natural feedback loop: the LLM writes the experiment code (in the coding operator), and when that code fails, the stack trace and error context flow back to the same model route for debugging — similar to how a developer would read their own error output.

### A.2 Remediation Operator

New operator: `auto_remediate_operator`. Runs *before* the postmortem operator in the verification chain.

- Input: run record with failure classification, stderr, generated code
- **Stage 1**: Check deterministic remediation table. If a fast fix exists and under attempt limit: apply fix, enqueue retry, emit `auto_remediated` event with `stage: "deterministic"`
- **Stage 2**: If Stage 1 fails or isn't applicable, and the failure has a stack trace or meaningful stderr: call LLM debugger route with the error context + original code. If LLM produces a code patch: apply patch, enqueue retry, emit `auto_remediated` event with `stage: "llm_debug"`
- **Escalate**: If both stages exhausted: pass through to existing postmortem operator for full analysis

### A.3 Spec Mutation & Code Patching Primitives

**Deterministic mutations** (Stage 1) — modify ExperimentSpec or RunSpec:

- `add_dependency(spec, package_name)` — adds to `resource_requirements.packages`
- `reduce_batch_size(spec, factor=0.5)` — halves batch size in method params
- `step_up_profile(spec, available_profiles)` — moves to next execution profile
- `extend_timeout(spec, factor=2.0, max_seconds)` — doubles timeout within policy limit

**LLM code patches** (Stage 2) — modify the generated experiment code:

- `debug_and_patch(code, stderr, stack_trace, spec, model_route)` — sends error context to LLM debugger route, returns a code diff + explanation
- The LLM receives: the original experiment spec (what the code is supposed to do), the generated code (what was written), the full stderr/stack trace (what went wrong), and the failure classification (category of problem)
- The LLM returns: a code patch (unified diff or replacement), an explanation of the fix, and a confidence level
- Low-confidence patches (LLM unsure of the fix) are logged but not auto-applied — escalated to postmortem instead

**Lineage tracking**: Every mutation (deterministic or LLM) is recorded in `remediation_lineage` on the new run, creating an audit trail of what was tried:

```
remediation_lineage: [
  {stage: "deterministic", action: "reduce_batch_size", factor: 0.5, attempt: 1},
  {stage: "llm_debug", model_route: "debugger", patch_summary: "Fixed tensor shape mismatch in forward()", confidence: 0.85, attempt: 2}
]
```

### A.4 Policy Controls

New policy section in `default.yaml`:

```yaml
remediation:
  enabled: true
  max_auto_remediations_per_run: 3
  allowed_actions:
    - install_dependency
    - reduce_batch_size
    - step_up_profile
    - extend_timeout
  escalate_after_exhaustion: true  # fall through to postmortem
```

### A.5 Changes to Existing Code

- `failure_postmortem_operator` gains a guard: skip if `auto_remediate_operator` already handled the failure
- `get_hypothesis_failure_caution()` excludes auto-remediated runs from penalty calculation (they're infrastructure, not experimental signal)
- New domain event: `auto_remediated` with remediation action, original failure class, and lineage

### A.6 Acceptance Criteria

- Dependency failure with "No module named torch" → Stage 1 auto-installs torch, retries, succeeds without human intervention
- OOM on first run → Stage 1 halves batch size, second run succeeds
- Runtime exception with stack trace → Stage 2 sends error to LLM debugger, LLM patches the code, retry succeeds
- Stage 1 fix fails (e.g., dependency conflict persists) → Stage 2 LLM analyzes the full error, suggests version pin or alternative
- Both stages exhausted → escalates to full postmortem operator
- Low-confidence LLM patch → logged but not applied, escalates to postmortem
- Remediation lineage is visible on the run record showing every fix attempt
- Auto-remediated runs are excluded from hypothesis failure penalty

---

## 5. Phase B — Directional Signal Evaluation

**Goal:** The system can answer "is this hypothesis line making progress?" using metric trends, not just pass/fail against a baseline.

**Why second:** Once mechanical failures are auto-remediated, most runs that reach verification will have valid metrics. The system needs to interpret what those metrics mean for the research direction.

### B.1 Signal Classification

Extend `VerificationOutcome` or add a parallel `DirectionalSignal` enum:

| Signal | Meaning | Criteria |
|--------|---------|----------|
| `advancing` | Primary metric improving meaningfully | Delta > significance threshold AND consistent direction across recent runs |
| `stalled` | No meaningful change | Abs(delta) < significance threshold for N consecutive runs |
| `regressing` | Moving in the wrong direction | Delta in wrong direction AND statistically significant |
| `noisy` | High variance, no clear direction | Coefficient of variation across recent runs exceeds threshold |
| `breakthrough` | Large unexpected improvement | Delta exceeds 2x the historical mean improvement |

### B.2 Metric Trend Analysis

New module: `libs/verification/trend.py`

- `compute_metric_series(session, charter_id, hypothesis_id, metric_name)` — ordered list of `(run_public_id, value, timestamp)` for all comparable runs
- `classify_direction(series, higher_is_better, significance_threshold)` — returns `DirectionalSignal` using:
  - Linear regression slope over last N runs
  - Mann-Kendall trend test for monotonic trend
  - Coefficient of variation for noise detection
  - Delta from frontier (best-so-far) for breakthrough detection
- `compute_frontier(series, higher_is_better)` — running best value, used to detect stalls relative to peak

### B.3 Multi-Metric Reconciliation

Research problems often have multiple metrics (accuracy + latency, F1 + inference time). When metrics conflict:

- Charter declares a **primary metric** and optional **constraint metrics** with bounds
- Primary metric direction drives the keep/discard decision
- Constraint violations (latency > 100ms) trigger `constraint_violated` signal regardless of primary metric
- When primary is `advancing` but a constraint is violated: `advancing_with_constraints` — the system should attempt to address the constraint without abandoning the approach

### B.4 Significance Thresholds

Per-metric configurable thresholds in the experiment spec or charter:

```yaml
success_criteria:
  primary_metric: val_accuracy
  higher_is_better: true
  significance_threshold: 0.005   # 0.5% change counts as meaningful
  stall_window: 3                 # 3 consecutive runs below threshold = stalled
  constraint_metrics:
    - name: inference_time_ms
      upper_bound: 100
    - name: model_size_mb
      upper_bound: 500
```

### B.5 Integration with Verification

- `verification_evaluator_operator` calls `classify_direction()` after existing checks
- Directional signal is stored on the `VerificationReport` (new field: `directional_signal`)
- `build_next_step_recommendations()` uses directional signal:
  - `advancing` → continue, maybe intensify
  - `stalled` → suggest parameter sweep or pivot
  - `regressing` → revert last change, try different approach
  - `noisy` → increase run count for statistical power
  - `breakthrough` → flag for human attention (good news worth reviewing)

### B.6 Frontier Tracking

New entity or extension to run records: **metric frontier** per charter + hypothesis line.

- Updated after each verified run
- Records: best value, which run achieved it, how many runs since last improvement
- "Runs since last improvement" is the key stall indicator
- Visible in the timeline UI as a frontier chart

### B.7 Acceptance Criteria

- 3 runs with <0.5% accuracy change → `stalled` signal, recommendation to pivot
- Run with 5% accuracy improvement over frontier → `breakthrough` signal
- Run where accuracy improves but latency exceeds constraint → `advancing_with_constraints`
- Noisy series (CV > 0.1 over 5 runs) → `noisy` signal, recommendation for more runs

---

## 6. Phase C — Autonomous Experiment Loop

**Goal:** The co-scientist can run an unattended experiment sequence: pick hypothesis, run experiment, evaluate signal, pivot or continue, repeat — without human approval at each step.

**Why third:** Phases A and B give the system the ability to handle failures and interpret results. This phase uses those capabilities to close the loop.

### C.1 Autonomy Policy

Extend `configs/policies/default.yaml`:

```yaml
autonomy:
  mode: supervised          # supervised | autonomous | overnight
  max_unattended_runs: 10   # hard cap before requiring human check-in
  auto_pivot_on_stall: true
  auto_pivot_on_regression: true
  auto_continue_on_advancing: true
  escalate_on_breakthrough: true
  escalate_on_portfolio_exhausted: true
  escalate_on_ambiguous_signal: true
  budget_limits:
    max_compute_hours: 8
    max_runs_per_hypothesis: 5
    max_total_runs: 50
```

Three modes:

- **supervised** (current behavior): human approves each transition
- **autonomous**: system executes the full loop, escalates only at defined boundaries
- **overnight**: autonomous + relaxed escalation (only on portfolio exhaustion or budget limits)

### C.2 Loop Operator

New operator: `autonomous_loop_operator`. Replaces the current linear operator pipeline when autonomy mode is enabled.

```
while budget_remaining and portfolio_not_exhausted:
    hypothesis = pick_next_hypothesis(portfolio)
    spec = generate_or_reuse_experiment_spec(hypothesis)

    run = execute_run(spec)

    if run.failed and auto_remediable:
        run = auto_remediate_and_retry(run)  # Phase A

    if run.succeeded:
        signal = evaluate_directional_signal(run)  # Phase B

        match signal:
            case advancing:
                update_frontier(run)
                continue with same hypothesis (maybe intensify)
            case stalled:
                if runs_on_this_hypothesis >= max_runs_per_hypothesis:
                    mark_hypothesis_stalled, pick next
                else:
                    suggest_parameter_variation, retry
            case regressing:
                mark_hypothesis_regressing, pick next
            case noisy:
                increase_run_count, retry for statistical power
            case breakthrough:
                update_frontier(run)
                if escalate_on_breakthrough: notify human
                else: continue

    if all hypotheses stalled or regressing:
        escalate: "portfolio exhausted, need new hypotheses or literature"
```

### C.3 Hypothesis Lifecycle Transitions

Extend `HypothesisCard.status` with autonomous transitions:

| Current Status | Signal | New Status | Action |
|---------------|--------|-----------|--------|
| `active` | `advancing` | `active` | Continue experiments |
| `active` | `stalled` (< max runs) | `active` | Try parameter variation |
| `active` | `stalled` (>= max runs) | `stalled` | Pick next hypothesis |
| `active` | `regressing` | `deprioritized` | Pick next hypothesis, reduce portfolio rank |
| `active` | `breakthrough` | `promising` | Update frontier, optionally notify human |
| `stalled` | Re-selected after literature update | `active` | Resume with new approach |
| `promising` | Meets success criteria | `validated` | Escalate to human for review |

### C.4 Run Budget Tracking

New fields on `ResearchCycle`:

- `total_compute_minutes` — accumulated across all runs
- `total_run_count` — count of completed runs
- `runs_per_hypothesis` — dict of hypothesis_id → run count

Budget checks run before each experiment. When limits hit, the loop stops cleanly with a summary of what was tried and where things stand.

### C.5 Overnight Mode

When `autonomy.mode == "overnight"`:

- Breakthroughs are logged but don't interrupt the loop
- Stalled hypotheses are auto-pivoted without notification
- The loop runs until budget exhaustion or portfolio exhaustion
- On completion: generate a structured summary report covering all runs, pivots, and the final state of each hypothesis
- The human reviews the summary in the morning, not individual run approvals

### C.6 Acceptance Criteria

- Overnight mode: system runs 10+ experiments across 3+ hypotheses without human input
- Auto-pivot: hypothesis stalls after 3 runs → system picks next ranked hypothesis and continues
- Budget enforcement: loop stops at compute hour limit with clean summary
- Portfolio exhaustion: all hypotheses stalled/regressing → system stops and requests new literature intake

---

## 7. Phase D — Cross-Charter Procedural Memory

**Goal:** The system learns reusable patterns from experience across research problems, building a knowledge base that improves performance over time.

**Why last:** This is the highest-value long-term investment but requires Phases A-C to generate the operational data. You need many autonomous experiment runs before cross-charter patterns become meaningful.

### D.1 Two-Tier Memory Architecture

**Tier 1 (exists): Raw observations** — individual postmortems, verification reports, run records. Charter-scoped, high-detail, high-volume.

**Tier 2 (new): Canonical patterns** — distilled knowledge abstracted from individual observations. Cross-charter, curated, long-lived.

### D.2 Pattern Entity

New entity: `CanonicalPattern`

```
CanonicalPattern:
  public_id: str
  pattern_type: str           # "failure_pattern" | "method_pattern" | "signal_pattern"
  title: str                  # "OOM on large tabular datasets with default batch size"
  description: str            # 2-3 sentence abstract
  trigger_conditions: list    # When does this pattern apply?
  proven_actions: list        # What worked? [{action, success_rate, evidence_count}]
  disproven_actions: list     # What didn't work?
  evidence_refs: list         # Links to source postmortems/runs across charters
  confidence_score: float     # Based on evidence count and consistency
  staleness_context: dict     # Environment assumptions (torch version, hardware, etc.)
  created_at: datetime
  updated_at: datetime
  last_validated_at: datetime
```

Pattern types:

- **Failure patterns**: "dependency X requires CUDA toolkit ≥ 12.0" — remediation knowledge
- **Method patterns**: "learning rate warmup improves convergence on transformer fine-tuning" — experimental knowledge
- **Signal patterns**: "accuracy plateau after epoch 3 on small datasets indicates overfitting, not convergence" — interpretation knowledge

### D.3 Pattern Consolidation

Periodic background operator: `pattern_consolidation_operator`

- Runs on schedule (e.g., after every 10th completed cycle) or on-demand
- Clusters postmortems by failure class + semantic similarity of root cause summaries
- Clusters successful runs by method similarity + domain
- For each cluster with 3+ observations: generates or updates a `CanonicalPattern`
- Uses LLM (synthesizer route) to extract the generalizable pattern from specific instances
- Tracks evidence count and consistency for confidence scoring

### D.4 Pattern Retrieval

Patterns feed into existing operators:

- **`auto_remediate_operator`** (Phase A): check canonical failure patterns before the static remediation table. If a pattern matches with high confidence, apply its proven action.
- **`hypothesis_generation`**: inject relevant method patterns as prior knowledge when generating new hypotheses
- **`source_retrieval_operator`**: use pattern retrieval hints to augment literature queries (extends existing `retrieval_guidance` from failure memory)
- **`verification_evaluator_operator`**: use signal patterns to interpret ambiguous results

Retrieval uses the arXiv warehouse's hybrid search infrastructure applied to pattern descriptions — semantic similarity over pattern titles and descriptions.

### D.5 Staleness and Decay

Patterns have an environmental context (Python version, framework versions, hardware). When context changes:

- `staleness_context` records the assumptions under which the pattern was validated
- Before applying a pattern, check if its context still matches the current environment
- Patterns not validated in 30 days get `confidence_score` decay (multiplied by 0.9 per month)
- Patterns with confidence below threshold are marked `needs_revalidation`
- Human can curate: confirm, dismiss, or refine patterns

### D.6 Hermes-Inspired Skill Extraction

When a canonical pattern reaches high confidence (5+ evidence refs, 80%+ success rate), the system can extract it as a **procedural skill** — a reusable instruction set that gets injected into operator context.

Example: a failure pattern about CUDA compatibility evolves into a skill that proactively checks CUDA version before launching GPU runs.

This bridges Hermes Agent's "skill files as procedural memory" concept into our operator architecture.

### D.7 Acceptance Criteria

- After 20+ runs across 3+ charters: at least 2 canonical patterns auto-generated
- Pattern with "reduce batch size on OOM" matches across charters with high confidence
- Pattern confidence decays when environment context changes
- Patterns with 80%+ success rate are usable by auto-remediation without LLM postmortem
- Human can view, confirm, or dismiss patterns through the API/UI

---

## 8. Phase Dependencies

```
Phase A (Auto-Remediation)
    ↓
Phase B (Directional Signal)
    ↓
Phase C (Autonomous Loop)     ← requires both A and B
    ↓
Phase D (Procedural Memory)   ← requires operational data from C
```

Phases A and B can be developed in parallel — they're independent. Phase C depends on both. Phase D depends on C generating enough data to consolidate.

---

## 9. New Entities Summary

| Entity | Phase | Purpose |
|--------|-------|---------|
| `RemediationAction` | A | Records auto-fix applied to a run (lineage) |
| `MetricFrontier` | B | Best-so-far tracker per charter + hypothesis line |
| `DirectionalSignal` | B | Enum: advancing/stalled/regressing/noisy/breakthrough |
| `RunBudget` | C | Compute/run budget tracking per cycle |
| `CanonicalPattern` | D | Cross-charter distilled knowledge |

---

## 10. Policy Changes Summary

| Policy Key | Phase | Purpose |
|------------|-------|---------|
| `remediation.enabled` | A | Toggle auto-remediation |
| `remediation.allowed_actions` | A | Which auto-fixes are permitted |
| `remediation.max_auto_remediations_per_run` | A | Cap per-run auto-fix attempts |
| `signal.significance_threshold` | B | Minimum delta to count as meaningful |
| `signal.stall_window` | B | Consecutive below-threshold runs to declare stall |
| `autonomy.mode` | C | supervised / autonomous / overnight |
| `autonomy.max_unattended_runs` | C | Hard cap before human check-in |
| `autonomy.auto_pivot_on_stall` | C | Auto-switch hypothesis on stall |
| `autonomy.budget_limits.*` | C | Compute hours, run counts |
| `memory.consolidation_interval` | D | How often to run pattern consolidation |
| `memory.confidence_decay_rate` | D | Monthly decay multiplier for stale patterns |

---

## 11. Files Likely Affected

### Phase A
- `libs/execution/artifacts.py` — extend `classify_failure()` or add `lookup_remediation()`
- `libs/orchestration/operators.py` — new `auto_remediate_operator` (two-stage)
- `libs/execution/remediation.py` — new module: deterministic remediation table + spec mutation primitives
- `libs/execution/debug.py` — new module: LLM code patching (`debug_and_patch()`, error context assembly)
- `libs/verification/failure_memory.py` — exclude auto-remediated runs from penalty
- `configs/policies/default.yaml` — new `remediation` section
- `configs/models/routes.yaml` — new `debugger` model route for Stage 2 LLM calls
- `prompts/remediation/v1/debug_code.md` — prompt template for LLM code debugging
- `libs/schemas/domain.py` — `RemediationAction` schema with lineage

### Phase B
- `libs/verification/trend.py` — new module: metric series, direction classification, frontier
- `libs/verification/outcome.py` — extend with `DirectionalSignal`
- `libs/verification/checks.py` — `compare_to_baseline()` gains trend awareness
- `libs/verification/historical.py` — `compare_to_historical()` returns trend data
- `libs/verification/recommendations.py` — signal-driven recommendations
- `libs/schemas/domain.py` — `MetricFrontier`, directional signal fields on `VerificationReport`
- `libs/storage/models.py` — new columns/tables for frontier tracking

### Phase C
- `libs/orchestration/operators.py` — new `autonomous_loop_operator`
- `libs/orchestration/worker.py` — loop-aware scheduling
- `libs/ideation/services.py` — autonomous hypothesis lifecycle transitions
- `libs/schemas/domain.py` — `RunBudget`, extended `HypothesisCard` status values
- `libs/storage/models.py` — budget tracking columns on `ResearchCycle`
- `configs/policies/default.yaml` — `autonomy` section
- `prompts/` — overnight summary report template

### Phase D
- `libs/memory/` — new package: canonical patterns, consolidation, retrieval
- `libs/orchestration/operators.py` — `pattern_consolidation_operator`
- `libs/schemas/domain.py` — `CanonicalPattern`
- `libs/storage/models.py` — `CanonicalPatternModel`
- `libs/verification/failure_memory.py` — pattern-aware guidance
- `libs/ideation/services.py` — pattern-aware hypothesis generation

---

## 12. Open Questions

1. **Metric significance**: Should the significance threshold be absolute (0.005) or relative (0.5%)? Relative makes more sense across diverse metrics but is harder to configure.

2. **Multi-metric weighting**: When primary metric advances but a constraint is violated, how aggressive should the system be? Always pivot, or attempt to fix the constraint while maintaining the approach?

3. **Overnight summary format**: What does the human need to see in the morning? A ranked list of hypotheses with their status? A frontier chart? A diff of what changed?

4. **Pattern consolidation trigger**: Time-based (every N days), event-based (every N cycles), or on-demand? Event-based is more responsive but harder to predict.

5. **Skill extraction threshold**: At what confidence level should a canonical pattern become a procedural skill that's always applied? Too low risks bad automation; too high wastes knowledge.

6. **Hypothesis generation in the loop**: When the portfolio is stalled but not exhausted, should the system generate new hypotheses autonomously, or only pivot among existing ones? Generating new hypotheses mid-loop requires literature re-intake.
