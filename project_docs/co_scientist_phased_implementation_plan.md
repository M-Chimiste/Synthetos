# Phased Implementation Plan

**Product:** Synthetos (ML Laboratory Co-Scientist)\
**Role:** Planner\
**Status:** Working Draft v4\
**Scope:** Local small-scale ML laboratory with autonomy roadmap\
**Last Updated:** 2026-04-09

---

## 1. Purpose

This document turns the revised PRD and system patterns into a practical build sequence.

It answers six questions:

1. What do we build first?
2. What can wait?
3. What should each phase prove before we move on?
4. How do discovery, paper analysis, experimentation, and autonomy land as real vertical slices?
5. When do reranking, paper reviews, remediation, and autonomous looping appear?
6. Which workstreams must start early because they shape the entire system?

This plan is downstream of `prd.md` and `system_patterns.md` and should guide execution before package-level details are tightened in `tech_context.md`.

---

## 2. Planning Assumptions

This implementation plan assumes the following product decisions are already in force:

- The system is **research-problem-first**, not competition-first.
- The first release is an **ML laboratory**, not a general-purpose science platform.
- The system works against **both internal and external sources**.
- Discovery is **metadata-first** and uses **title + abstract together** before any deeper read.
- The system should maintain **explicit discovery state** and synchronized exports.
- Paper analysis runs at **two depths**:
  - metadata-depth analysis always during discovery
  - full-text paper analysis only after shortlist or later escalation
- Paper review artifacts are **separate but linked** and only generated for papers that reach full-text analysis.
- The v1 retrieval views are **Stable** and **Discovery**.
- Reranking is **automatic by default**, but must be budget-aware and degrade gracefully.
- The execution layer must support **GPU-capable isolated workloads**.
- Different workflow stages may use **different models** through a common gateway.
- Every experiment should produce a **run record**, a **verification record**, and when needed, a **structured postmortem**.
- Mechanical failures should route through **auto-remediation** before becoming full postmortem cases.
- Verified runs should eventually gain **directional signal** and **frontier state**.
- The system should support **full automation as a configurable mode**, with checkpoint gates off unless policy or profile enables them.
- Modular behavior must be supported through **skill.md**** packages**.
- External orchestrators must be supported through a **stable control-plane API and telemetry stream**.
- Cross-charter pattern memory should be **light-touch by default**, with no mandatory human verification before patterns can begin influencing planning.

---

## 3. Delivery Principles

### 3.1 Build vertical slices, not disconnected subsystems

Each phase should end with a real loop that a human or orchestrator can use, inspect, and critique.

### 3.2 Stabilize the artifact model early

The most important early decision is the durable shape of the research record.

The following entities should be treated as first-class from the start:

- `ResearchCharter`
- `ResearchState`
- `ProblemProfile`
- `DiscoverySession`
- `DiscoveryView`
- `PaperCard`
- `PaperAnalysisPacket`
- `PaperReviewArtifact`
- `EvidenceCard`
- `HypothesisCard`
- `ExperimentSpec`
- `RunRecord`
- `VerificationReport`
- `FailurePostmortem`
- `RemediationAction`
- `MetricFrontier`
- `CanonicalPattern`
- `ReportBundle`
- `SkillDefinition`
- `SkillBinding`
- `SkillExecutionRecord`
- `OrchestratorClient`
- `ApprovalEvent`
- `DomainEvent`

### 3.3 Keep context scoped to the task

The system should not give every model every document, every prompt, and every event.  Context assembly should be phase-specific, operator-specific, and skill-aware.

### 3.4 Prefer durable simple infrastructure in v1

The first version should optimize for:

- local repeatability
- inspectable storage
- auditable execution
- easy restart and resume
- low operator burden
- headless API access

### 3.5 Discovery and analysis are part of the product, not pre-processing

Discovery state, paper analysis packets, and related exports should land early, not as late-stage polish.

### 3.6 Reports are part of the product

Every major phase should emit something readable:

- discovery report
- paper analysis packet
- evidence summary
- hypothesis review packet
- experiment run summary
- verification report
- failure postmortem
- completion report

### 3.7 Skills and API support start early

Skill support and orchestrator access should not be backfilled late.  They affect state shape, event design, trust boundaries, and operator contracts from day one.

### 3.8 Autonomy features should layer onto a stable lab core

Remediation, signal, autonomous loops, and cross-charter pattern memory should be added in order, after the base discovery-analysis-experiment loop is stable.

---

## 4. Phase Overview

The roadmap is organized into seven phases.

### Phase 0 — Foundation, Shared State, Skill Skeleton, and API Spine

Create the repo skeleton, canonical schemas, control plane, worker runtime, event stream, skill loader, and orchestrator-facing API foundation.

### Phase 1 — Discovery Pipeline MVP

Deliver a real research discovery loop with internal and external retrieval, metadata-depth analysis, shortlist reasoning, automatic reranking with graceful fallback, stable/discovery views, and structured exports.

### Phase 2 — Full Paper Analysis and Evidence Pipeline

Turn shortlisted papers into structured paper-analysis packets with typed paper graphs, graph-aware QA, locate support, coverage checks, optional advisory review artifacts, and evidence extraction.

### Phase 3 — Hypotheses, Protocols, and Execution Lab MVP

Turn evidence into ranked hypotheses, executable experiment specs, isolated runs, live telemetry, and baseline verification.

### Phase 4 — Remediation, Directional Signal, and Frontier Tracking

Add mechanical-failure auto-remediation, signal classification, frontier updates, and richer verification-driven next-step logic.

### Phase 5 — Autonomous Loop and Configurable Gating

Enable supervised and autonomous execution modes, budget-aware looping, optional checkpoint gates, and completion reporting.

### Phase 6 — Cross-Charter Pattern Memory and Pilot Hardening

Add canonical pattern consolidation, reuse across charters, trust tiers for skills and patterns, and full-system hardening across representative ML workloads.

---

## 5. Phase 0 — Foundation, Shared State, Skill Skeleton, and API Spine

### 5.1 Objective

Stand up the minimum local platform needed to support a real research cycle.

This phase creates the product backbone:

- repository shape
- local services
- durable state
- state transitions
- operator contract
- model gateway
- event stream
- skill discovery and validation
- initial dashboard shell
- versioned orchestrator API skeleton

### 5.2 Work to implement

#### A. Repository and service skeleton

- Create the monorepo structure for API, worker, web, CLI, shared schemas, adapters, skills, prompts, and tests.
- Define the first bounded contexts in code.
- Add local bootstrapping for the whole stack.

#### B. Durable state

- Stand up PostgreSQL as the system of record.
- Enable `pgvector`.
- Create migration tooling.
- Add canonical tables for cycles, jobs, events, discovery sessions, reports, skills, approvals, orchestrator clients, and lineage.

#### C. Shared state model

- Define `ResearchState` and allowed state transitions.
- Define the typed operator input/output contract.
- Add append-only domain events.
- Define lineage and identity rules.

#### D. Minimal UI shell

- Create a lightweight local UI for:
  - creating a research cycle
  - viewing current state
  - browsing recent events
  - seeing active jobs
  - opening generated reports
  - observing live telemetry

#### E. Telemetry plumbing

- Add worker-to-UI and worker-to-API streaming for:
  - active operator
  - current phase
  - job status
  - run status
  - recent log events
- Add pause, cancel, and resume hooks.

#### F. Model gateway

- Create a common adapter for LLM calls.
- Create a common adapter for embeddings.
- Support both hosted and local models from day one.
- Support role-based model routing from day one.

#### G. Skill foundation

- Define the `skill.md` package contract.
- Build skill discovery from configured directories.
- Validate skill metadata and basic structure.
- Persist `SkillDefinition` and enable/disable state.
- Expose a skill catalog view in UI and API.
- Add trust tiers for first-party, user-local, and untrusted third-party skills.

#### H. Orchestrator API foundation

- Define versioned resource ids and API schemas.
- Expose endpoints for cycle creation, cycle state, event streaming, and health.
- Add API token and scope model for external orchestrators.
- Record orchestrator identity in events.

### 5.3 Deliverables

- local stack boot script
- monorepo structure
- database migrations
- shared schema package
- initial dashboard shell
- operator runtime skeleton
- event stream and audit trail
- model gateway interface
- skill discovery and validation skeleton
- orchestrator API skeleton with OpenAPI docs

### 5.4 Exit criteria

Phase 0 is done when:

- a user can create a research cycle from UI or CLI
- the cycle is persisted and visible in the dashboard
- a worker can claim a job, emit events, and update durable state
- the UI can stream state changes without manual refresh
- one hosted model and one local model can both be invoked through the same gateway
- the system can discover at least one first-party skill and expose it via UI/API
- an external client can create a cycle and subscribe to the event stream through the API

### 5.5 Out of scope

- real literature intelligence
- real experiment execution
- strong verification logic
- rich skill hooks

---

## 6. Phase 1 — Discovery Pipeline MVP

### 6.1 Objective

Deliver the first genuinely useful research discovery loop:

```text
scoped problem
-> source retrieval
-> metadata-depth analysis
-> title + abstract screening
-> shortlist
-> stable or discovery view
-> selective deeper-read escalation
-> discovery report and exports
```

### 6.2 Work to implement

#### A. Research intake integration

- Connect `ResearchCharter` to discovery workflows.
- Add source-scope selection and retrieval-view selection.
- Support researcher notes and orchestrator-provided search guidance.

#### B. Internal and external source adapters

- Add internal corpus adapter.
- Add arXiv metadata warehouse integration.
- Add targeted external retrieval adapters for the initial supported sources.
- Add metadata dedupe across sources.

#### C. Metadata-depth analysis

- Implement lightweight analysis over title, abstract, authors, venue, year, and source.
- Capture likely method family, likely contribution type, shortlist fit, and escalation rationale.
- Persist metadata-depth analysis as part of the discovery state.

#### D. Ranking, views, and reranking

- Implement first-stage ranking with lexical retrieval and configured scoring features.
- Support **Stable** and **Discovery** retrieval views.
- Add automatic reranking when available and within policy budget.
- Add graceful fallback to first-stage ranking when reranking is unavailable, too slow, or over budget.
- Add diversity-aware postprocessing for Discovery mode.

#### E. Structured outputs and discovery UX

- Generate discovery artifacts such as:
  - ranked paper set
  - links and access data
  - basic stats
  - shortlist summary
  - step log
- Surface view differences and shortlist rationale in the UI.
- Make discovery artifacts retrievable over API.

#### F. Evaluation hooks

- Add optional evaluation flow for hit rate, Recall\@K, Precision\@K, and MRR when ground truth is available.
- Persist metrics to the discovery session.

#### G. Skills

- Add first-party literature skills such as:
  - problem scoping support
  - title/abstract triage
  - shortlist critique
  - escalation rationale drafting

### 6.3 Deliverables

- research charter to discovery flow
- source adapters for internal corpus and initial external sources
- metadata-depth analysis operator
- stable and discovery retrieval views
- automatic reranking with graceful fallback
- discovery artifacts and exports
- first literature skill set
- API endpoints for discovery state and reports

### 6.4 Exit criteria

Phase 1 is done when:

- a user can define a research problem and run discovery end to end
- the system can search internal corpus plus external metadata sources
- shortlisted papers show why they were selected
- stable and discovery views are both available
- reranking improves results when affordable and falls back cleanly when not
- discovery artifacts are viewable in the UI and API
- an orchestrator can monitor discovery progress without scraping the UI

### 6.5 Out of scope

- full paper graph construction
- deep reproducibility checking
- experiment execution
- remediation and autonomy

---

## 7. Phase 2 — Full Paper Analysis and Evidence Pipeline

### 7.1 Objective

Turn shortlisted papers into structured understanding and evidence.

### 7.2 Work to implement

#### A. Full-text ingestion and chunking

- Add HTML-first and PDF fallback fetch paths.
- Build structure-aware chunking that preserves sections, figures, tables, and equations.
- Preserve source locations and provenance for every chunk.

#### B. Typed paper graph construction

- Add extractors for:
  - concepts
  - methods
  - experiments
  - datasets
  - figures and tables
  - equations where useful
- Build typed nodes and relations with provenance metadata.

#### C. Graph-aware QA and locate support

- Add graph-aware retrieval and question answering.
- Add locate workflows for concepts, figures, tables, and related chunks.
- Return evidence-backed answers with supporting artifacts.

#### D. Coverage verification

- Compute coverage diagnostics for sections, figures, tables, and equations.
- Surface missing-link and weak-coverage warnings in the UI.

#### E. Paper review artifacts

- Generate `PaperReviewArtifact` only for papers escalated to full-text analysis.
- Keep review outputs advisory and linked to the corresponding `PaperAnalysisPacket`.

#### F. Evidence pipeline

- Turn selected paper-analysis outputs into `EvidenceCard`s.
- Preserve contradiction, redundancy, and confidence signals.
- Distinguish metadata-only evidence from full-analysis evidence.

#### G. Skills

- Add first-party analysis skills such as:
  - concept extraction guidance
  - method extraction guidance
  - reproducibility checklist guidance
  - evidence synthesis support

### 7.3 Deliverables

- HTML/PDF ingestion path
- structure-aware chunking pipeline
- typed paper graph builder
- graph-aware QA and locate support
- coverage verification subsystem
- linked paper analysis and review artifacts
- evidence extraction operators

### 7.4 Exit criteria

Phase 2 is done when:

- a shortlisted paper can be escalated into a full paper-analysis packet
- the system can answer graph-aware questions over that paper with provenance
- coverage diagnostics identify missing or weakly linked elements
- advisory review artifacts are available only for fully analyzed papers
- evidence cards can be generated from analyzed papers and fed into downstream planning

### 7.5 Out of scope

- autonomous experiment execution
- auto-remediation
- cross-charter pattern memory

---

## 8. Phase 3 — Hypotheses, Protocols, and Execution Lab MVP

### 8.1 Objective

Turn discovery and evidence into real, runnable ML experiments.

### 8.2 Work to implement

#### A. Hypothesis portfolio

- Generate multiple candidate hypotheses from evidence cards.
- Critique and rank them.
- Persist rationale for ranking and deprioritization.

#### B. Protocol compiler

- Compile selected hypotheses into executable `ExperimentSpec`s.
- Define baseline, controls, metrics, artifacts, stop conditions, and expected outputs.
- Reject under-specified ideas.

#### C. Workspace and execution runtime

- Create per-run git worktrees.
- Support base images and on-demand image builds.
- Execute runs in sandboxed containers with optional GPU passthrough.
- Capture logs, metrics, resource usage, and artifacts.

#### D. Telemetry and controls

- Stream run telemetry to UI and API.
- Add pause, cancel, and retry actions.
- Show current operator, current run, and queue state.

#### E. Baseline verification

- Add initial verification checks:
  - baseline comparison
  - artifact presence checks
  - output contract checks
  - basic historical comparison hooks
- Generate initial `VerificationReport`s and `FailurePostmortem`s.

#### F. Skills

- Add coding, experiment planning, and evaluation skills.
- Capture skill usage in run lineage.

### 8.3 Deliverables

- hypothesis portfolio manager
- protocol compiler
- execution runner
- GPU-capable sandbox path
- run telemetry stream
- run-control UI and API
- baseline verification subsystem
- first coding and evaluation skills

### 8.4 Exit criteria

Phase 3 is done when:

- the system can produce evidence-backed hypotheses from discovery and analysis outputs
- a chosen hypothesis compiles into a valid `ExperimentSpec`
- the system can execute a real experiment in an isolated workspace
- live run telemetry is visible in the UI
- every run produces a verification outcome or a failure postmortem
- an allowed external client can monitor and interrupt a run through the API

### 8.5 Out of scope

- automatic remediation
- directional signal
- autonomous hypothesis pivoting
- canonical patterns

---

## 9. Phase 4 — Remediation, Directional Signal, and Frontier Tracking

### 9.1 Objective

Make the execution loop more resilient and more research-aware.

### 9.2 Work to implement

#### A. Failure classification refinement

- Tighten deterministic failure classification to distinguish:
  - dependency failures
  - OOM and resource failures
  - timeouts
  - runtime exceptions
  - metric parse failures
  - invalid artifact output

#### B. Auto-remediation layer

- Add `auto_remediate_operator` before full postmortem generation.
- Support focused remediation paths for known failure classes.
- Support broader debug remediation when the focused path fails.
- Persist `RemediationAction` history and retry lineage.

#### C. Verification expansion

- Add stronger historical comparison.
- Add optional self-critic or quick pre-check before expensive full verification.
- Tighten invalid-result handling and metric sanity checks.

#### D. Directional signal classification

- Add `DirectionalSignal` support with:
  - advancing
  - stalled
  - regressing
  - noisy
  - breakthrough
- Support primary metric and constraint metrics.
- Record signal reasoning in the verification artifact.

#### E. Frontier tracking

- Maintain `MetricFrontier` state per charter and hypothesis line.
- Surface best run, best metric, and runs since last improvement.
- Show frontier state in the UI and API.

#### F. Recommendations and next-step logic

- Update recommendation logic so it uses:
  - remediation history
  - directional signal
  - frontier state
  - postmortem history

### 9.3 Deliverables

- refined failure classification
- auto-remediation subsystem
- directional signal subsystem
- frontier tracking views
- richer verification and recommendation logic

### 9.4 Exit criteria

Phase 4 is done when:

- common mechanical failures can be retried through remediation before postmortem creation
- successful runs receive directional signal classification
- frontier state is visible and updates correctly across repeated runs
- recommendations distinguish between mechanical recovery, parameter variation, and true hypothesis pivots
- resolved mechanical failures do not pollute scientific failure memory the same way irrecoverable failures do

### 9.5 Out of scope

- full autonomous loop
- cross-charter pattern memory

---

## 10. Phase 5 — Autonomous Loop and Configurable Gating

### 10.1 Objective

Enable unattended, budget-aware experiment sequencing without giving up control.

### 10.2 Work to implement

#### A. Autonomy policy and modes

- Add supervised and autonomous modes.
- Add cycle-level budgets for:
  - compute
  - run count
  - wall clock
  - runs per hypothesis
- Keep checkpoint gates off by default unless configuration/profile enables them.

#### B. Autonomous loop operator

- Implement the re-entrant loop:
  - select hypothesis
  - compile or update experiment spec
  - execute
  - remediate if needed
  - verify
  - classify signal
  - continue, vary, pivot, or regenerate
  - stop on budget or policy boundary

#### C. Hypothesis lifecycle transitions

- Add status transitions such as:
  - active
  - stalled
  - deprioritized
  - promising
  - validated
- Use directional signal and frontier state to update lifecycle status.

#### D. Optional checkpoint gates

- Support configurable gates:
  - after every run
  - after every N runs
  - before cost or hardware escalation
  - before result promotion
  - before network-enabled execution

#### E. Context summarization and repetition detection

- Add summarization for long-running loop history.
- Detect repeated specs and repeated near-no-op parameter loops.
- Force variation or pivot when repeated work is detected.

#### F. Completion reporting

- Generate a full completion report at loop end.
- Summarize:
  - hypotheses tried
  - experiment results
  - remediation actions
  - frontier progression
  - next-step recommendations

### 10.3 Deliverables

- supervised/autonomous mode support
- budget-aware autonomous loop
- hypothesis lifecycle transitions
- configurable checkpoint gates
- repetition detection and context summarization
- completion report generation

### 10.4 Exit criteria

Phase 5 is done when:

- the system can run a budgeted unattended sequence across multiple hypotheses
- the loop can continue promising work, vary stalled work, and deprioritize regressing work
- checkpoint gates are configurable and off unless enabled
- the loop stops cleanly at budget or policy boundaries
- the user receives a readable completion report instead of only raw logs

### 10.5 Out of scope

- cross-charter canonical pattern reuse
- broader remote execution scale-out

---

## 11. Phase 6 — Cross-Charter Pattern Memory and Pilot Hardening

### 11.1 Objective

Make the system learn across research cycles and harden it for real use.

### 11.2 Work to implement

#### A. Canonical pattern memory

- Add `CanonicalPattern` entity and consolidation workflows.
- Distill patterns from:
  - postmortems
  - remediation histories
  - directional signal trajectories
  - successful experimental lines
- Track evidence count, confidence, and staleness context.

#### B. Pattern reuse

- Feed canonical patterns back into:
  - retrieval guidance
  - hypothesis generation
  - remediation prior knowledge
  - verification and planning
- Allow low-friction pattern influence without mandatory human verification.
- Support optional human curation for higher-risk or stale patterns.

#### C. Skill and trust hardening

- Strengthen trust-tier enforcement.
- Improve validation and diagnostics for higher-risk skills.
- Add documentation and examples for safe third-party skills.

#### D. End-to-end pilot exercises

- Run the product on selected internal research problems.
- Run the product on a small public benchmark set where appropriate.
- Compare discovery configurations, paper-analysis quality, and autonomy behavior.

#### E. Recovery and product hardening

- Improve resume behavior across long cycles.
- Improve report readability and timeline views.
- Tighten contract tests and compatibility tests for orchestrators.

### 11.3 Deliverables

- canonical pattern subsystem
- pattern-aware planning integration
- trust-tier hardening for skills and patterns
- pilot evaluation results
- hardened recovery and contract tests

### 11.4 Exit criteria

Phase 6 is done when:

- the system can reuse useful positive and negative patterns across charters
- pattern influence works automatically when thresholds are met
- stale patterns decay or are flagged for review
- the full cycle works across a few representative ML problems
- reports and controls are credible enough for day-to-day researcher use
- external orchestrators can drive a full cycle through API with observability and policy control

---

## 12. Cross-Cutting Workstreams

These workstreams cut across every phase.

### 12.1 Model routing and context management

- role-based routing
- local plus hosted model support
- context budgeting and skill-aware assembly
- summarization paths for long-running loops

### 12.2 Policy and approval model

- run thresholds
- model usage policy
- deeper-read budgets
- reranker budgets
- remediation permissions
- autonomy mode and checkpoint behavior
- orchestrator permission scopes

### 12.3 Skill library

- first-party skills
- custom skill examples
- trust tiers
- skill validation and testing
- skill docs and templates

### 12.4 API and telemetry

- versioned schemas
- event streams
- client SDKs
- contract tests

### 12.5 Reporting UX

- rendered markdown
- discovery views
- paper analysis packets
- timeline views
- report bundle navigation
- postmortem readability
- completion reporting

### 12.6 Testing and fixtures

- problem fixtures
- discovery fixtures
- paper-analysis fixtures
- skill fixtures
- execution sandbox fixtures
- API fixtures
- autonomy fixtures

---

## 13. MVP Definition of Done

The baseline MVP is done when all of the following are true:

- a researcher can create a scoped ML research cycle and run it end to end
- the system can retrieve internal and external sources and triage literature with title + abstract together
- stable and discovery views are both usable
- reranking happens automatically when affordable and degrades gracefully when not
- deeper reads are selective, reasoned, and recorded
- selected papers can be turned into provenance-aware paper-analysis packets
- advisory paper review artifacts are generated only for fully analyzed papers
- hypotheses and experiment specs are evidence-backed and durable
- experiments run in isolated GPU-capable sandboxes
- every experiment is verified and failures get postmortems
- the system supports a meaningful first-party `skill.md` library plus custom skills
- reports are readable in the UI and available over API
- an orchestrator agent can create, monitor, and steer a cycle over API without bypassing policy

---

## 14. Autonomy Milestone Definition of Done

The first autonomy milestone is done when all of the following are true:

- the system can auto-remediate common mechanical failures under policy
- successful runs receive directional signal and frontier updates
- supervised and autonomous modes both work
- the loop can continue, vary, pivot, or regenerate hypotheses within configured budgets
- checkpoint gates remain configurable and off unless enabled
- the user receives a completion report for unattended runs
- initial canonical pattern reuse works across at least a few representative cycles

---

## 15. Suggested Immediate Next Step

Use `tech_context.md` to lock the first-pass stack and implementation details for:

- source adapters and retrieval backends
- automatic reranking and graceful fallback behavior
- paper-analysis graph storage and export shape
- remediation and directional-signal schema design
- autonomy policy, checkpoint settings, and pattern thresholds

