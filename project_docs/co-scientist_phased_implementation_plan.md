# Phased Implementation Plan

**ML Laboratory Co-Scientist · delivery roadmap for the local ML laboratory MVP**

**Role**  
The Planner

**Product**  
ML Laboratory Co-Scientist

**Status**  
Working Draft

**Scope**  
Local small-scale ML laboratory MVP

**Last Updated**  
2026-03-21

---

## 1. Purpose

This document translates the current product and architecture direction into a practical build sequence.

It is meant to answer five questions clearly:

1. What do we build first?
2. What can wait?
3. What should each phase prove before we move on?
4. Which workstreams can move in parallel?
5. What does “MVP done” actually mean for the first ML laboratory?

This document is downstream of `system_patterns.md` and should guide the first implementation passes before we lock concrete stack details in `tech_context.md`.

---

## 2. Planning Assumptions

This implementation plan assumes the following product decisions are already in force:

- The system is **research-problem-first**, not competition-first.
- The first release is an **ML laboratory**, not a general-purpose science platform.
- The system should work against **both internal and external sources**.
- arXiv discovery is **metadata-first**, with **title + abstract reviewed together** before any deeper read.
- arXiv escalation should follow **metadata -> HTML full text when possible -> PDF only when necessary**.
- The system should be able to run **automated low-risk experiments** without requiring a human to approve every run.
- The user still needs a **live control surface** for progress, telemetry, intervention, and steering.
- The execution layer must support **GPU-capable isolated workloads**.
- Different workflow stages may use **different models** through a common gateway.
- Every experiment should produce a **result record**, a **verification record**, and if it fails, a **structured postmortem**.
- Historical internal work should matter. The system should compare new outputs to **prior internal runs and research memory**, not just the current baseline.

---

## 3. Delivery Principles

### 3.1 Build vertical slices, not disconnected subsystems

Each phase should end with a real loop that a human can use, inspect, and critique. We should avoid spending multiple phases building invisible infrastructure that cannot yet test the product truth.

### 3.2 Stabilize the artifact model early

The most important early decision is not the queue library or UI framework. It is the durable shape of the research record.

The following entities should be treated as first-class from the start:

- `ResearchCharter`
- `ResearchState`
- `PaperCard`
- `EvidenceCard`
- `HypothesisCard`
- `ExperimentSpec`
- `RunRecord`
- `VerificationReport`
- `FailurePostmortem`
- `ReportBundle`
- `ApprovalEvent`
- `DomainEvent`

### 3.3 Keep context scoped to the task

The system should not give every model every document, every prompt, and every event. Context assembly should be phase-specific and operator-specific.

### 3.4 Prefer simple durable infrastructure in v1

The first version should optimize for:

- local repeatability
- inspectable storage
- auditable execution
- easy restart and resume
- low operator burden

It should not optimize for:

- multi-tenant scale
- distributed workers
- complex workflow orchestration products
- overly specialized infrastructure too early

### 3.5 Reports are part of the product, not a final garnish

Every major phase should emit something readable by a human:

- literature screening report
- evidence summary
- hypothesis review packet
- experiment run summary
- verification report
- failure postmortem
- cycle summary

---

## 4. Phase Overview

The roadmap is organized into six phases.

### Phase 0 — Foundation and Local Runtime
Create the repo skeleton, canonical schemas, control plane, worker runtime, initial dashboard shell, model gateway, and durable state.

### Phase 1 — Research Intake and Source Retrieval
Create the first usable research intake loop: scoped problem -> internal/external retrieval -> title/abstract triage -> shortlist -> selective full-text escalation.

### Phase 2 — Literature Intelligence and Protocolization
Turn screened sources into evidence, hypotheses, critiques, and executable experiment plans.

### Phase 3 — Execution Lab MVP
Run experiments in isolated GPU-capable sandboxes, stream telemetry live, and allow the user to intervene without breaking the workflow.

### Phase 4 — Verification, Historical Comparison, and Failure Memory
Verify every experiment, compare results against internal history, and turn failures into reusable memory.

### Phase 5 — Pilot Evaluation and Hardening
Exercise the product end-to-end on a small public benchmark set plus internal research problems, harden the loop, and prepare the next architecture pass.

---

## 5. Phase 0 — Foundation and Local Runtime

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
- minimal dashboard shell

### 5.2 Work to implement

#### A. Repository and service skeleton

- Create the monorepo structure for API, worker, frontend, CLI, shared schemas, adapters, prompts, and tests.
- Define the first bounded contexts in code:
  - control plane
  - research memory
  - retrieval
  - literature intelligence
  - protocol compiler
  - execution
  - verification
  - reporting
- Add local bootstrapping for the whole stack.

#### B. Durable state

- Stand up PostgreSQL as the system of record.
- Enable `pgvector`.
- Create migration tooling.
- Add canonical tables for research cycles, jobs, events, papers, evidence, hypotheses, experiments, runs, verifications, reports, and approvals.

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
- Keep the UI intentionally thin but real from phase 0 onward.

#### E. Telemetry plumbing

- Add worker-to-UI streaming for:
  - active operator
  - current phase
  - job status
  - run status
  - recent log events
- Add pause, cancel, and resume hooks even if the first version is limited.

#### F. Model gateway

- Create a common adapter for LLM calls.
- Create a common adapter for embeddings. - Recommend Sentence Transformers for maximum portability
- Support both hosted and local models from day one.
- Support role-based model routing from day one, even if the first routing table is simple.

#### G. Dev ergonomics

- Add linting, formatting, static checks, and test scaffolding.
- Add local fixtures and sample research cycles.
- Add a small seed corpus for manual testing.

### 5.3 Deliverables

- Local stack boot script
- Monorepo structure
- Database migrations
- Shared schema package
- Initial dashboard shell
- Operator runtime skeleton
- Event stream and audit trail
- Model gateway interface

### 5.4 Exit criteria

Phase 0 is done when:

- A user can create a research cycle from the UI or CLI.
- The cycle is persisted and visible in the dashboard.
- A worker can claim a job, emit events, and update durable state.
- The UI can stream state changes without a manual refresh.
- One hosted model and one local model can both be invoked through the same gateway.
- The system can pause and resume a simple operator flow.

### 5.5 Out of scope

- Real literature intelligence
- Real experiment execution
- Verification logic
- Strong benchmark support

---

## 6. Phase 1 — Research Intake and Source Retrieval

### 6.1 Objective

Deliver the first genuinely useful research-assistant loop:

**scoped problem -> source retrieval -> title/abstract screening -> shortlist -> selective full-text escalation**

### 6.2 Work to implement

#### A. Research problem intake

- Create the `ResearchCharter` flow.
- Let the user define:
  - research question
  - task type
  - success metric
  - compute budget
  - novelty expectations
  - stop conditions
  - source scope
- Support updates to the charter as the cycle evolves.

#### B. Internal source registration

- Add internal corpus ingestion for:
  - notes
  - prior reports
  - papers
  - experiment summaries
  - run logs
  - selected code references if needed later
- Track provenance, timestamps, and source type.

#### C. arXiv metadata layer

- Build the arXiv metadata ingest path into PostgreSQL. - See the m-chimiste-arxiv-harvester-example for metadata scraping.  Also see kaggle-arxiv-example for a detailed way to download *all* of arxiv's metadata in a single go. Harvester is for incremental updates and kaggle is for initial population.
- Support three retrieval modes:
  - bulk metadata bootstrap
  - incremental metadata harvesting
  - on-demand query fallback
- Store enough structure for lexical search, vector search, date filtering, and source linking.

#### D. Retrieval and ranking

- Implement hybrid search across internal and external sources.
- Search title + abstract together, not separately.
- Rank results using:
  - lexical similarity
  - semantic similarity
  - recency
  - source relevance
  - novelty distance from internal history
- Deduplicate overlapping records.

#### E. Screening and escalation funnel

- Add paper lifecycle states:
  - retrieved
  - screened
  - shortlisted
  - html_fetched
  - pdf_fetched
  - evidence_extracted
- Require an escalation reason before deeper fetch.
- Prefer HTML full text before PDF when available.
- Track why a paper or document was shortlisted.

#### F. User-facing screening report

- Create a human-readable screening report that shows:
  - what was searched
  - what was found
  - what was shortlisted
  - why items were rejected or escalated
  - which sources came from internal memory vs external literature

### 6.3 Deliverables

- `ResearchCharter` intake flow
- Internal corpus adapter
- arXiv metadata adapter
- Search and rerank pipeline
- Screening and shortlist UI
- Escalation policy for HTML/PDF fetches
- Literature screening report

### 6.4 Exit criteria

Phase 1 is done when:

- A user can define a research problem and persist it as a charter.
- The system can retrieve relevant internal and external sources.
- The system screens title + abstract together and produces a ranked shortlist.
- Full text is fetched only for shortlisted items with an explicit reason.
- The user can review a readable screening report in the UI.

### 6.5 Out of scope

- Deep evidence extraction from all shortlisted papers
- Strong novelty scoring
- Automatic hypothesis generation
- Experiment execution

---

## 7. Phase 2 — Literature Intelligence and Protocolization

### 7.1 Objective

Convert screened sources into usable research reasoning:

**shortlist -> evidence -> hypothesis portfolio -> critique -> experiment plan**

### 7.2 Work to implement

#### A. Evidence extraction

- Add `EvidenceCard` creation from:
  - metadata-only reads
  - HTML full text
  - PDF text when required
  - internal reports and notes
- Extract structured evidence types such as:
  - claim
  - method
  - limitation
  - result
  - implementation detail
  - open question
- Preserve source depth so the system knows whether the evidence came from metadata or full text.

#### B. Contradiction and redundancy signals

- Add similarity and contradiction detection across evidence cards.
- Detect overlapping methods and repeated claims.
- Mark likely stale or superseded approaches using date and citation context where available.

#### C. Hypothesis portfolio

- Generate multiple candidate hypotheses.
- Require every hypothesis to cite its supporting evidence.
- Add a critique pass that scores for:
  - novelty
  - likely failure modes
  - redundancy
  - implementation feasibility
  - evaluation risk

#### D. Protocol compiler

- Convert a selected hypothesis into an `ExperimentSpec`.
- Require the spec to define:
  - baseline
  - variables
  - controls
  - success metric
  - expected artifacts
  - stop conditions
  - budget envelope
  - verification needs
- Reject under-specified ideas before code generation begins.

#### E. Task-scoped context assembly

- Build operator-specific context packing.
- Ensure the ideation model sees different context than the coding or verification model.
- Version prompt templates and retrieval recipes.

#### F. User-facing evidence and portfolio views

- Add views for:
  - evidence cards
  - hypothesis cards
  - critique summaries
  - experiment specs
- Add a readable hypothesis review packet.

### 7.3 Deliverables

- `EvidenceCard` pipeline
- Contradiction and redundancy layer
- Hypothesis generator and reviewer operators
- `ExperimentSpec` compiler and validator
- Context assembly rules
- Hypothesis review report

### 7.4 Exit criteria

Phase 2 is done when:

- The system can produce evidence cards from shortlisted sources.
- The system can generate multiple grounded hypotheses.
- Each hypothesis can be critiqued and ranked.
- At least one hypothesis can be converted into a valid `ExperimentSpec`.
- The user can inspect evidence, critiques, and experiment plans in the UI.

### 7.5 Out of scope

- High-throughput portfolio search
- Sophisticated theorem-prover-like planning
- Mature agent self-improvement loops

---

## 8. Phase 3 — Execution Lab MVP

### 8.1 Objective

Turn experiment plans into real local runs:

**experiment spec -> isolated workspace -> code change -> sandboxed execution -> artifacts -> live telemetry**

### 8.2 Work to implement

#### A. Workspace and patch flow

- Create per-experiment isolated workspaces.
- Track parent code lineage.
- Store patches or diffs as first-class artifacts.
- Make each workspace inspectable and replayable.

#### B. Execution sandbox

- Run generated or modified code inside containers.
- Support GPU passthrough.
- Support resource limits for:
  - runtime
  - memory
  - disk
  - GPU selection if relevant
- Default to network-off unless explicitly allowed by policy.

#### C. Preflight and dry run

- Add preflight checks for:
  - config completeness
  - dataset availability
  - artifact contract validity
  - metric parser availability
  - environment readiness
  - budget fit
- Add a lightweight dry-run path for fast feedback before expensive execution.

#### D. Automated low-risk execution

- Allow the scheduler to auto-run low-risk experiments within policy bounds.
- Keep expensive, unusual, or policy-exception runs behind explicit approval.
- Record why a run was allowed to auto-execute.

#### E. Live telemetry and intervention

- Stream logs, metrics, and resource usage to the UI.
- Let the user:
  - stop a run
  - pause queueing
  - reprioritize experiments
  - inspect intermediate output
- Preserve the full run history regardless of outcome.

#### F. Benchmark and task adapters

- Introduce benchmark/task profiles for the first ML problem classes.
- Keep the product architecture benchmark-agnostic even when initial pilots include public competition datasets.
- Focus on task structure rather than hardcoding a single benchmark source.

#### G. Run reporting

- Generate a readable run summary for each experiment with:
  - what changed
  - what was executed
  - key metrics
  - artifacts produced
  - initial interpretation

### 8.3 Deliverables

- Workspace manager
- Patch application flow
- Containerized execution runner
- GPU-capable runtime path
- Preflight and dry-run pipeline
- Telemetry streaming UI
- Run summary report

### 8.4 Exit criteria

Phase 3 is done when:

- An approved `ExperimentSpec` can be converted into a real run.
- The run executes in an isolated containerized environment.
- GPU-backed runs are supported where needed.
- The user can watch telemetry live and intervene.
- Each run produces a durable `RunRecord` and readable run report.
- Low-risk experiments can execute automatically within policy.

### 8.5 Out of scope

- Distributed compute scheduling
- Cluster-scale autoscaling
- Massive benchmark coverage

---

## 9. Phase 4 — Verification, Historical Comparison, and Failure Memory

### 9.1 Objective

Make the lab trustworthy:

**completed run -> verification -> historical comparison -> promotion or rejection -> postmortem**

### 9.2 Work to implement

#### A. Deterministic verification

- Verify every experiment.
- Add checks appropriate to the first ML tasks, including:
  - baseline comparison
  - metric sanity checks
  - split and schema validation
  - artifact presence and parseability
  - rerun requirement
- Separate run success from claim success.

#### B. Historical comparison

- Compare current runs to:
  - current cycle baseline
  - prior runs in the same cycle
  - prior runs across the internal lab history
- Surface whether the result is:
  - genuinely new
  - a regression
  - a repeat of prior work
  - uncertain or under-validated

#### C. Failure memory

- Classify failed runs into structured categories.
- Add `FailurePostmortem` generation with fields such as:
  - failure type
  - likely cause
  - evidence for the diagnosis
  - whether the failure invalidates the hypothesis or only the implementation
  - suggested next actions
- Feed failure memory back into ranking and search.

#### D. Promotion logic

- Define what it means for a result to be promoted from “completed run” to “accepted finding.”
- Require verification to pass before promotion.
- Keep report generation downstream of the verified state.

#### E. Reporting bundle

- Generate a human-readable verification bundle that explains:
  - what was tested
  - what changed versus baseline
  - what verification checks ran
  - whether the result is robust, tentative, or failed
  - what the recommended next step is

### 9.3 Deliverables

- Verification service
- Historical comparison engine
- Failure classifier
- `FailurePostmortem` schema and renderer
- Verification report view
- Promotion rules

### 9.4 Exit criteria

Phase 4 is done when:

- Every run automatically produces a verification result.
- Failed runs produce structured postmortems.
- Results are compared against historical internal work.
- Promotion only happens after verification.
- The user can inspect verification status and failure reasoning in the UI.

### 9.5 Out of scope

- Fully automatic publication workflows
- Broad multi-domain scientific verification packs

---

## 10. Phase 5 — Pilot Evaluation and Hardening

### 10.1 Objective

Prove the product on a small but meaningful set of research problems.

This phase validates the full loop against:

- a small public benchmark set for ML experimentation
- internal research problems using the existing corpus
- a few different task archetypes, not just one style of benchmark

### 10.2 Work to implement

#### A. Pilot benchmark pack

Create a compact pilot suite that covers at least:

- one tabular or structured prediction problem
- one text or retrieval-oriented problem
- one additional ML task archetype if local compute allows
- at least one internal research problem tied to the existing corpus

Public benchmarks may include competition-style datasets, but the system should be evaluated as a research co-scientist, not as a leaderboard optimization bot.

#### B. End-to-end runs

- Run full research cycles from charter through verification.
- Capture operator cost, model cost, runtime cost, and human time saved.
- Measure how often the literature funnel avoids unnecessary full-text reads.

#### C. Product hardening

- Improve reliability of retries and resume behavior.
- Improve UI clarity for events, reports, and intervention.
- Tighten policy defaults and budgets.
- Improve prompt versioning and experiment traceability.

#### D. Evaluation and review

- Evaluate:
  - quality of shortlisted literature
  - quality of evidence extraction
  - plausibility of hypotheses
  - execution success rate
  - verification pass rate
  - usefulness of failure postmortems
  - overall usefulness to a human researcher
- Identify what should move into the next architecture and what should stay deferred.

### 10.3 Deliverables

- Pilot benchmark suite
- Pilot evaluation dashboard
- End-to-end cycle reports
- Reliability fixes and operator tuning
- MVP review memo

### 10.4 Exit criteria

Phase 5 is done when:

- The product can complete end-to-end cycles without manual database intervention.
- The title/abstract-first funnel works in practice and avoids brute-force PDF ingestion.
- The system can execute and verify low-risk ML experiments locally.
- The user can inspect telemetry, reports, and postmortems in a usable UI.
- At least one internal research cycle produces a useful, credible report bundle.
- We are ready to lock the next version of `tech_context.md` and choose which scale-up work actually matters.

---

## 11. Cross-Cutting Workstreams

These workstreams begin early and continue through multiple phases.

### 11.1 Model strategy and prompt assets

- role-based model routing
- prompt versioning
- evaluation of model/task fit
- cost tracking by operator
- fallback behavior if a provider or local runtime fails

### 11.2 Observability

- structured logs
- operator traces
- run telemetry
- error classification
- UI surfaces for current status and recent failures

### 11.3 Testing strategy

- unit tests for state transitions and policies
- integration tests for retrieval, execution, and verification flows
- fixture-based tests for literature screening and run promotion
- replay tests for stored research cycles

### 11.4 Reporting and explainability

- readable markdown reports
- rendered report views in the UI
- evidence-linked recommendations
- clear “why this happened” summaries for shortlist, hypothesis, run, and verification states

### 11.5 Policy and safety

- budgets for full-text access and compute
- allowlists and denylists for networked execution
- approval handling for high-cost or unusual actions
- explicit policy records in durable state

---

## 12. Suggested Build Order Within the Team

If work is parallelized, the most sensible split is:

### Track A — Control Plane and UI
Owns research cycle creation, dashboard, event stream, approvals, and report rendering.

### Track B — Storage and Research Memory
Owns schemas, migrations, repositories, search views, and lineage.

### Track C — Retrieval and Literature Intelligence
Owns internal/external adapters, screening, evidence extraction, and hypothesis support.

### Track D — Execution and Verification
Owns workspaces, containers, telemetry, experiment runs, verification, and postmortems.

### Track E — Model Gateway and Prompt Infrastructure
Owns provider adapters, local/hosted model routing, embedding interfaces, and prompt asset management.

Even if one person is doing most of the work, this split is still useful because it prevents early code from becoming an undifferentiated blob.

---

## 13. Decisions That Should Be Locked Before Phase 0 Starts

The following decisions should be finalized before implementation begins in earnest:

- exact monorepo shape
- frontend stack for the local dashboard
- API framework choice
- migration tooling choice
- container runtime choice
- local GPU support strategy
- hosted model providers to support first
- local model runtime to support first
- report rendering approach in the UI
- artifact storage root and conventions

These belong in `tech_context.md`.

---

## 14. MVP Definition of Done

The first ML laboratory MVP should be considered complete when all of the following are true:

- A user can define a research problem and create a `ResearchCharter`.
- The system can search internal memory and arXiv metadata.
- The system triages literature using title + abstract together before deeper reading.
- HTML full text is preferred before PDF when deeper reading is required.
- The system can generate evidence, grounded hypotheses, and executable experiment specs.
- Low-risk experiments can run automatically in isolated GPU-capable sandboxes.
- The user can watch telemetry live and intervene when needed.
- Every run produces a `RunRecord`, a verification result, and if relevant, a structured failure postmortem.
- Historical internal work is used for comparison and interpretation.
- Every research cycle can produce a readable report bundle for a human researcher.

---

## 15. Immediate Next Step

The next document should be `tech_context.md`.

It should stay narrowly focused on implementation choices needed to unlock phases 0 through 2, including:

- local runtime setup
- service startup model
- package and dependency choices
- frontend stack
- database and migration tooling
- queue and worker setup
- container runtime and GPU support
- model provider strategy
- config and environment management
- coding standards and testing defaults

`system_patterns.md` defines the system shape.  
This implementation plan defines the build sequence.  
`tech_context.md` should define the concrete stack and developer workflow.
