# Phased Implementation Plan

**Product:** ML Laboratory Co-Scientist
**Role:** Planner
**Status:** Working Draft v3
**Scope:** Local small-scale ML laboratory MVP
**Last Updated:** 2026-03-21

---

## 1. Purpose

This document translates the current product and architecture direction into a practical build sequence.

It answers five questions:

1. What do we build first?
2. What can wait?
3. What should each phase prove before we move on?
4. Which workstreams can move in parallel?
5. How do `skill.md` support and the orchestrator API land in the roadmap instead of being vague future add-ons?

This plan is downstream of `prd.md` and `system_patterns.md` and should guide execution before we tighten package-level details in `tech_context.md`.

---

## 2. Planning Assumptions

This implementation plan assumes the following product decisions are already in force:

- The system is **research-problem-first**, not competition-first.
- The first release is an **ML laboratory**, not a general-purpose science platform.
- The system works against **both internal and external sources**.
- arXiv discovery is **metadata-first**, with **title + abstract reviewed together** before any deeper read. (See kaggle-arxiv-example.txt and arxiv-harvester example)
- arXiv escalation follows **metadata -> HTML full text when possible -> PDF only when necessary**.
- The system should run **automated low-risk experiments** without requiring a human to approve every run.
- The user still needs a **live control surface** for progress, telemetry, intervention, and steering.
- The execution layer must support **GPU-capable isolated workloads**.
- Different workflow stages may use **different models** through a common gateway.
- Every experiment should produce a **run record**, a **verification record**, and if it fails, a **structured postmortem**.
- Historical internal work matters. The system should compare new outputs to **prior internal runs and research memory**, not just the current baseline.
- Modular behavior must be supported through **`skill.md` packages**.
- External orchestrators must be supported through a **stable control-plane API and telemetry stream**.

---

## 3. Delivery Principles

### 3.1 Build vertical slices, not disconnected subsystems

Each phase should end with a real loop that a human or orchestrator can use, inspect, and critique.

### 3.2 Stabilize the artifact model early

The most important early decision is the durable shape of the research record.

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
- `SkillDefinition`
- `SkillBinding`
- `SkillExecutionRecord`
- `OrchestratorClient`
- `ApprovalEvent`
- `DomainEvent`

### 3.3 Keep context scoped to the task

The system should not give every model every document, every prompt, and every event. Context assembly should be phase-specific, operator-specific, and skill-aware.

### 3.4 Prefer simple durable infrastructure in v1

The first version should optimize for:

- local repeatability
- inspectable storage
- auditable execution
- easy restart and resume
- low operator burden
- headless API access

### 3.5 Reports are part of the product

Every major phase should emit something readable:

- literature screening report
- evidence summary
- hypothesis review packet
- experiment run summary
- verification report
- failure postmortem
- cycle summary

### 3.6 Skills and API support start early

Skill support and orchestrator access should not be backfilled late. They affect state shape, event design, security boundaries, and operator contracts from day one.

---

## 4. Phase Overview

The roadmap is organized into six phases.

### Phase 0 — Foundation, Shared State, Skill Skeleton, and API Spine
Create the repo skeleton, canonical schemas, control plane, worker runtime, initial dashboard shell, skill loader, event stream, and orchestrator-facing API foundation.

### Phase 1 — Research Intake and Literature Triage
Create the first useful research loop: scoped problem -> internal/external retrieval -> title/abstract screening -> shortlist -> selective HTML/PDF escalation.

### Phase 2 — Evidence, Hypotheses, Protocols, and Phase Skills
Turn screened sources into evidence, hypotheses, critiques, and executable experiment plans. Expand the first-party skill library.

### Phase 3 — Execution Lab MVP and Live Control
Run experiments in isolated GPU-capable sandboxes, stream telemetry live, and allow both humans and orchestrators to intervene safely.

### Phase 4 — Verification, Historical Comparison, and Failure Memory
Verify every experiment, compare against internal history, and turn failures into reusable memory.

### Phase 5 — Pilot Hardening and Ecosystem Readiness
Exercise the product end-to-end on a small public benchmark set plus internal research problems, harden the loop, and validate skill/API interoperability.

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
- initial dashboard shell
- `skill.md` discovery and validation
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
- Add canonical tables for cycles, jobs, events, reports, skills, orchestrator clients, approvals, and lineage.

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
- skill discovery/validation skeleton
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

## 6. Phase 1 — Research Intake and Literature Triage

### 6.1 Objective

Deliver the first genuinely useful research-assistant loop:

```text
scoped problem
-> source retrieval
-> title + abstract screening
-> shortlist
-> selective HTML/PDF escalation
-> literature report
```

### 6.2 Work to implement

#### A. Research intake

- Create `ResearchCharter` workflows for scoped ML problems.
- Add problem templates and source-scope selection.
- Support problem notes from both humans and orchestrators.

#### B. Internal and external source adapters

- Add internal corpus adapter.
- Add arXiv metadata warehouse integration. (See kaggle-arxiv-example.txt and arxiv-harvester example)
- Add targeted external retrieval adapter where needed.
- Add metadata dedupe across sources.

#### C. Literature triage

- Implement title + abstract joint scoring.
- Track shortlist decisions and reasons.
- Implement HTML-first escalation and PDF fallback.
- Capture deeper-read rationale.

#### D. Reporting

- Generate a readable literature screening packet.
- Surface shortlist reasoning in the UI.
- Make reports retrievable over API.

#### E. Skills

- Add first-party literature skills such as:
  - problem scoping support
  - title/abstract triage
  - shortlist critique
  - escalation rationale drafting

#### F. API

- Expose source retrieval status and literature reports over API.
- Stream literature triage events in real time.

### 6.3 Deliverables

- research charter UI/API flow
- source adapters for internal corpus and arXiv metadata (See kaggle-arxiv-example.txt and arxiv-harvester example)
- title/abstract triage operator
- shortlist report bundle
- first literature skill set
- API endpoints for source state and reports

### 6.4 Exit criteria

Phase 1 is done when:

- a user can define a research problem and run literature intake end to end
- the system can search internal corpus plus arXiv metadata
- shortlisted papers show why they were selected
- deeper reads are recorded with reasons
- the literature screening report is viewable in the UI and API
- an orchestrator can monitor triage progress without scraping the UI

---

## 7. Phase 2 — Evidence, Hypotheses, Protocols, and Phase Skills

### 7.1 Objective

Turn screened sources into executable research plans.

### 7.2 Work to implement

#### A. Evidence extraction

- turn shortlisted sources into `EvidenceCard`s
- support conflict and redundancy signals
- preserve provenance and read depth

#### B. Hypothesis portfolio

- generate multiple candidate hypotheses
- critique and rank them
- store portfolio state and decision rationale

#### C. Protocol compiler

- create `ExperimentSpec`s from approved hypotheses
- define baseline, controls, metrics, artifacts, stop conditions, and expected outputs
- reject under-specified ideas

#### D. Skills

- add first-party skills for:
  - evidence extraction
  - novelty critique
  - protocol drafting
  - benchmark/problem-specific context shaping
- add skill tests and examples

#### E. API

- expose hypothesis cards, experiment specs, and portfolio ranking through the API
- allow orchestrators to request a hypothesis review or protocol compilation job

### 7.3 Deliverables

- evidence extraction operators
- hypothesis portfolio manager
- protocol compiler
- first protocol and critique skills
- hypothesis and protocol API resources

### 7.4 Exit criteria

Phase 2 is done when:

- the system can produce evidence cards from shortlisted sources
- at least three candidate hypotheses can be generated and ranked for a problem
- the chosen hypothesis compiles into a valid `ExperimentSpec`
- skills can influence context assembly and outputs in a recorded way
- an orchestrator can inspect the portfolio and request the next operator step through the API

---

## 8. Phase 3 — Execution Lab MVP and Live Control

### 8.1 Objective

Run experiments in isolated GPU-capable environments and make the process observable and steerable.

### 8.2 Work to implement

#### A. Workspace and execution runtime

- create per-run git worktrees
- support base images and on-demand image builds
- execute runs in sandboxed containers with optional GPU passthrough
- capture logs, metrics, resource usage, and artifacts

#### B. Telemetry and controls

- stream run telemetry to UI and API
- add pause, cancel, and retry actions
- show current operator, current run, and queue state

#### C. Automation policy

- allow low-risk automated experiment execution
- keep long-running, expensive, or sensitive actions behind policy thresholds

#### D. Skills

- add coding, experiment repair, and evaluator skills
- capture skill usage in run lineage

#### E. API

- expose run-control endpoints
- expose live run telemetry streams
- let orchestrators pause or cancel allowed runs

### 8.3 Deliverables

- execution runner
- GPU-capable sandbox path
- run telemetry stream
- run-control UI
- run-control API
- first coding and evaluation skills

### 8.4 Exit criteria

Phase 3 is done when:

- the system can execute a real experiment in an isolated workspace
- live run telemetry is visible in the UI
- an allowed external client can monitor and interrupt a run through the API
- automated low-risk experiments can proceed without manual approval at every step
- skill usage is visible in run lineage and reports

---

## 9. Phase 4 — Verification, Historical Comparison, and Failure Memory

### 9.1 Objective

Make results credible and reusable.

### 9.2 Work to implement

#### A. Verification

- run deterministic checks for every experiment
- compare results against current baseline and historical internal work
- enforce artifact and metric sanity checks

#### B. Failure memory

- classify failures
- create structured `FailurePostmortem` records
- feed postmortem insights back into retrieval and ranking

#### C. Reporting

- create verification reports and cycle summaries
- surface historical comparisons clearly

#### D. Skills

- add postmortem and verification-summary skills
- let skills suggest follow-up searches or protocol updates based on failures

#### E. API

- expose verification reports and postmortems through API
- allow orchestrators to fetch structured summaries and next-step recommendations

### 9.3 Deliverables

- verification subsystem
- postmortem generator
- historical comparison views
- verification/report APIs
- first postmortem/reflection skills

### 9.4 Exit criteria

Phase 4 is done when:

- every run results in a verification outcome
- failed or rejected runs generate structured postmortems
- the system can compare a new run to prior internal work
- reports make it obvious whether a result is robust, tentative, or rejected
- an orchestrator can monitor verification outcomes and retrieve report bundles over API

---

## 10. Phase 5 — Pilot Hardening and Ecosystem Readiness

### 10.1 Objective

Validate the full loop on real workloads and prepare for broader use.

### 10.2 Work to implement

#### A. Pilot exercises

- run the product on a small public benchmark set, including selected Kaggle competitions where appropriate
- run the product on internal research problems
- evaluate literature triage quality against arXiv metadata and internal corpus tasks

#### B. Hardening

- improve recovery behavior and resume flows
- improve report quality and timeline views
- tighten policy defaults and skill validation
- add API contract and compatibility tests

#### C. Skill ecosystem readiness

- publish a small first-party skill library
- add sample custom skill packages
- document skill authoring and testing

#### D. Orchestrator readiness

- provide a simple client SDK
- test end-to-end usage from an external orchestrator harness
- validate monitoring, intervention, and report retrieval workflows

### 10.3 Deliverables

- pilot evaluation results
- hardened policy and recovery behaviors
- first-party skill pack set
- simple orchestrator client SDK
- updated docs and examples

### 10.4 Exit criteria

Phase 5 is done when:

- the full cycle works across at least a few representative ML problems
- reports are credible enough for day-to-day researcher use
- skills can be added or modified without changing the shared core
- an external orchestrator can drive a full cycle through API with observability and control
- the system is ready for the next architecture pass rather than still behaving like a prototype demo

---

## 11. Cross-Cutting Workstreams

These workstreams cut across every phase.

### 11.1 Model routing and context management

- role-based routing
- local plus hosted model support
- context budgeting and skill-aware assembly

### 11.2 Policy and approval model

- run thresholds
- model usage policy
- deeper-read budgets
- orchestrator permission scopes

### 11.3 Skill library

- first-party skills
- custom skill examples
- skill validation and testing
- skill docs and templates

### 11.4 API and telemetry

- versioned schemas
- event streams
- client SDKs
- contract tests

### 11.5 Reporting UX

- rendered markdown
- timeline views
- report bundle navigation
- postmortem readability

### 11.6 Testing and fixtures

- problem fixtures
- literature fixtures
- skill fixtures
- execution sandbox fixtures
- API fixtures

---

## 12. MVP Definition of Done

The MVP is done when all of the following are true:

- a researcher can create a scoped ML research cycle and run it end to end
- the system can retrieve internal and external sources and triage literature with title + abstract together
- deeper reads are selective, reasoned, and recorded
- hypotheses and experiment specs are evidence-backed and durable
- experiments run in isolated GPU-capable sandboxes
- every experiment is verified and failures get postmortems
- reports are readable in the UI and available over API
- the system supports a meaningful first-party `skill.md` library plus custom skills
- an orchestrator agent can create, monitor, and steer a cycle over API without bypassing policy

---

## 13. Suggested Immediate Next Step

Use `tech_context.md` to lock the first-pass stack and implementation details for:

- the skill package format and loader
- the orchestrator API resources and streaming approach
- the local runtime and execution backplane
- the first three first-party skill packs
