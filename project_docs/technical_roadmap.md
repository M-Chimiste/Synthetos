# Technical Roadmap: Autonomous Learning & Experimental Signal

**Product:** ML Laboratory Co-Scientist
**Status:** Working Draft v1
**Last Updated:** 2026-03-24
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

### 2.1 The LLM wrote the code — it should fix the code

The LLM generates the experiment code. When that code fails, the natural feedback loop is sending the error back to the same model. Even "obvious" fixes benefit from LLM context: a regex sees `No module named torch` and installs `torch`; the LLM sees the same error, notices the CUDA dependency, and installs `torch==2.3.1+cu121`. For directional signal and verification outcomes, deterministic checks come first and the LLM interprets — but for code-level remediation, the LLM is always in the loop.

### 2.2 The interesting failure is a successful run with bad results

A missing dependency is a speed bump, not a research finding. A run that completes, produces valid metrics, and shows the hypothesis moving the wrong direction? That's the signal the co-scientist needs to reason about. The system should resolve mechanical failures quickly (with LLM help) so it can spend its real intelligence budget on interpreting experimental results.

### 2.3 Autonomy is the default, escalation is the exception

Inspired by autoresearch: *"do NOT pause to ask the human. The human might be asleep."* The co-scientist should have a clear autonomy policy that defines what it can do without asking. Human gates should exist only at genuine decision boundaries (portfolio exhausted, ambiguous multi-metric tradeoffs, success criteria met).

### 2.4 Memory has tiers with different lifetimes

Inspired by Hermes Agent's three-tier memory. Short-term context (current cycle), medium-term patterns (current charter), and long-term procedural knowledge (cross-charter canonical patterns) serve different purposes and decay at different rates.

### 2.5 Keep/discard is more useful than a taxonomy

Autoresearch's binary keep/discard on a single scalar is crude but decisive. Our system needs to handle multi-metric experiments, but the core question is the same: did this run advance the research goal or not? Everything else is detail.

### 2.6 Tools and context should be retrieved, not hardcoded

Inspired by TxAgent's ToolRAG pattern. As operator and skill counts grow, hardcoded pipelines break down. The system should embed operator/skill descriptions and retrieve the most relevant ones given the current research state — the same way the arXiv warehouse retrieves relevant papers. This applies to context assembly too: let the LLM help decide what prior evidence and patterns are relevant to the current step, rather than stuffing everything into a static context pack.

### 2.7 Criticize cheaply before verifying expensively

Inspired by Biomni's self-critic rounds. Before running the full deterministic verification pipeline (artifact checks, metric sanity, baseline comparison, historical comparison), run a fast LLM critic pass that catches obvious problems in the experimental setup or results. This is a lightweight pre-filter that saves compute on runs that would clearly fail verification — the critic can flag issues like "the model was only trained for 1 epoch" or "the reported accuracy is suspiciously close to random chance" before we spin up the full check suite.

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

**Goal:** Mechanical failures are resolved autonomously through LLM-assisted remediation. The system fixes its own mistakes, iterating on errors the way a developer would — reading the stack trace, understanding the context, and patching the code.

**Why first:** This is the highest-ROI change. The LLM writes the experiment code. When that code fails, the natural loop is feeding the error back to the same model for a fix. The current system generates an expensive postmortem for every failure, including trivial ones a developer would fix in 30 seconds. This phase replaces that with a tight remediation loop that resolves most failures without human intervention.

### A.1 LLM-Assisted Remediation

Every mechanical failure goes through the LLM. The difference is **how much context the LLM needs** and **what kind of fix it produces**. For well-understood failure classes, the LLM gets a focused prompt with strong priors (e.g., "this is a missing dependency — figure out which package and version to install"). For unknown failures, the LLM gets the full error context and more latitude.

**Known failure patterns — focused LLM call (cheap, fast):**

| Failure Class | Context Given to LLM | Expected Fix Type |
|---------------|---------------------|-------------------|
| `dependency_failure` | Stderr with import error, current requirements.txt, experiment spec | Package name + version pin to add to build recipe |
| `oom_or_resource_limit` | Model architecture from spec, batch size, dataset size, available profiles | Batch size reduction, gradient checkpointing, or profile step-up |
| `timeout` | Runtime duration, what phase was running (data load vs training), resource snapshot | Timeout extension, data loading optimization, or early stopping config |
| `metric_parse_failure` | Generated code's output section, expected metrics format from spec | Code patch to fix metrics serialization |
| `invalid_artifact_output` | Generated code's artifact writing section, expected output contract | Code patch to produce the declared artifacts |

These use a **focused prompt template** per failure class — the LLM isn't doing open-ended debugging, it's answering a specific question with strong constraints. This keeps the call cheap (~500 tokens out) and fast.

**Unknown failures — full debugging LLM call (more expensive, deeper):**

| Failure Class | Context Given to LLM | Expected Fix Type |
|---------------|---------------------|-------------------|
| `runtime_exception` | Full stderr/stack trace, generated code, experiment spec, prior remediation attempts | Code patch (unified diff) + explanation |
| Any failure after focused fix fails | All of the above, plus the focused fix that was tried and why it didn't work | Revised code patch informed by the failed attempt |

The full debugging call uses a **general debug prompt** that gives the LLM the complete picture. The LLM wrote the code — it should be able to read its own stack trace and fix it.

**Key design point:** The LLM is *always* in the loop, even for "obvious" fixes. A regex parser would see `No module named torch` and install `torch`. The LLM sees the same error but also understands that the experiment uses CUDA, so it installs `torch` with the right CUDA index URL and pins the version compatible with the other deps. The LLM's contextual understanding is what makes remediation actually work.

### A.2 Remediation Operator

New operator: `auto_remediate_operator`. Runs *before* the postmortem operator in the verification chain.

- Input: run record with failure classification, stderr, generated code, experiment spec, prior remediation lineage
- **Attempt 1 (focused):** If failure class is recognized, use the focused prompt template for that class. LLM returns a targeted fix (`run_mutations`, `spec_mutations`, code patch, or dependency/build recipe change). Apply fix, then enqueue `run_prepare` when spec-level restaging is required or `run_execute` when the existing workspace can be retried directly.
- **Attempt 2+ (escalated):** If the focused fix didn't resolve the failure, escalate to the full debug prompt with the prior attempt's context included. The LLM knows what was already tried.
- **Give up:** If max remediation attempts reached, or if the LLM returns a low-confidence fix, pass through to the existing postmortem operator for full structured analysis.

The operator maintains a **remediation conversation** — each attempt builds on the previous one, similar to a developer iterating on a fix. The LLM sees what it tried last time and why it didn't work.

### A.3 Fix Primitives

The LLM's output is parsed into one or more **fix actions** that the remediation operator applies.

**Run-level mutations (`run_mutations`):**
- `execution_profile` — switch to another configured profile when policy allows it
- `timeout_seconds` — increase retry execution budget
- `memory_limit_mb` / `cpu_limit` / `gpu_enabled` — bounded runtime overrides for the retrying run

**Spec-level mutations (`spec_mutations`):**
- `resource_requirements`
- `stop_conditions`
- `estimated_runtime_minutes`
- `gpu_required`

These require the harness to be restaged before retry so the updated values are written into `run_config.json`.

**Code patches:**
- `patch_code(workspace, full_file_contents)` — replaces the generated run script with corrected code

**Build recipe changes:**
- `dependency_adds` — appends Python packages to `build_recipe.pip_packages`
- On retry, the container bootstrap installs these packages before executing the experiment command
- System package installation and base image switching remain out of scope for this correction pass

**Lineage tracking:** Every fix is recorded in an append-only `remediation_actions` log and surfaced on run detail:

```
remediation_actions: [
  {
    attempt: 1,
    failure_class: "dependency_failure",
    prompt_type: "focused",
    model_route: "debugger",
    actions: [{type: "add_dependency", package: "torch", version: "2.3.1+cu121"}],
    explanation: "Added torch with CUDA 12.1 support to match the container's CUDA toolkit",
    confidence: 0.92
  },
  {
    attempt: 2,
    failure_class: "runtime_exception",
    prompt_type: "full_debug",
    model_route: "debugger",
    actions: [{type: "patch_code", summary: "Fixed tensor device mismatch in forward()"}],
    explanation: "Model weights were on CPU but input was on CUDA. Moved model.to(device) before training loop.",
    confidence: 0.88
  }
]
```

### A.4 Policy Controls

New policy section in `default.yaml`:

```yaml
remediation:
  enabled: true
  max_attempts_per_run: 3           # budget cap prevents infinite loops — no confidence gating
  allowed_fix_types:
    - add_dependency
    - reduce_batch_size
    - step_up_profile
    - extend_timeout
    - modify_hyperparameter
    - patch_code
    - add_system_package
  blocked_fix_types:               # never auto-apply these
    - change_base_image
  escalate_after_exhaustion: true   # fall through to postmortem when attempts exhausted
  model_route: debugger             # which model route handles remediation calls
```

### A.5 Changes to Existing Code

- `failure_postmortem_operator` gains a guard: skip if `auto_remediate_operator` already resolved the failure
- `get_hypothesis_failure_caution()` and `aggregate_failure_guidance()` should reason over postmortems directly; successful auto-remediation is excluded implicitly because resolved runs do not create postmortems
- Run detail includes remediation lineage so the operator trail is visible outside the database
- `classify_failure()` must detect dependency/import errors before falling back to generic `runtime_exception`

### A.6 Acceptance Criteria

- Dependency failure with "No module named torch" → focused LLM call installs torch with correct CUDA version, retry succeeds
- OOM → focused LLM call analyzes model size and data, recommends appropriate batch size (not just blind halving), retry succeeds
- Runtime exception with shape mismatch → full debug call reads the stack trace, patches the tensor operation, retry succeeds
- First focused fix doesn't resolve the issue → second attempt escalates with prior context, LLM adjusts approach
- All attempts exhausted → escalates to full postmortem operator with the entire remediation history attached
- Every fix the LLM produces is applied (no confidence gating) — the attempt budget is the safety valve
- Remediation lineage visible on run record showing every attempt, action, and explanation
- Auto-remediated runs excluded from hypothesis failure penalty

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
- Primary metric direction drives the keep/discard decision for clear-cut cases
- Constraint violations (latency > 100ms) are flagged regardless of primary metric direction
- **When metrics conflict (primary advancing but constraint violated):** the full metric picture is sent to the LLM (verifier route) which decides whether to continue refining the current approach or pivot. This avoids brittle rules for tradeoffs that require judgment — e.g., a 3% accuracy gain might justify a 10ms latency increase in one context but not another

### B.4 Significance Thresholds

Relative thresholds, defined per-problem in the charter or experiment spec. Different research problems have wildly different metric scales — a 0.5% delta is meaningful for ImageNet accuracy but noise for a loss function. The hypothesis and experimental design drive what counts as meaningful change.

```yaml
success_criteria:
  primary_metric: val_accuracy
  higher_is_better: true
  significance_threshold_pct: 0.5   # 0.5% relative change counts as meaningful
  stall_window: 3                   # 3 consecutive runs below threshold = stalled
  constraint_metrics:
    - name: inference_time_ms
      upper_bound: 100
    - name: model_size_mb
      upper_bound: 500
```

If no threshold is specified, the system defaults to a conservative relative threshold (1%) and logs a warning suggesting the researcher define one explicitly.

### B.5 Self-Critic Pre-Check (Biomni-inspired)

Before running the full deterministic verification pipeline, run a fast LLM critic pass. The critic receives the experiment spec, the run's metrics summary, and the generated code, and is prompted to identify obvious problems:

- "The model trained for only 1 epoch — results are not meaningful"
- "Reported accuracy of 0.51 on a binary task is indistinguishable from random"
- "The training loss is still decreasing at the final step — the model hasn't converged"
- "The evaluation was run on the training set, not the validation set"

The critic uses a **cheap, fast model route** (e.g., a smaller model or low max_tokens) because it's a pre-filter, not a deep analysis. Its output is a structured list of `{issue, severity, suggestion}`.

**How it integrates:**
- Runs *before* `verification_evaluator_operator`, not after
- If the critic finds `critical` severity issues: the run is marked `INVALID` immediately without running the full check suite, saving compute
- If the critic finds `warning` severity issues: they're attached to the verification report as `critic_warnings` for the LLM verifier to consider
- If the critic finds nothing: proceed to full verification as normal

This is deliberately lightweight — a single LLM call with a focused prompt, not a multi-step reasoning chain. The goal is to catch the 20% of problems that are obvious at a glance, not to replace the deterministic checks.

### B.6 Integration with Verification

- `verification_evaluator_operator` calls `classify_direction()` after existing checks
- Directional signal is stored on the `VerificationReport` (new field: `directional_signal`)
- `build_next_step_recommendations()` uses directional signal:
  - `advancing` → continue, maybe intensify
  - `stalled` → suggest parameter sweep or pivot
  - `regressing` → revert last change, try different approach
  - `noisy` → increase run count for statistical power
  - `breakthrough` → flag for human attention (good news worth reviewing)

### B.7 Frontier Tracking

New entity or extension to run records: **metric frontier** per charter + hypothesis line.

- Updated after each verified run
- Records: best value, which run achieved it, how many runs since last improvement
- "Runs since last improvement" is the key stall indicator
- Visible in the timeline UI as a frontier chart

### B.8 Acceptance Criteria

- 3 runs with <0.5% accuracy change → `stalled` signal, recommendation to pivot
- Run with 5% accuracy improvement over frontier → `breakthrough` signal
- Run where accuracy improves but latency exceeds constraint → LLM evaluates tradeoff and decides pivot or continue
- Noisy series (CV > 0.1 over 5 runs) → `noisy` signal, recommendation for more runs
- Self-critic catches "trained for 1 epoch" → run marked INVALID without full verification suite
- Self-critic warning "loss still decreasing" → attached to verification report, full checks still run

---

## 6. Phase C — Autonomous Experiment Loop

**Goal:** The co-scientist can run an unattended experiment sequence: pick hypothesis, run experiment, evaluate signal, pivot or continue, repeat — without human approval at each step.

**Why third:** Phases A and B give the system the ability to handle failures and interpret results. This phase uses those capabilities to close the loop.

### C.1 Autonomy Policy

Extend `configs/policies/default.yaml`:

```yaml
autonomy:
  mode: supervised          # supervised | autonomous
  auto_pivot_on_stall: true
  auto_pivot_on_regression: true
  auto_continue_on_advancing: true
  auto_regenerate_hypotheses: true  # trigger literature re-intake when portfolio stalls
  escalate_on_portfolio_exhausted: true  # only after re-generation also fails
```

Budget is set per-project by the user (on the charter or cycle), not in the global policy:

```yaml
# Example charter budget (set by user at project start)
budget:
  max_compute_hours: 8
  max_runs_per_hypothesis: 5
  max_total_runs: 50
  max_wall_clock_hours: 12
```

Two modes:

- **supervised** (current behavior): human approves each transition
- **autonomous**: system executes the full loop including hypothesis re-generation, escalates only on true portfolio exhaustion (after re-generation) or user-defined budget limits

### C.2 Loop Operator

New operator: `autonomous_loop_operator`. Replaces the current linear operator pipeline when autonomy mode is enabled.

```
while budget_remaining:
    hypothesis = pick_next_hypothesis(portfolio)

    if hypothesis is None:
        # Portfolio stalled — attempt re-generation before giving up
        if auto_regenerate_hypotheses and regeneration_budget_remaining:
            run_literature_intake_sub_loop()   # retrieve → synthesize → generate → rank
            continue                            # re-enter loop with refreshed portfolio
        else:
            escalate: "portfolio exhausted after re-generation"
            break

    spec = generate_or_reuse_experiment_spec(hypothesis)
    run = execute_run(spec)

    if run.failed:
        run = auto_remediate_and_retry(run)    # Phase A — LLM fixes the code

    if run.succeeded:
        signal = evaluate_directional_signal(run)  # Phase B

        match signal:
            case advancing:
                update_frontier(run)
                # continue with same hypothesis (maybe intensify)
            case stalled:
                if runs_on_this_hypothesis >= max_runs_per_hypothesis:
                    mark_hypothesis_stalled, pick next
                else:
                    suggest_parameter_variation, retry
            case regressing:
                mark_hypothesis_deprioritized, pick next
            case noisy:
                increase_run_count, retry for statistical power
            case breakthrough:
                update_frontier(run)
                # continue — breakthroughs don't interrupt the loop
            case conflicting_metrics:
                pivot_decision = ask_llm_to_evaluate_tradeoff(run)
                apply pivot_decision

generate_completion_report()  # full research report as ReportBundle
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

Budget is **defined by the user at project start**, not dynamically allocated by the system. The user declares how much compute and how many loops the co-scientist gets.

New fields on `ResearchCycle`:

- `budget_max_compute_minutes` — user-declared compute limit
- `budget_max_total_runs` — user-declared max experiment count
- `budget_max_wall_clock_hours` — user-declared time limit
- `budget_max_runs_per_hypothesis` — user-declared per-hypothesis cap
- `used_compute_minutes` — accumulated across all runs
- `used_run_count` — count of completed runs
- `runs_per_hypothesis` — dict of hypothesis_id → run count

Budget checks run before each experiment. When any limit is hit, the loop stops cleanly and generates the completion report.

### C.5 Per-Experiment Results Writeup

Every experiment produces a structured results writeup (not just metrics). This is the atomic unit of research documentation and feeds into both the completion report and long-term pattern learning.

Each writeup covers:
- **What was tried**: hypothesis, approach, key parameters
- **What happened**: metrics, directional signal, any remediations applied
- **Decision**: pivot to next hypothesis, double down with variation, or mark as promising
- **Rationale**: why this decision was made (LLM-generated, grounded in the metrics)

These writeups accumulate on the cycle and become the backbone of the completion report. They also provide the signal for measuring co-scientist effectiveness over time: what fraction of experiments produced positive signal vs negative signal? Is the system getting better at picking winners?

Stored as lightweight `ReportBundle` entries (type: `experiment_result`) linked to the run record.

### C.6 Embedding-Based Operator & Skill Retrieval (TxAgent-inspired)

As the system grows beyond the initial 15 skills, hardcoded operator pipelines become a bottleneck. The autonomous loop needs dynamic operator selection.

**OperatorRAG:** Embed all operator and skill descriptions using the same sentence-transformers infrastructure as the arXiv warehouse. At each step in the loop, retrieve the top-K most relevant operators/skills given the current research state (hypothesis, recent results, failure context).

**How it works:**
- Operator and skill manifests already have structured descriptions. Embed these at registration time.
- Before each loop iteration, assemble a query from the current state: active hypothesis title + latest metric summary + directional signal + any failure context
- Retrieve top-K operators/skills by cosine similarity
- The loop operator uses the retrieved set rather than a hardcoded pipeline

**Dynamic expansion (TxAgent meta-tool pattern):** The loop operator can request additional operators mid-execution. If the retrieved set doesn't include what's needed (e.g., the system encounters a new kind of failure it hasn't seen), it can explicitly query for more operators — similar to TxAgent's `Tool_RAG` meta-tool that lets the agent expand its own toolbox.

**Fallback:** When the operator count is small (< 20), the overhead of embedding retrieval isn't worth it. The system falls back to the existing hardcoded pipelines. OperatorRAG activates only when the registry exceeds a configured threshold.

### C.7 Context Summarization Under Pressure (TxAgent-inspired)

Long autonomous runs accumulate evidence, experiment results, and remediation history that can exceed context window limits. Rather than truncating or failing, the system compresses earlier context while preserving key findings.

**When it triggers:** The `ContextPack` token budget is exceeded during loop iteration.

**How it works:**
- Earlier evidence cards, experiment writeups, and remediation logs are summarized into condensed forms using a cheap LLM call
- Recent items (last N iterations) are preserved in full
- The summary retains: key metric values, directional signals, hypothesis status changes, and any patterns identified
- Similar to TxAgent's step-by-step summarization that replaces verbose tool outputs with single-sentence summaries

**What's preserved verbatim:**
- Current hypothesis and experiment spec (always full)
- Most recent 3 experiment writeups (full detail)
- Current metric frontier (always full)
- Active remediation lineage (full)

**What gets compressed:**
- Older experiment writeups → one-line summaries: "Hypothesis X, run 3: accuracy 0.82 → 0.84 (advancing)"
- Resolved remediation chains → "Fixed OOM via batch size reduction on run 2"
- Superseded evidence cards → summary of conclusions only

This ensures the autonomous loop can run for dozens of iterations without context degradation.

### C.8 Repetition Detection (TxAgent-inspired)

The autonomous loop must detect and break out of unproductive cycles. Without this, a stalled hypothesis could trigger the same experiment parameters repeatedly.

**Trace-level detection:** Track the last N operator invocations with their key arguments (hypothesis ID, experiment spec hash, parameter values). If the same combination appears twice, flag it as a loop and force a pivot or parameter variation.

**Result-level detection:** If 3 consecutive runs produce metrics within the noise threshold of each other (same hypothesis, same approach), the system recognizes stall even if parameters differ slightly and forces a more significant variation or pivot.

### C.9 Autonomous Mode & Completion Report

When `autonomy.mode == "autonomous"`:

- Breakthroughs are logged but don't interrupt the loop
- Stalled hypotheses are auto-pivoted without notification
- When the portfolio stalls, the system triggers hypothesis re-generation (literature re-intake → evidence synthesis → new hypotheses) before declaring exhaustion
- The loop runs until budget exhaustion or true portfolio exhaustion (no viable hypotheses remain even after re-generation)
- **On completion:** generate a full research report as a first-class `ReportBundle`. This is not a log dump — it's a structured report covering:
  - Which hypotheses were tried and in what order
  - Experimental results for each (metrics, frontier progression)
  - Which approaches showed promise and which were dead ends
  - The current metric frontier and best-performing configuration
  - Remediation actions taken and their outcomes
  - Recommendations for next steps (if any)
- The human reviews a research report, not individual run approvals

### C.10 Acceptance Criteria

- Autonomous mode: system runs 10+ experiments across 3+ hypotheses without human input
- Auto-pivot: hypothesis stalls after 3 runs → system picks next ranked hypothesis and continues
- Budget enforcement: loop stops at compute hour limit with clean summary
- Portfolio exhaustion: all hypotheses stalled/regressing → system stops and requests new literature intake
- Repetition detection: same experiment spec run twice → system forces parameter variation or pivot
- Context summarization: loop runs 20+ iterations without context overflow or truncation
- OperatorRAG (when skill count > 20): system retrieves relevant operators dynamically, not from hardcoded pipeline

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
  polarity: str               # "positive" (do this) | "negative" (don't do this)
  title: str                  # "OOM on large tabular datasets with default batch size"
  description: str            # 2-3 sentence abstract
  trigger_conditions: list    # When does this pattern apply?
  proven_actions: list        # What worked? [{action, success_rate, evidence_count}]
  disproven_actions: list     # What didn't work? [{action, failure_rate, evidence_count}]
  evidence_refs: list         # Links to source postmortems/runs across charters
  evidence_count: int         # Total observations supporting this pattern
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

Canonical patterns are extracted at **any confidence threshold** — the system learns from both successes and failures. Negative patterns ("data augmentation on tabular data consistently hurts performance") are as valuable as positive ones, specifically to prevent the system from repeating failed approaches.

Pattern types and how they're applied:

- **Positive patterns** (proven actions): injected as suggestions into hypothesis generation and experiment design. "Learning rate warmup improves transformer fine-tuning convergence" → the hypothesis generator considers warmup when proposing transformer experiments.
- **Negative patterns** (disproven actions): injected as warnings. "Random rotation augmentation degrades tabular model accuracy" → the hypothesis generator avoids this approach or explicitly justifies diverging from the pattern.
- **Failure remediation patterns**: fed into the auto-remediation operator as prior knowledge. "CUDA OOM on models >500M params with batch size >32 on A100" → the remediation operator starts with a smaller batch size instead of discovering this through trial and error.

This bridges Hermes Agent's "skill files as procedural memory" concept into our operator architecture. The key difference from Hermes: we extract patterns from both success *and* failure trajectories, not just successful complex tasks.

### D.7 Acceptance Criteria

- After 20+ runs across 3+ charters: both positive and negative patterns auto-generated
- Negative pattern ("X consistently fails in context Y") prevents the hypothesis generator from proposing X in similar contexts
- Positive pattern ("reduce batch size on OOM") is applied by auto-remediation without rediscovering it each time
- Pattern staleness decay triggers when environment context changes (e.g., framework version bump)
- Consolidation runs on configured time interval without manual triggering
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
| `CriticFinding` | B | Self-critic pre-check issue (severity, suggestion) |
| `MetricFrontier` | B | Best-so-far tracker per charter + hypothesis line |
| `DirectionalSignal` | B | Enum: advancing/stalled/regressing/noisy/breakthrough |
| `RunBudget` | C | Compute/run budget tracking per cycle |
| `OperatorEmbedding` | C | Embedded operator/skill descriptions for retrieval |
| `ContextSummary` | C | Compressed earlier context for long-running loops |
| `CanonicalPattern` | D | Cross-charter distilled knowledge |

---

## 10. Policy Changes Summary

| Policy Key | Phase | Purpose |
|------------|-------|---------|
| `remediation.enabled` | A | Toggle auto-remediation |
| `remediation.allowed_fix_types` | A | Which auto-fixes are permitted |
| `remediation.max_attempts_per_run` | A | Cap per-run fix attempts (the only safety valve — no confidence gating) |
| `remediation.model_route` | A | Which model route handles remediation LLM calls |
| Charter `success_criteria.significance_threshold_pct` | B | Relative minimum delta to count as meaningful (per-problem) |
| Charter `success_criteria.stall_window` | B | Consecutive below-threshold runs to declare stall (per-problem) |
| `autonomy.mode` | C | supervised / autonomous |
| `autonomy.auto_pivot_on_stall` | C | Auto-switch hypothesis on stall |
| `autonomy.auto_regenerate_hypotheses` | C | Trigger literature re-intake when portfolio stalls |
| Charter `budget.*` | C | User-defined compute hours, run counts, wall clock hours (per-project) |
| `memory.consolidation_interval_hours` | D | Time-based trigger for pattern consolidation |
| `memory.staleness_decay_rate` | D | Monthly decay multiplier for stale patterns |

---

## 11. Files Likely Affected

### Phase A
- `libs/execution/artifacts.py` — `classify_failure()` unchanged, provides routing to correct prompt
- `libs/orchestration/operators.py` — new `auto_remediate_operator`
- `libs/execution/remediation.py` — new module: fix primitives (spec mutations, code patching, build recipe changes)
- `libs/execution/debug.py` — new module: LLM remediation calls (context assembly, response parsing, confidence evaluation)
- `libs/verification/failure_memory.py` — exclude auto-remediated runs from penalty
- `configs/policies/default.yaml` — new `remediation` section
- `configs/models/routes.yaml` — new `debugger` model route
- `prompts/remediation/v1/` — focused prompt templates per failure class + general debug prompt
- `libs/schemas/domain.py` — `RemediationAction` schema with lineage

### Phase B
- `libs/verification/trend.py` — new module: metric series, direction classification, frontier
- `libs/verification/critic.py` — new module: self-critic pre-check (Biomni-inspired)
- `libs/verification/outcome.py` — extend with `DirectionalSignal`
- `libs/verification/checks.py` — `compare_to_baseline()` gains trend awareness
- `libs/verification/historical.py` — `compare_to_historical()` returns trend data
- `libs/verification/recommendations.py` — signal-driven recommendations
- `libs/schemas/domain.py` — `MetricFrontier`, `CriticFinding`, directional signal fields on `VerificationReport`
- `libs/storage/models.py` — new columns/tables for frontier tracking, critic warnings on verification reports
- `prompts/verification/v1/self_critic.md` — focused critic prompt template
- `configs/models/routes.yaml` — `critic` model route (cheap/fast model)

### Phase C
- `libs/orchestration/operators.py` — new `autonomous_loop_operator`
- `libs/orchestration/worker.py` — loop-aware scheduling
- `libs/orchestration/operator_rag.py` — new module: embedding-based operator/skill retrieval (TxAgent-inspired)
- `libs/orchestration/context_summarizer.py` — new module: context compression for long-running loops (TxAgent-inspired)
- `libs/orchestration/loop_guard.py` — new module: repetition detection at trace and result level
- `libs/ideation/services.py` — autonomous hypothesis lifecycle transitions
- `libs/schemas/domain.py` — `RunBudget`, `OperatorEmbedding`, `ContextSummary`, extended `HypothesisCard` status values
- `libs/storage/models.py` — budget tracking columns on `ResearchCycle`, operator embedding cache
- `libs/reporting/` — per-experiment results writeup generation, completion report template
- `configs/policies/default.yaml` — `autonomy` section
- `prompts/reporting/v1/experiment_result.md` — per-experiment writeup template
- `prompts/reporting/v1/completion_report.md` — full research completion report template
- `prompts/orchestration/v1/context_summary.md` — prompt for compressing earlier context

### Phase D
- `libs/memory/` — new package: canonical patterns, consolidation, retrieval
- `libs/orchestration/operators.py` — `pattern_consolidation_operator`
- `libs/schemas/domain.py` — `CanonicalPattern`
- `libs/storage/models.py` — `CanonicalPatternModel`
- `libs/verification/failure_memory.py` — pattern-aware guidance
- `libs/ideation/services.py` — pattern-aware hypothesis generation

---

## 12. Resolved Design Decisions

1. **Metric significance**: Relative thresholds, not absolute. The threshold is defined per-problem in the charter's `success_criteria` or the experiment spec's declared metrics. Different research problems have wildly different scales — 0.5% is meaningful for ImageNet accuracy but noise for a loss function. The hypothesis and experimental design drive the threshold, not a global default.

2. **Multi-metric weighting**: The LLM decides when to pivot. When primary metric advances but a constraint is violated, the directional signal evaluation sends the full metric picture to the LLM (verifier route) and asks: "given this tradeoff, should the system continue refining this approach or pivot?" This avoids brittle rules for situations that require judgment.

3. **Completion summary format**: Not "overnight" specifically — the summary is generated when the agent reaches its configured time/budget limit for a research project. The output is a **full research report**: what hypotheses were tried, experimental results for each, which approaches showed promise, which were dead ends, and the current frontier. This is a first-class `ReportBundle` with a dedicated template, not a log dump.

4. **Pattern consolidation trigger**: Time-based, configured at research project start. The interval is set in the charter or policy (e.g., `memory.consolidation_interval_hours: 24`). Simpler than event-based, predictable, and avoids consolidation storms after bursts of activity.

5. **Skill extraction threshold**: Any threshold — both positive and negative results are extracted as patterns. A pattern that says "learning rate warmup helps transformer fine-tuning" is valuable. A pattern that says "data augmentation on tabular data consistently hurts performance" is equally valuable. The system should learn what *not* to try as much as what *to* try, specifically to avoid repeating failed approaches.

6. **Hypothesis generation in the loop**: Yes, the system generates new hypotheses autonomously. When the existing portfolio stalls, the loop triggers literature re-intake and hypothesis generation before declaring portfolio exhaustion. This is a full sub-loop (retrieve → synthesize evidence → generate hypotheses → rank → continue), not just a shuffle of existing hypotheses.

7. **Remediation confidence calibration**: Just try it. The cost of a failed fix attempt is a few minutes of compute. The cost of *not* trying (escalating to a postmortem, possibly waiting for a human) is much higher. The `max_attempts_per_run` budget cap prevents infinite loops. No confidence threshold gating — if the LLM produces a fix, apply it. Revisit if empirical data shows the system wasting significant compute on bad patches.

---

## 13. Resolved Design Decisions (continued)

8. **Budget allocation**: Defined upfront by the user at project start. The user sets both the total number of experiment loops and compute limits (hours, runs). The system doesn't need to dynamically split budget between hypothesis re-generation and experiments — it operates within the user's declared budget and stops when it's spent.

9. **Negative pattern representation**: Negative patterns are simply negative experimental results — "I tried X and the metrics got worse / didn't improve." No special constraint mechanism needed. They're stored the same way as positive patterns, just with negative signal. When the hypothesis generator sees prior evidence that approach X degraded metrics in a similar context, it factors that into its ranking naturally.

10. **Pivot decision quality tracking**: Per-experiment results writeups. Every experiment produces a structured report discussing: what was tried, what happened, and the decision to pivot or double down. Over time, the system's effectiveness is measured by the ratio of positive-signal experiments to negative-signal experiments — are we getting better at picking hypotheses that work? This is a reportable metric, not a runtime gate.

---

## 14. External Influences

Patterns adopted from research into existing agent systems:

| Pattern | Source | Where Applied | What We Took |
|---------|--------|--------------|--------------|
| Three-tier memory (declarative, procedural, dialectic) | [Hermes Agent](https://github.com/NousResearch/hermes-agent) | Phase D | Memory architecture with different lifetimes. Skill extraction from experience. Background consolidation nudges. |
| Binary keep/discard on single metric, fully autonomous loop | [autoresearch](https://github.com/karpathy/autoresearch) | Phase B, C | Decisiveness over deliberation. No human approval gates during the loop. Budget as the only safety valve. |
| Embedding-based tool retrieval (ToolRAG) | [TxAgent](https://github.com/mims-harvard/TxAgent) | Phase C | Dynamic operator/skill selection via embedding similarity instead of hardcoded pipelines. Meta-tool pattern for requesting more capabilities mid-execution. |
| Token-overflow-triggered context summarization | [TxAgent](https://github.com/mims-harvard/TxAgent) | Phase C | Compress earlier evidence and results under pressure rather than truncating or failing. Step-by-step summarization preserving reasoning structure. |
| Repetition detection (trace-level and token-level) | [TxAgent](https://github.com/mims-harvard/TxAgent) | Phase C | Prevent autonomous loops from repeating identical experiments. Force variation or pivot when loops are detected. |
| Hierarchical sub-agent spawning with depth limits | [TxAgent](https://github.com/mims-harvard/TxAgent) | Phase C | Bounded recursion for hypothesis re-generation sub-loops within the main autonomous loop. |
| Force-finish resilience | [TxAgent](https://github.com/mims-harvard/TxAgent) | Phase C | Always produce a completion report even when the loop terminates abnormally. |
| Self-critic feedback rounds | [Biomni](https://github.com/snap-stanford/Biomni) | Phase B | Cheap LLM pre-check before expensive verification pipeline. Catch obvious problems at a glance. |
| LLM-as-resource-router | [Biomni](https://github.com/snap-stanford/Biomni) | Phase C | Let the LLM help select relevant context (evidence, patterns, tools) for the current step, rather than static context packs. |
| Two-layer tool definitions (implementation + schema) | [Biomni](https://github.com/snap-stanford/Biomni) | Existing | Validates our existing pattern of adapter interfaces + skill manifests. |
| Know-how document injection | [Biomni](https://github.com/snap-stanford/Biomni) | Phase D | Canonical patterns injected into operator prompts as domain expertise — same pattern as Biomni's protocol documents in system prompts. |

**What we deliberately did NOT adopt:**
- TxAgent's lack of formal verification (we keep our deterministic verification pipeline)
- TxAgent's monolithic agent class (we keep hexagonal architecture)
- Biomni's `exec()`-based code execution without sandboxing (we keep containerized execution)
- Biomni's flat generate-execute loop without state machine (we keep typed `ResearchState` with transitions)
- Hermes Agent's reliance on implicit success/failure signals (we keep explicit directional signal evaluation)

---

## 15. Open Questions

None currently. All design decisions resolved. Ready for detailed implementation planning.
