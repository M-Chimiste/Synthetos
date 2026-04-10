# Product Requirements Document

**Product:** Synthetos (ML Laboratory Co-Scientist)  
**Role:** Product Manager  
**Status:** Working Draft v4  
**Scope:** Local small-scale ML laboratory with autonomy roadmap  
**Last Updated:** 2026-04-09

---

## 1. Purpose

This document revises the PRD for the ML Laboratory Co-Scientist based on the current product documents, the technical roadmap, and lessons pulled from the Paper Circle research discovery framework.

It answers six questions:

1. What problem are we solving?
2. What does the first product actually do?
3. What new product requirements should be added from the autonomy roadmap?
4. What literature discovery and paper analysis capabilities should become first-class product surfaces?
5. What requirements must the system satisfy to be useful, trustworthy, and inspectable?
6. What remains explicitly out of scope for the first release?

This PRD is the source document for `system_patterns.md`, `phased_implementation_plan.md`, and `tech_context.md`.

---

## 2. Executive Summary

The ML Laboratory Co-Scientist is a local-first research system for machine learning work.  It is designed to help a researcher move from a scoped research problem to evidence-grounded experiments, verified results, reusable memory, and human-readable reports.

The revised product now has four first-class surfaces:

1. **Discovery Pipeline** for multi-source literature discovery, metadata-first triage, structured ranking, and reproducible retrieval artifacts.
2. **Paper Analysis Pipeline** for deep paper understanding through structured extraction, typed paper graphs, graph-aware question answering, and coverage checks.
3. **Experiment and Verification Pipeline** for evidence-backed hypothesis generation, executable experiment specs, isolated runs, deterministic verification, and failure memory.
4. **Autonomy Layer** for LLM-assisted auto-remediation, directional signal tracking, budgeted unattended experimentation, and cross-charter procedural memory.

The first release remains a bounded ML laboratory, not a generalized science platform and not a literature-only workbench.  However, the literature side is now much stronger than in the prior PRD.  The system should not only retrieve papers, it should maintain an explicit discovery state, produce synchronized exports, support structured paper analysis, and let users interrogate a paper or paper set with provenance-aware answers.

The product should still feel like a research control tower with bounded autonomy, not a black-box agent swarm.

---

## 3. Problem Statement

Autonomous experimentation is only one slice of research.  Before an experiment is worth running, a researcher usually needs to:

- frame the problem clearly
- understand prior internal work
- inspect recent external literature
- decide which papers deserve deeper reading
- extract methods, evidence, and caveats from those papers
- compare claims to reproducibility signals and missing details
- translate ideas into valid, testable protocols
- run experiments in isolated environments
- interpret whether results are actually advancing the research line
- retain both failures and useful patterns so the next attempt is better

Today those steps are fragmented across notebooks, papers, internal notes, experiment logs, terminal sessions, ad hoc agent prompts, and disconnected search tools.

The result is predictable:

- literature review is expensive and inconsistent
- deep paper understanding is bottlenecked on manual reading
- experiment failures are over-escalated or forgotten
- agents over-read, over-generate, or overfit to surface signals without strong grounding
- researchers lack a durable state model for discovery, analysis, execution, and verification
- there is little clean API surface for higher-level orchestration

We need a product that turns the ML research loop into a durable, inspectable system with strong retrieval, strong paper understanding, and bounded autonomy.

---

## 4. Product Vision

Build the best local co-scientist for ML researchers: a system that can ingest a research direction, discover and organize the relevant literature, analyze papers into structured knowledge, propose and execute credible experiments, interpret experimental progress, learn from prior work, and expose the entire process through both a human-facing UI and an orchestrator-facing API.

---

## 5. Goals

### 5.1 Primary goals

- Reduce time from a new ML research problem to a credible baseline and first verified experiments.
- Combine internal memory, external literature discovery, paper analysis, and execution into one workflow.
- Preserve the researcher-style literature funnel: **title + abstract together -> shortlist -> HTML or other machine-readable full text if available -> PDF only when necessary**.
- Make discovery reproducible through explicit state, step logs, structured outputs, and evaluation metrics.
- Turn selected papers into structured, provenance-aware analysis artifacts rather than only freeform summaries.
- Support automated low-risk experimentation while preserving human intervention and steering.
- Add LLM-assisted auto-remediation so mechanical failures do not automatically become full postmortem events.
- Add directional signal tracking so the system can determine whether a hypothesis line is advancing, stalled, regressing, noisy, or showing a breakthrough.
- Support budgeted autonomous research loops that can continue iterating while the user is away.
- Learn reusable procedural patterns across charters, not only within one research cycle.
- Make skills modular so the system can gain new behaviors by loading `skill.md` packages rather than hardcoding everything into the core.
- Expose a stable API so orchestrator agents can use and monitor the system safely.
- Make every result traceable to evidence, prompts, code lineage, runtime, verification output, and policy decisions.

### 5.2 Secondary goals

- Evaluate the product across a few public benchmark tasks without making the product benchmark-centric.
- Support structured exports that can be used by both humans and coding agents.
- Make the local system good enough that it can later generalize to broader research domains.
- Keep the product usable by a single researcher on a single workstation.

---

## 6. Non-Goals

The ML laboratory v1 will not:

- be a general wet-lab or physical-science execution system
- autonomously publish papers or represent unverified claims as scientific truth
- mirror all arXiv PDFs by default
- require a human to approve every routine low-risk run
- depend on distributed cluster orchestration, Kubernetes, or multi-tenant infrastructure
- let external orchestrators bypass policy, approvals, or durable state
- use LLM paper review scores as a trusted standalone ranking or acceptance mechanism
- treat a hidden chat transcript as the system's source of truth
- ship community social features as a primary product surface in v1

---

## 7. Users and Jobs to Be Done

### 7.1 Primary user

An ML researcher or advanced practitioner who wants a system that behaves like a capable lab assistant.

### 7.2 Secondary user

An external orchestrator agent or coding-agent framework that wants to drive the lab through a clean API instead of brittle UI automation.

### 7.3 Core jobs to be done

When I define a new ML research problem, help me:

- understand what we already know internally
- discover relevant external work without brute-force paper ingestion
- rank, filter, and diversify candidate papers
- inspect why a paper was retrieved and why it was shortlisted
- analyze a chosen paper into concepts, methods, experiments, datasets, and reproducibility cues
- ask targeted questions over one paper or a paper set and get provenance-aware answers
- propose multiple evidence-grounded directions
- turn a promising direction into a valid experiment plan
- execute and verify experiments locally
- understand whether a research line is improving or stalling
- automatically recover from trivial mechanical failures
- preserve failures and reusable lessons learned
- monitor progress live and intervene when needed
- let higher-level orchestrator agents use the same system safely

---

## 8. Product Principles

### 8.1 Research-problem-first

The product is organized around scoped research problems, not around a single benchmark provider or paper search engine.

### 8.2 Metadata before full text

Default literature behavior is:

```text
query plan
-> title + abstract screening
-> shortlist
-> HTML or other machine-readable full text when needed
-> PDF only when necessary
```

### 8.3 Discovery state is a product surface

Discovery is not a transient prompt.  The system should maintain explicit paper sets, links, statistics, summaries, rankings, and step logs that can be inspected, exported, and resumed.

### 8.4 Paper understanding should be structured

When the user escalates from discovery to analysis, the system should produce structured paper knowledge with provenance, not only narrative summaries.

### 8.5 Evidence before hypothesis, hypothesis before code

The system should not jump straight from retrieval into code generation.

### 8.6 Verification before claim

Every experiment is tested.  Promoted findings require deterministic verification and clear comparison context.

### 8.7 Review agents are advisory, not sovereign

LLM-generated paper critiques and paper scores can help prioritize reading and identify weaknesses, but they should not be treated as the final arbiter of paper quality or experiment validity.

### 8.8 Autonomy is budgeted and inspectable

The system should automate low-risk work, remediate trivial failures, and run unattended loops when policy allows, but it must always expose telemetry, intervention points, and termination conditions.

### 8.9 Local-first and bounded

The system must be usable on one machine with explicit budgets, inspectable artifacts, and resumable state.

### 8.10 Skills are product surface, not a hack

Behavioral modularity must be deliberate.  `skill.md` packages are a supported extension mechanism.

### 8.11 API-first control plane

Everything the UI can do should flow through a durable control-plane API so external orchestrators can use the same system.

### 8.12 Task-scoped context

The product should never stuff all history and all documents into every model context.  Context must be assembled per task, per phase, per skill, and per operator.

---

## 9. Product Scope

### 9.1 In scope for the v1 ML laboratory

#### A. Research intake and problem scoping

- create a `ResearchCharter` from a scoped ML research problem
- capture goals, datasets, budgets, success criteria, stop conditions, and constraints
- attach internal and external source scopes

#### B. Multi-source discovery and literature triage

- internal corpus retrieval
- arXiv metadata warehouse
- targeted external retrieval for selected sources
- query expansion and structured retrieval planning where useful
- title + abstract screening together
- shortlist rationale and escalation rationale
- selective escalation to HTML or PDF
- deduplication across sources
- ranking views that can balance similarity, recency, novelty, and other configured factors
- diversity-aware postprocessing so results are not redundant clones of one another

#### C. Discovery state, exports, and evaluation

- explicit discovery state that persists paper sets, links, statistics, summaries, and step history
- synchronized artifacts for discovery and analysis outputs
- machine-readable exports such as JSON, CSV, BibTeX, and Markdown where applicable
- human-readable rendered views and downloadable reports
- retrieval evaluation metrics such as hit rate, MRR, Recall@K, and Precision@K when ground truth is available

#### D. Paper analysis workbench

- ingest selected papers from PDF or URL
- structure-aware chunking that preserves sections, figures, tables, and equations
- typed paper graph with nodes for papers, sections, concepts, methods, experiments, datasets, and visual elements
- provenance metadata for all extracted entities and relations
- graph-aware question answering and locate functionality
- coverage verification for sections, figures, tables, and equations
- structured paper analysis packets and reproducibility notes

#### E. Evidence, hypotheses, and protocols

- turn shortlisted sources and analyzed papers into `EvidenceCard`s
- support contradiction and redundancy signals
- generate multiple candidate hypotheses
- critique and rank hypotheses
- compile selected hypotheses into executable `ExperimentSpec`s

#### F. Execution lab

- isolated GPU-capable execution
- automated low-risk experiment runs
- live telemetry and intervention controls
- code lineage and artifact capture

#### G. Verification and research memory updates

- deterministic checks for every run
- comparison to declared baseline and relevant historical internal work
- structured failure postmortems
- directional signal classification and frontier tracking
- promotion or rejection of findings

#### H. Reporting

- rendered reports in the UI
- literature screening packets
- paper analysis packets
- experiment writeups
- verification reports
- failure postmortems
- cycle summaries and completion reports

#### I. Skill system

- discover, validate, enable, disable, and execute `skill.md` packages
- attach skills to operators and research cycles
- store skill execution records and lineage

#### J. Orchestrator API

- create and manage research cycles over API
- monitor events, discovery state, runs, approvals, and reports
- steer, pause, cancel, or annotate work through a policy-checked interface

### 9.2 In scope for the autonomy roadmap after the core loop is stable

#### A. Auto-remediation layer

- classify mechanical failures into actionable remediation paths
- run `auto_remediate_operator` before full postmortem generation
- allow focused LLM-assisted fixes for dependency failures, OOM, timeout, metric serialization issues, and invalid artifact output
- preserve remediation lineage as a first-class run artifact

#### B. Directional signal evaluation

- classify runs as `advancing`, `stalled`, `regressing`, `noisy`, or `breakthrough`
- support per-problem significance thresholds and constraint metrics
- run a cheap self-critic before the full verification suite when useful
- maintain a metric frontier per charter and hypothesis line

#### C. Autonomous experiment loop

- support supervised and autonomous modes
- continue promising lines, vary stalled ones, deprioritize regressing ones, and regenerate hypotheses when the portfolio is exhausted
- enforce compute, wall-clock, and run-count budgets at the cycle level
- support context summarization and repetition detection for long unattended loops

#### D. Cross-charter procedural memory

- consolidate postmortems, successful methods, and signal patterns into `CanonicalPattern`s
- reuse positive and negative patterns across future charters
- decay stale patterns and support human curation

### 9.3 Out of scope for the first release

- generalized non-ML science adapters
- fully autonomous external publication workflows
- third-party multi-user SaaS deployment
- deep graph-native storage as the canonical source of truth
- unconstrained agent societies without shared state and policy

---

## 10. Core User Workflows

### 10.1 Researcher workflow

```text
define research problem
-> create charter
-> retrieve internal + external sources
-> screen title + abstract together
-> shortlist and inspect rationale
-> escalate to HTML/PDF where justified
-> analyze chosen papers into a typed graph
-> ask graph-aware questions and inspect coverage gaps
-> extract evidence
-> generate and critique hypotheses
-> compile experiment spec
-> run experiments
-> verify
-> inspect directional signal and frontier state
-> review report and decide next action
```

### 10.2 Low-risk autonomous workflow

```text
approved charter + policies
-> automated retrieval and screening
-> automated paper analysis where selected
-> automated protocol compilation
-> automated low-risk experiments
-> auto-remediation of mechanical failures
-> directional signal evaluation
-> pivot, continue, or regenerate hypotheses
-> live telemetry to user
-> automatic verification, postmortem creation, and completion reporting
-> user intervention only when needed or requested
```

### 10.3 External orchestrator workflow

```text
orchestrator authenticates
-> creates or resumes research cycle
-> subscribes to event stream
-> requests operator or skill execution
-> receives discovery state, telemetry, and reports
-> pauses, cancels, or adds guidance
-> submits approvals where policy allows
```

---

## 11. Functional Requirements

### FR-1 Research Intake

- The product must allow a user or orchestrator to create a `ResearchCharter` for a scoped ML problem.
- The charter must include goal, success criteria, budget envelope, source scope, and stop conditions.
- The product must persist the charter and expose it through UI and API.

### FR-2 Multi-Source Retrieval

- The product must retrieve from both internal and external sources.
- The product must support an arXiv metadata warehouse and incremental updates.
- The product must support targeted source retrieval driven by the charter.
- The product must support deduplication across sources.
- The product must support lexical, semantic, and optional reranking paths where beneficial, while preserving measurable trade-offs in cost and latency.

### FR-3 Discovery Triage and Ranking

- The product must evaluate title and abstract together during first-pass screening.
- The product must record why a paper or source was shortlisted.
- The product must prefer HTML or machine-readable full text over PDF when available.
- The product must record why any deeper read was requested.
- The product must support ranking views that balance relevance, recency, novelty, and configured user intent.
- The product should support diversity-aware postprocessing so the top results are not overly redundant.

### FR-4 Discovery State and Structured Outputs

- The product must maintain explicit discovery state for papers, links, statistics, summaries, rankings, and step history.
- The product must regenerate synchronized machine-readable artifacts after meaningful discovery or analysis steps.
- The product must expose those artifacts through the UI and API.
- The product must support export formats appropriate for researcher workflows, including at least JSON and Markdown, with CSV and BibTeX where applicable.

### FR-5 Paper Analysis Pipeline

- The product must support analysis of a paper from PDF or URL.
- The product must extract structured elements including sections, figures, tables, equations, methods, experiments, datasets, and concepts.
- The product must build a typed paper graph with provenance metadata linking graph elements back to source content.
- The product must preserve verification status and confidence for extracted elements.

### FR-6 Graph-Aware QA and Coverage Verification

- The product must support question answering grounded in the typed paper graph and supporting source chunks.
- The product must support precise locate functionality for concepts, figures, tables, and other extracted elements.
- The product must compute coverage diagnostics for figure, table, section, and equation extraction.
- The product must expose missing-link and missing-coverage diagnostics to the user.

### FR-7 Evidence and Hypothesis Formation

- The product must extract structured evidence from shortlisted sources and analyzed papers.
- The product must generate multiple hypotheses, not only one.
- The product must critique and rank hypotheses.
- Each hypothesis must cite supporting evidence.

### FR-8 Protocol Compilation

- The product must compile a hypothesis into an `ExperimentSpec` before execution.
- The `ExperimentSpec` must define baseline, controls, metrics, artifacts, stop conditions, and expected outputs.

### FR-9 Execution

- The product must run experiments in isolated workspaces and containers.
- The product must support GPU-capable runs when required.
- The product must support automated low-risk experimentation.
- The product must stream telemetry to the UI and API during execution.

### FR-10 Auto-Remediation

- The product must support LLM-assisted remediation for mechanical failures before escalating to full postmortem analysis.
- The product must support focused remediation paths for recognized failure classes and broader debugging paths for unknown failures.
- The product must record remediation attempts, actions, and outcomes in durable lineage.
- The product must preserve policy controls over allowed fix types and retry budgets.

### FR-11 Verification and Directional Signal

- The product must verify every experiment.
- The product must compare results against the declared baseline and relevant historical internal work.
- The product must classify failures and create a structured postmortem for unsuccessful or invalid runs.
- The product must classify directional signal for successful runs using metrics and recent run history.
- The product must maintain frontier state per charter and hypothesis line.

### FR-12 Autonomous Research Loop

- The product must support supervised and autonomous execution modes.
- In autonomous mode, the system must be able to continue, vary, deprioritize, or pivot hypotheses based on directional signal and policy.
- The system must be able to regenerate hypotheses when the current portfolio is exhausted and policy allows it.
- The system must stop cleanly when the budget or termination conditions are met.

### FR-13 Cross-Charter Procedural Memory

- The product must support a cross-charter memory layer for reusable positive and negative patterns.
- The product must support pattern consolidation from runs, postmortems, and verification reports.
- The product must allow pattern reuse in remediation, retrieval, hypothesis generation, and verification.
- The product must support staleness handling and human curation of patterns.

### FR-14 Reporting

- The product must generate human-readable reports for literature screening, paper analysis, experiments, verification, postmortems, and cycle summaries.
- Reports must be rendered in the UI and available over API.
- Autonomous runs must produce completion reports that summarize what was tried, what happened, and what should happen next.

### FR-15 Skill System

- The product must support a first-class skill mechanism using `skill.md` packages.
- Skills must be discoverable from configured directories.
- Skills must be enable-able, disable-able, and versioned.
- Skills must declare required context, outputs, and permissions.
- Skill execution must be logged and linked to research state.
- Skills must not bypass policy, provenance, or verification requirements.

### FR-16 Orchestrator API

- The product must expose a stable control-plane API for external orchestrators.
- The API must allow create/read/update of research cycles, discovery artifacts, reports, approvals, and run-control actions.
- The API must expose streaming telemetry for events and run status.
- The API must support orchestrator identity and scoped permissions.
- All orchestrator actions must be auditable.

### FR-17 Evaluation and Benchmarking

- The product must support retrieval evaluation metrics when ground truth is available.
- The product must support internal benchmarking of discovery quality, verification quality, and autonomy quality over time.
- The product must let users compare search and ranking configurations without requiring external tooling.

### FR-18 Human Review and Intervention

- The product must allow the user to inspect and edit important extracted artifacts where appropriate.
- The product must allow the user to intervene in active work.
- The product must make it clear which parts of the output are deterministic, which are model-generated, and which are human-verified.

---

## 12. Non-Functional Requirements

### 12.1 Reliability

- Research state must survive restarts.
- Jobs must be resumable.
- Audit history must be append-only.

### 12.2 Reproducibility

- Accepted results must be replayable from stored lineage.
- Discovery and analysis outputs must be reconstructible from stored inputs, scores, and step history.
- Runs must record code lineage, model identifiers, datasets, configs, metrics, and artifacts.

### 12.3 Explainability

- The system must answer why a paper was retrieved, why it was shortlisted, why a graph element exists, why a hypothesis exists, why a run was promoted, and why a skill was applied.

### 12.4 Extensibility

- New task behavior should preferentially be added as skills, adapters, configs, or operator modules instead of core rewrites.

### 12.5 Operability

- A single researcher should be able to run the system locally.
- The phase-1 UI must expose live status, reports, and controls.

### 12.6 API stability

- Orchestrator-facing endpoints must be versioned.
- Event payloads must use stable schemas.

### 12.7 Safety and isolation

- Generated code must not run directly on the host.
- Skills and orchestrator actions must be subject to capability checks.
- External writes must require explicit policy satisfaction.

### 12.8 Context discipline

- Operators must have bounded context budgets.
- Long autonomous runs must degrade gracefully through summarization or prioritization rather than uncontrolled prompt growth.

---

## 13. Success Metrics

### 13.1 Discovery quality metrics

- shortlist precision as judged by the researcher
- Recall@K, MRR, hit rate, and Precision@K where labeled evaluation is available
- percentage of shortlisted papers escalated to full text for a documented reason
- percentage of discovery sessions with synchronized structured artifacts successfully generated
- diversity of top-ranked result sets for broad queries

### 13.2 Paper analysis quality metrics

- graph coverage score for sections, figures, tables, and equations
- proportion of graph answers returned with valid provenance
- user-rated usefulness of paper analysis packets
- rate of human corrections to extracted graph elements

### 13.3 Experiment quality metrics

- time from charter creation to first baseline run
- time from charter creation to first verified experiment
- percentage of experiments with complete lineage and verification records
- percentage of failed experiments with structured postmortems
- auto-remediation resolution rate for mechanical failures

### 13.4 Autonomy quality metrics

- percentage of completed runs with directional signal attached
- average autonomous run count before user intervention
- number of useful frontier improvements per charter
- percentage of autonomous pivots later judged sensible by the researcher

### 13.5 Memory quality metrics

- reuse rate of canonical patterns across charters
- reduction in repeated failed ideas due to cross-charter memory
- researcher trust in pattern suggestions and warnings

### 13.6 System metrics

- median event-stream latency to UI and API
- skill load and validation success rate
- retrieval artifact generation success rate
- API contract test pass rate

---

## 14. Risks and Mitigations

| Risk | Why it matters | Mitigation |
|---|---|---|
| Over-reading literature | Wasted time, cost, and noisy evidence | Enforce metadata-first triage, escalation reasons, and full-text budgets |
| Redundant retrieval results | Discovery quality drops | Add deduplication, diversity-aware ranking, and configurable views |
| Weak paper graph extraction | Deep analysis becomes untrustworthy | Preserve provenance, expose coverage checks, and allow human review |
| Over-trusting review agents | LLM scores may not align with expert judgment | Keep paper review outputs advisory and never the sole decision gate |
| Hidden behavior in prompts | Hard to debug or govern | Move durable logic to typed state, policies, configs, and skills |
| Fragile experimentation | Broken or irreproducible runs erode trust | Use isolated workspaces, containers, verification, and postmortems |
| Mechanical failures consuming intelligence budget | Co-scientist wastes time on trivial issues | Add auto-remediation before postmortem generation |
| Autonomous loops thrashing | Budget burn without progress | Use directional signal, repetition detection, frontier tracking, and hard budget stops |
| Pattern memory becoming stale | Old advice degrades outcomes | Track environment assumptions, apply decay, and support human curation |
| External orchestrator misuse | Unsafe or opaque remote control of the lab | Use scoped API tokens, auditable actions, policy checks, and approval gates |

---

## 15. Release Framing

### 15.1 MVP definition

The MVP is complete when a user or orchestrator can:

1. create a scoped ML research cycle
2. retrieve internal and external sources
3. triage literature with title + abstract together
4. inspect explicit discovery state and exports
5. selectively read deeper only when justified
6. analyze a chosen paper into a provenance-aware structured representation
7. generate evidence-backed hypotheses
8. compile and run experiments automatically where policy allows
9. verify every run and create postmortems
10. inspect directional signal and frontier state
11. review rendered reports in a UI
12. use at least a small library of `skill.md` packages
13. drive and monitor the system through a stable orchestrator API

### 15.2 Post-MVP autonomy milestone

The first autonomy milestone is complete when the system can:

1. auto-remediate common mechanical failures
2. classify directional signal on verified runs
3. execute a budgeted autonomous loop across multiple hypotheses
4. regenerate hypotheses when the current portfolio stalls
5. produce a completion report at the end of an unattended run window
6. reuse cross-charter positive and negative patterns in future cycles

### 15.3 Evaluation tracks

The product should be exercised against:

- a small set of public ML benchmark tasks
- a set of internal research problems and internal research memory
- retrieval and literature triage tasks against arXiv metadata plus internal corpora
- paper analysis tasks where coverage and provenance can be manually spot-checked

---

## 16. Resolved Product Decisions for v1

### 16.1 How much of the paper analysis pipeline should run automatically during discovery versus only on explicit escalation?

Adopt a **two-depth analysis model**.

**Automatic during discovery:**

- metadata-level analysis should always run from the start
- this includes title, abstract, authors, venue, year, source, query fit, likely contribution type, likely methodological relevance, and shortlist rationale
- this lightweight analysis should help rank, filter, diversify, and justify shortlisting decisions

**Selective deeper analysis after shortlist or later pivot points:**

- full-text ingestion, typed paper graph construction, graph-aware QA context, reproducibility checks, and coverage verification should run only for shortlisted papers or when explicitly triggered by downstream needs
- downstream triggers include evidence extraction, protocol validation, contradiction resolution, hypothesis regeneration, and frontier validation after experiments

This keeps the system aligned with the metadata-first funnel while still allowing paper analysis to re-enter later in the cycle when the research loop needs deeper evidence.

### 16.2 Should paper review outputs be stored as a separate artifact type from paper analysis packets?

Yes.  In v1, paper review outputs should be stored as a **separate but linked artifact type**.

Reasoning:

- a **paper analysis packet** is primarily structural and evidence-oriented
- a **paper review artifact** is evaluative and advisory
- they have different trust levels, different generation logic, and different downstream uses

Recommended stance:

- keep both artifacts linked to the same source paper and provenance chain
- allow a report bundle to include both
- never let review artifacts replace analysis packets as the canonical source of paper-grounded evidence

### 16.3 Which retrieval views should be mandatory in v1?

Use a smaller subset in v1.

Recommended mandatory views:

- **Stable** — the default for precise, reproducible, high-confidence retrieval
- **Discovery** — a novelty- and diversity-leaning mode for adjacent ideas, overlooked work, and broader exploration

Recommended non-mandatory view for v1:

- **Balanced** can exist internally as a preset or API option, but it does not need to be a first-class required user-facing mode in the first release

Why this is the best v1 cut:

- Stable supports the most common research workflow
- Discovery supports the main exploratory use case
- Balanced adds extra UI and tuning surface without adding a clearly distinct workflow early on

### 16.4 Which autonomy decisions should remain human-gated in the first shipped release?

The system should support **full automation as a configurable mode**, but shipped defaults should keep a few specific gates for safety and cost control.

Recommended gates in the first release:

- runs that exceed a configured cost, time, or hardware threshold
- any profile escalation such as a larger GPU tier or substantially higher resource envelope
- network-enabled execution or external side effects
- promotion of a result to a validated or headline finding

Recommended optional gate:

- a **checkpoint gate** that lets the user require review after each completed experiment, or after every N runs, before the system launches the next costly experiment

This matches the intended operating model:

- full automation should be possible
- human gating should be minimal by default
- cost-control and safety gates should remain configurable

### 16.5 How strict should third-party skill trust and signing be in the first local release?

Use a **moderate-trust model** in v1.

Recommended stance:

- do **not** require cryptographic signing in the first local release
- do require manifest validation, content hashing, declared capabilities, and explicit user trust for higher-risk skills
- first-party skills can be trusted by default
- user-authored local skills can be trusted by explicit opt-in
- third-party unsigned skills should be treated as untrusted until the user approves them

Risk-sensitive behavior should require stronger trust:

- Python hooks
- filesystem write access beyond allowed artifact paths
- network access
- run-control mutations

This gives the first release a practical security posture without making local experimentation painful.  Signing can be added later once the format and trust model stabilize.

## 17. Next Document

The next architecture source of truth is `system_patterns.md`, which should translate these revised product requirements into the canonical system shape and reflect:

- two-depth paper analysis behavior
- separate but linked paper analysis and review artifacts
- stable and discovery retrieval modes as the required v1 views
- configurable autonomy gates with optional checkpoint review behavior
- trust tiers for third-party skills

