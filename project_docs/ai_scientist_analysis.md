# Analysis: SakanaAI/AI-Scientist — Lessons for Synthetos

**Document Type:** External System Analysis
**Status:** Complete
**Date:** 2026-03-27
**Repository Analyzed:** [SakanaAI/AI-Scientist](https://github.com/SakanaAI/AI-Scientist)
**Purpose:** Identify patterns, components, and insights from AI-Scientist that can strengthen the Synthetos co-scientist system.

---

## 1. Overview of AI-Scientist

AI-Scientist is an automated research pipeline that enables LLMs to independently generate research ideas, execute experiments, write papers, and review results. It was published by Sakana AI and represents one of the first end-to-end autonomous science systems.

### Pipeline Stages

```
seed_ideas.json + prompt.json + experiment.py
    → generate_ideas()        → ideas.json
    → check_idea_novelty()    → ideas.json (with "novel" field)
    → [filter novel ideas]
    → per idea:
        → perform_experiments()   → final_info.json, plots
        → perform_writeup()       → paper PDF via LaTeX
        → perform_review()        → structured review JSON
        → perform_improvement()   → revised paper (optional)
```

### Repository Structure

```
ai_scientist/
    llm.py                  — LLM abstraction layer (multi-provider)
    generate_ideas.py       — Idea generation + novelty checking
    perform_experiments.py  — Experiment execution via Aider
    perform_writeup.py      — Section-by-section LaTeX paper writing
    perform_review.py       — NeurIPS-style ensemble review
    fewshot_examples/       — Real paper/review pairs for few-shot prompting
templates/
    nanoGPT/                — Self-contained experiment template
    2d_diffusion/           — Diffusion model template
    grokking/               — Generalization dynamics template
    (+ 8 community templates)
launch_scientist.py         — Main orchestrator
experimental/               — Dockerfile, open-ended variant
review_iclr_bench/          — Reviewer benchmarking against real ICLR reviews
```

### Supported Models

Claude (direct, Bedrock, Vertex AI), GPT-4o/4.1/o1/o3, DeepSeek (chat, coder, reasoner), Gemini, Llama 3.1 405B (via OpenRouter).

---

## 2. Patterns Worth Adopting

### 2.1 Reflection Loops with Early Termination

**What AI-Scientist does:** A consistent pattern used in idea generation, novelty checking, and review. The LLM engages in multi-turn self-critique (up to N rounds), refining its output each round. The loop terminates early when the LLM includes the phrase "I am done" in its response.

**Where it appears:**
- `generate_ideas.py`: `num_reflections=5` rounds of idea refinement
- `check_idea_novelty()`: Up to 10 rounds of search-evaluate-decide
- `perform_review.py`: Review self-correction rounds

**Recommendation for Synthetos:** Formalize this as a core operator primitive. Any operator involving LLM reasoning (hypothesis generation, evidence synthesis, verification narrative) should support:
- Configurable max reflection rounds (per operator, via config)
- Early termination detection (structured signal, not string matching)
- Append-only conversation history within the reflection loop
- Reflection metadata recorded in operator reports (rounds used, convergence signal)

This pattern maps naturally to the operator contract: each reflection round is a sub-step within the operator's execution, with the shared `ResearchState` updated only after convergence.

### 2.2 Ensemble Review with Meta-Aggregation

**What AI-Scientist does:** The review module generates N independent reviews (default 5) at temperature 0.75 for diversity. Numerical scores are averaged across valid reviews. A separate "Area Chair" meta-reviewer synthesizes qualitative consensus. If the meta-review fails, the first valid individual review serves as fallback.

**Additional insight — bias-controlled prompts:** Two reviewer system prompts exist:
- `reviewer_system_prompt_neg` (default): "If the submission is bad or mediocre or you are unsure, give a low score and reject."
- `reviewer_system_prompt_pos`: "If the submission is good or you are unsure, give a high score and accept."

The negative-bias default counteracts known LLM leniency in evaluation tasks.

**Recommendation for Synthetos:** Apply this to the Verify loop:
- Ensemble verification with configurable reviewer count in `configs/policies/`
- Meta-aggregation as a separate operator (or sub-operator) producing the `VerificationReport`
- Bias direction as a policy parameter (negative-bias default for experiment verification, configurable per research charter)
- Score averaging with outlier filtering and confidence intervals
- Graceful degradation: if meta-review fails, fall back to best individual review

### 2.3 Iterative Literature Search (Search-Inject-Decide Loop)

**What AI-Scientist does:** `check_idea_novelty()` runs up to 10 rounds where:
1. The LLM proposes search queries based on the idea
2. Semantic Scholar or OpenAlex returns top-10 results (title, authors, venue, year, abstract, citation count)
3. Results are injected into the conversation
4. The LLM evaluates and either proposes refined queries or declares a decision

The same pattern is reused in the writeup stage for citation discovery (up to 20 rounds).

**Recommendation for Synthetos:** Adapt this for the Explore loop's literature triage, but with Synthetos's metadata-first discipline:
- Round 1-N: search and screen on title + abstract only (metadata-first)
- Escalation to full text requires the LLM to provide explicit justification
- Each round's queries and decisions are recorded as `DomainEvent`s
- The search backend should be wrapped behind `adapters/corpus/` supporting both Semantic Scholar and OpenAlex
- Token budget enforcement via `ContextPack` prevents unbounded context growth (a specific weakness in AI-Scientist)

### 2.4 Few-Shot Exemplars for Review Quality Grounding

**What AI-Scientist does:** The review module loads 3 real paper/review pairs from `fewshot_examples/`:
- Papers stored as `.pdf` and pre-extracted `.txt`
- Reviews stored as `.json` matching the exact output schema expected from the LLM
- Examples include substantive critiques (ablation study gaps, visualization coverage), not just surface-level comments

This is the only module in AI-Scientist that uses few-shot prompting, and it produces the highest-quality structured output.

**Recommendation for Synthetos:** Create a `fixtures/review_exemplars/` directory:
- For Kaggle MVP: exemplary competition write-ups with structured critiques
- For general ML: adapted from real conference reviews (with appropriate licensing)
- Exemplars should match the `VerificationReport` schema exactly
- Store as versioned assets alongside prompts in `prompts/verification/`
- Key insight: **real examples beat instruction-only prompts** for calibrating evaluation quality

### 2.5 Template-Based Experiment Structure

**What AI-Scientist does:** Each experiment type is a self-contained directory:
```
templates/nanoGPT/
    experiment.py       — The modifiable code (single file, ~500-700 lines)
    plot.py             — Visualization script
    prompt.json         — System prompt + task description
    seed_ideas.json     — 2-3 calibration ideas
    latex/template.tex  — Paper template
    run_0/              — Pre-computed baseline results
```

The LLM modifies `experiment.py` within this fixed structure. The constraint that experiments must be expressible as modifications to a single known file keeps LLM edits tractable.

**Recommendation for Synthetos:** Define a standard template structure for Kaggle competitions:
```
templates/kaggle_tabular/
    train.py            — Training pipeline
    predict.py          — Inference pipeline
    evaluate.py         — Local evaluation
    config.yaml         — Hyperparameters and data paths
    baseline/           — Pre-computed baseline metrics
```

Templates should be registered in `configs/execution/templates/` and discoverable by the orchestrator. The `ExperimentSpec` should reference which template was used and what modifications were applied.

### 2.6 Aider as a Code-Editing Backbone

**What AI-Scientist does:** Instead of generating entire files, AI-Scientist uses the [Aider](https://github.com/paul-gauthier/aider) library's `Coder` class with `edit_format="diff"`. The LLM proposes SEARCH/REPLACE blocks applied to existing code. This:
- Reduces hallucination (the LLM works with existing code, not blank slate)
- Preserves working code structure
- Enables targeted modifications rather than full rewrites
- Provides built-in git integration (though AI-Scientist disables it with `use_git=False`)

**Recommendation for Synthetos:** Consider Aider (or a similar diff-based editing approach) as an adapter behind the hexagonal interface:
```
adapters/coder/
    interface.py        — CoderPort defining edit_file(), run_and_feedback()
    aider_adapter.py    — Aider-backed implementation
    direct_adapter.py   — Direct LLM code generation (fallback)
```

This preserves architectural cleanliness while leveraging a proven tool. The adapter interface allows swapping Aider for alternatives (or a custom implementation) without changing the Experiment loop operators.

---

## 3. Patterns to Avoid

### 3.1 No Sandboxing — Experiments Run Directly on Host

AI-Scientist executes experiments via `subprocess.run("python experiment.py")` with no containerization, no resource limits beyond a 2-hour timeout, and no network isolation. The README explicitly warns users to implement their own containerization.

**Synthetos already addresses this:** Docker + NVIDIA Container Toolkit with network-disabled containers, read-only dataset mounts, enforced resource limits, and per-run git worktree isolation.

### 3.2 File System as Sole State Mechanism

State in AI-Scientist is scattered JSON files (`ideas.json`, `final_info.json`, `notes.txt`, `review.txt`) across directories. There is no database, no typed schemas, no event log, no transactional guarantees, and no audit trail.

**Synthetos already addresses this:** PostgreSQL + pgvector for persistent state, typed Pydantic schemas at all boundaries, append-only `DomainEvent` log, and `ResearchState` as the single source of truth.

### 3.3 Inline Prompt Strings with No Versioning

All prompts in AI-Scientist are Python f-string constants embedded in source code. There is no external template system, no versioning, no checksumming, and no A/B testing capability. Changing a prompt requires changing Python code.

**Synthetos already addresses this:** Versioned prompt assets under `prompts/`, with every model call recording prompt ID, version/checksum, and model route.

### 3.4 Hardcoded Model Routing via if/elif Chains

`llm.py` contains ~200 lines of `if "claude" in model: ... elif "gpt" in model: ...` with largely duplicated logic per provider. Adding a new provider requires editing this chain.

**Synthetos already addresses this:** Config-driven YAML model routing with role-based selection (planner, triage, synthesizer, critic, coder, verifier, reporter).

### 3.5 No Evidence-Before-Hypothesis Discipline

AI-Scientist generates ideas directly from the experiment template code. There is no prior literature review, no evidence synthesis, and no hypothesis ranking before jumping to ideas. The novelty check happens *after* idea generation, not before.

**Synthetos already addresses this:** The Explore → Experiment → Verify pipeline enforces evidence-before-hypothesis-before-code as an architectural invariant.

### 3.6 Unbounded Context Growth

All previously generated ideas are dumped as a serialized JSON string into the next idea generation prompt. With many ideas, this silently approaches or exceeds context limits. There is no token counting or budget management anywhere in the codebase.

**Synthetos already addresses this:** Task-scoped `ContextPack` with explicit token budgets, allowed sources, and deterministic ordering.

### 3.7 No Failure Memory

When an experiment fails in AI-Scientist, it is logged and abandoned. There is no structured postmortem, no feeding failure information back into hypothesis ranking, and no learning from past failures.

**Synthetos already addresses this:** `FailurePostmortem` records feed back into retrieval and ranking via the Verify loop.

### 3.8 Review Hardcoded to a Single Model

AI-Scientist hardcodes the review stage to GPT-4o (`openai.OpenAI()`) regardless of the `--model` argument. This creates a hidden dependency on an OpenAI API key even when using Claude for everything else.

**Synthetos should avoid this:** The model routing system should allow role-based model selection for verification, configurable per research charter.

---

## 4. Extractable Components

| AI-Scientist Component | What to Extract | Target Location in Synthetos |
|---|---|---|
| `search_for_papers()` with Semantic Scholar + OpenAlex | Dual-API literature search with exponential backoff | `adapters/corpus/semantic_scholar.py`, `adapters/corpus/openalex.py` |
| `extract_json_between_markers()` | Robust JSON extraction from LLM output with fallback chain | `libs/core/llm_output.py` |
| Reflection loop pattern | Multi-turn LLM critique with configurable rounds and early termination | Core operator mixin or base class in `libs/core/` |
| Ensemble + meta-review | N independent reviews → score averaging → meta-aggregation | `libs/verification/ensemble.py` |
| NeurIPS review form structure | Detailed rubric with per-dimension scoring (1-4 and 1-10 scales) | Adapt for `VerificationReport` schema in `libs/schemas/` |
| Per-section writing tips | Domain-specific structured guidance for report generation | `configs/reporting/section_tips.yaml` |
| Bias-controlled reviewer prompts | Negative-bias default for calibrated evaluation | `prompts/verification/` with bias parameter |
| Template experiment structure | Standardized experiment directory layout with baseline | `configs/execution/templates/` |
| Few-shot review exemplars | Real paper/review pairs for grounding LLM evaluation quality | `fixtures/review_exemplars/` |
| Aider diff-based code editing | SEARCH/REPLACE editing of experiment code via LLM | `adapters/coder/aider_adapter.py` |

---

## 5. Architectural Comparison

| Dimension | AI-Scientist | Synthetos (Planned) | Assessment |
|---|---|---|---|
| **State management** | File system (JSON, txt, tex) | PostgreSQL + pgvector, typed Pydantic schemas | Synthetos far stronger |
| **Orchestration** | Sequential function calls in `do_idea()` | State machine with explicit transitions, append-only events | Synthetos far stronger |
| **LLM abstraction** | if/elif chain per provider | Config-driven YAML routing with role-based selection | Synthetos far stronger |
| **Prompt management** | Inline Python f-strings | Versioned file assets with ID, checksum, model route | Synthetos far stronger |
| **Execution isolation** | `subprocess.run()` on host | Docker + NVIDIA Container Toolkit, network disabled | Synthetos far stronger |
| **Literature triage** | Post-hoc novelty check only | Metadata-first screening pipeline in Explore loop | Synthetos far stronger |
| **Failure handling** | Log and abandon | Structured `FailurePostmortem`, feedback into ranking | Synthetos far stronger |
| **Context management** | Unbounded prompt growth | Token-budgeted `ContextPack` per operator | Synthetos far stronger |
| **Reflection loops** | Effective but ad-hoc per module | Not yet implemented — adopt and formalize | Adopt from AI-Scientist |
| **Ensemble verification** | Sophisticated (5-review + meta-review) | Not yet implemented — adopt and formalize | Adopt from AI-Scientist |
| **Few-shot exemplars** | Used for review quality grounding | Not yet planned — add to verification | Adopt from AI-Scientist |
| **Code editing approach** | Aider diff-based editing | Not yet decided | Consider adopting Aider adapter |
| **Paper/report writing** | Section-by-section with per-section tips | Planned but not detailed | Learn from AI-Scientist's structure |

---

## 6. Strategic Takeaways

1. **AI-Scientist validates the end-to-end concept.** Autonomous idea → experiment → paper → review is feasible with current LLMs. The system has produced papers that, while imperfect, demonstrate the full loop is tractable. This is encouraging for Synthetos's more ambitious architecture.

2. **Synthetos's architecture is fundamentally stronger in every structural dimension.** Typed state, operator contracts, hexagonal adapters, containerized execution, failure memory, and evidence-first workflow are all superior to AI-Scientist's approach. The AI-Scientist validates *what* to build; Synthetos already has a better plan for *how*.

3. **The biggest concrete borrowings should be:**
   - Reflection loop pattern (formalized as an operator primitive)
   - Ensemble verification with bias control and meta-aggregation
   - Semantic Scholar + OpenAlex dual-search behind the corpus adapter
   - Few-shot exemplars for grounding verification quality
   - Template-based experiment structure with baselines
   - Aider as a code-editing adapter option

4. **Do not borrow:** The inline prompt pattern, file-system-only state, if/elif model routing, unsandboxed execution, or post-hoc-only novelty checking. These are all explicitly solved better in Synthetos's existing design.

5. **Cost reference point:** AI-Scientist reports that generating a complete paper costs less than $15 using Claude Sonnet 3.5. This provides a useful baseline for Synthetos's cost estimation, though the additional rigor of evidence-first workflow and ensemble verification will increase per-cycle cost.

6. **The Aider dependency is a double-edged sword.** It is a powerful and proven tool for LLM-driven code editing, but it is a significant external dependency. Wrapping it behind a hexagonal adapter interface mitigates the coupling risk while preserving the capability.

---

## 7. Recommended Actions

### Immediate (Phase 0-1)
- [ ] Add `extract_json_between_markers()` equivalent to `libs/core/` as a utility for all operator output parsing
- [ ] Design the reflection loop as a core operator primitive with configurable rounds and structured termination
- [ ] Implement Semantic Scholar and OpenAlex adapters behind `adapters/corpus/` interface

### Near-term (Phase 2-3)
- [ ] Implement ensemble verification with bias-controlled prompts and meta-aggregation
- [ ] Create few-shot review exemplar fixtures for the Kaggle MVP domain
- [ ] Define Kaggle competition experiment templates with baseline structure
- [ ] Evaluate Aider integration as an adapter for the Experiment loop's code generation phase

### Later (Phase 4-5)
- [ ] Benchmark Synthetos verification quality against AI-Scientist's review output
- [ ] Explore open-ended idea generation mode (AI-Scientist's `launch_oe_scientist.py` variant) where review scores feed back into hypothesis ranking
- [ ] Consider section-by-section report writing with per-section tips for the Reporting subsystem
