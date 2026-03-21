# System Patterns

**Product:** ML Laboratory Co-Scientist  
**Role:** Architect  
**Status:** Working Draft v3  
**Scope:** Local small-scale ML laboratory MVP  
**Last Updated:** 2026-03-21

---

## 1. Purpose

This document defines the canonical architecture for the ML Laboratory Co-Scientist.

It answers five questions:

1. What is the system made of?
2. How do the major parts relate to each other?
3. What architectural patterns are required for the product to stay reliable, explainable, and extensible?
4. How do `skill.md` packages fit into the architecture without turning the system into prompt spaghetti?
5. How should external orchestrator agents use and monitor the lab without bypassing policy or provenance?

This document is architecture-first. It defines shape, boundaries, data flow, and major patterns. It does not pin package versions; those belong in `tech_context.md`.

It is downstream of `prd.md` and upstream of `phased_implementation_plan.md` and `tech_context.md`.

---

## 2. Architecture Summary

The ML Laboratory Co-Scientist should be built as a **stateful research operating system**, not as a swarm of agents chatting in the dark.

The core architectural decision is:

> The system runs as typed operators over a shared `ResearchState`, backed by durable storage, explicit policy, modular skills, and an append-only audit trail.

The product is organized around three loops:

1. **Explore** — problem framing, source retrieval, literature screening, evidence synthesis.
2. **Experiment** — hypothesis portfolio management, protocol compilation, code generation, sandboxed execution.
3. **Verify** — deterministic checks, historical comparison, structured postmortems, report generation.

Two horizontal layers now cut across all three loops:

- **Skill layer** — `skill.md` packages that add modular behavior, context rules, and optional deterministic hooks.
- **Orchestrator API layer** — a stable control-plane surface for external agents to create, monitor, and steer work.

---

## 3. System Design Principles

### 3.1 Local-first by default

The system must run on a single developer workstation without requiring cluster orchestration or multi-tenant infrastructure.

### 3.2 Shared state over agent conversation

Durable state lives in structured records, artifacts, skill bindings, and audit events. Prompt history is not the source of truth.

### 3.3 Task-scoped context over global context dumping

Each operator and each skill should receive only the context needed for that task. The system must not hand every model the entire corpus, event log, and research history.

### 3.4 Metadata before full text

Literature discovery must follow the same funnel a careful researcher would use:

```text
title + abstract together
-> shortlist
-> HTML or other machine-readable full text when needed
-> PDF only when necessary
```

### 3.5 Deterministic core, probabilistic edge

LLMs are useful for synthesis, ideation, critique, and report drafting. They should not own bookkeeping, policy, lineage, or state transitions.

### 3.6 Evidence before hypothesis, hypothesis before code

The system should move through durable intermediates instead of collapsing directly from retrieval into execution.

### 3.7 Skills are modular overlays, not shadow architecture

Skills should extend the system in explicit, inspectable ways. A skill may influence context assembly, prompting, heuristics, or deterministic helper logic, but it does not become a hidden second control plane.

### 3.8 API-first control plane

Everything the UI can do should flow through the control-plane API so humans and orchestrator agents share the same operational surface.

### 3.9 Reproducibility is a first-class feature

Every accepted claim must be traceable to evidence, prompts, code lineage, runtime environment, verification results, and approvals.

### 3.10 Human control for irreversible or external actions

The system may automate low-risk work, but it must expose telemetry, intervention points, and approval boundaries.

### 3.11 Narrow now, extensible later

The architecture should generalize cleanly later, but the first product is an ML laboratory.

---

## 4. Top-Level System Shape

### 4.1 Runtime topology

```text
+-------------------------------------------------------------------+
|                    User Surfaces and Consumers                     |
|     Web UI   |   CLI   |   External Orchestrators / Agents        |
+-------------------------------+-----------------------------------+
                                |
                                v
+-------------------------------------------------------------------+
|                    Control Plane and API Layer                     |
|  - research cycle API                                              |
|  - orchestrator API                                                |
|  - approvals and policy entrypoints                                |
|  - report and artifact endpoints                                   |
|  - event and telemetry streams                                     |
+------------------------+----------------------+--------------------+
                         |                      |
                         |                      |
                         v                      v
              +--------------------+   +----------------------------+
              | Durable State      |   | Worker / Operator Runtime  |
              | - Postgres         |   | - intake                   |
              | - pgvector         |   | - retrieval                |
              | - jobs             |   | - literature               |
              | - audit/events     |   | - ideation                 |
              | - skill registry   |   | - protocol compilation     |
              +---------+----------+   | - execution                |
                        |              | - verification             |
                        |              | - reporting                |
                        |              +-------------+--------------+
                        |                            |
                        v                            v
              +--------------------+   +----------------------------+
              | Artifact Store     |   | Skill Runtime              |
              | local filesystem   |   | - skill discovery          |
              | reports, runs,     |   | - validation               |
              | logs, literature,  |   | - binding / resolution     |
              | patches            |   | - execution records        |
              +---------+----------+   +-------------+--------------+
                        |                            |
                        +-------------+--------------+
                                      |
                                      v
                         +-----------------------------+
                         | Execution Runner            |
                         | git worktree + containers   |
                         | GPU-capable sandbox         |
                         +-------------+---------------+
                                       |
                                       v
                         +-----------------------------+
                         | External / Local Adapters   |
                         | - internal corpus           |
                         | - arXiv metadata warehouse  |
                         | - targeted external search  |
                         | - HTML / PDF fetchers       |
                         | - LLM / embeddings gateway  |
                         | - git                       |
                         | - container runtime         |
                         +-----------------------------+
```

### 4.2 Architectural stance

The system is not built around freeform agent-to-agent message passing.

It is built around:

- typed records
- explicit state transitions
- operator execution with durable inputs and outputs
- skill bindings with declared permissions and context needs
- append-only audit events
- isolated experiment workspaces
- policy-checked approvals
- API-mediated intervention and observation

That is what makes the lab debuggable.

---

## 5. Core Architectural Patterns

### 5.1 Shared `ResearchState` as source of truth

Each research cycle is represented by a durable `ResearchState`. Operators and skills do not own hidden state.

A `ResearchState` should reference, at minimum:

- `ResearchCharter`
- scoped problem definition
- source retrieval sessions
- `PaperCard` or `SourceRecord` entities
- `EvidenceCard` entities
- `HypothesisCard` portfolio
- `ExperimentSpec` queue
- `RunRecord` history
- `VerificationReport` history
- `FailurePostmortem` history
- `ReportBundle` history
- `SkillBinding` and `SkillExecutionRecord` history
- budget state
- approval state
- audit events

Why this pattern exists:

- makes the system restartable
- makes work inspectable without replaying prompt history
- allows deterministic tests against stored state
- prevents hidden memory drift from becoming system behavior

### 5.2 State machine orchestration

The lab should be implemented as a state machine over a research cycle, not as a freeform conversation.

A typical cycle might move through states like:

```text
created
-> chartered
-> retrieval_ready
-> literature_screened
-> evidence_ready
-> portfolio_ready
-> protocol_ready
-> running
-> verifying
-> reporting
-> closed
```

Pattern rule: an operator may only move the cycle to an allowed next state and must emit the event that explains why.

### 5.3 Event-sourced audit trail

The system should keep an append-only audit log of domain events. This is not full event sourcing for every read model, but it is a durable event trail for every meaningful action.

Example event types:

- `research_charter_created`
- `source_query_planned`
- `paper_title_abstract_screened`
- `paper_shortlisted`
- `fulltext_fetch_requested`
- `fulltext_fetch_approved`
- `evidence_extracted`
- `skill_bound_to_operator`
- `skill_executed`
- `hypothesis_generated`
- `experiment_spec_created`
- `run_started`
- `run_failed`
- `run_verified`
- `postmortem_created`
- `report_bundle_created`
- `approval_requested`
- `approval_recorded`
- `orchestrator_command_received`

Why this pattern exists:

- lets humans reconstruct what happened
- supports debugging and future analytics
- preserves approval history
- powers UI telemetry and orchestrator streams
- provides a durable lab notebook backbone

### 5.4 Ports and adapters / hexagonal architecture

External systems must sit behind adapters. Core research logic should not know the details of a source API, the LLM provider, or the container runtime.

The core should depend on interfaces such as:

- `LiteratureAdapter`
- `CorpusAdapter`
- `ExternalSearchAdapter`
- `LLMAdapter`
- `EmbeddingAdapter`
- `ExecutionAdapter`
- `ReportAdapter`
- `SkillProvider`
- `OrchestratorAuthProvider`

Why this pattern exists:

- makes the product testable with fixtures and mocks
- contains external API churn
- keeps business rules independent from vendors
- makes future generalization possible without rewriting the core

### 5.5 Metadata-first retrieval funnel

The literature subsystem must preserve the difference between:

1. metadata-only evidence
2. full-text evidence
3. implementation details extracted from deeper reading

A paper should move through lifecycle states such as:

```text
retrieved
-> title_abstract_screened
-> shortlisted
-> html_fetched
-> pdf_fetched
-> evidence_extracted
```

Pattern rule: metadata screening happens by default; deeper fetch is an exception that requires a reason.

Allowed reasons:

- high triage score
- conflict resolution
- implementation detail needed for experiment design
- explicit human or orchestrator request allowed by policy

### 5.6 Portfolio search, not greedy search

The system should maintain a ranked portfolio of hypotheses and experiment specs rather than following one proposal to completion before considering alternatives.

This means:

- multiple hypotheses can survive review
- multiple experiment specs can be queued
- failure memory informs future ranking
- the scheduler can pick the next experiment by expected value, not creation order

Suggested ranking factors:

- expected information gain
- implementation feasibility
- estimated runtime and cost
- novelty relative to internal history and prior literature
- risk of invalid evaluation
- fit to the charter

### 5.7 Skill package pattern

A skill is a modular behavior pack rooted in a `skill.md` file.

A skill package should support:

- metadata and version information
- description of when to use the skill
- declared inputs and outputs
- context requirements
- permitted models or preferred routing
- capability requirements and policy hints
- examples and tests
- optional deterministic helper hooks

Recommended skill package shape:

```text
skills/
  literature/
    title_abstract_triage/
      skill.md
      hooks.py                # optional
      fixtures/               # optional
      tests/                  # optional
      schemas/                # optional
```

Pattern rules:

- skills are discovered from configured paths
- skills must validate before activation
- skills may request context, not global state
- skills may not bypass policy, approvals, or durable state writes
- every skill execution must emit a `SkillExecutionRecord`

Why this pattern exists:

- allows custom and modular behavior
- keeps domain-specific instructions inspectable and reusable
- prevents skill logic from dissolving into random prompts in application code
- makes external agent compatibility easier

### 5.8 Ephemeral workspaces with durable lineage

Every proposed experiment should execute in its own isolated workspace, ideally backed by a git worktree or equivalent branch directory.

Each run should capture:

- source commit or parent branch
- generated patch or diff
- problem profile
- runtime image or environment id
- prompt and model identifiers used during generation
- bound skills used during generation or review
- seeds
- dataset hash or cache reference
- produced artifacts and metrics

### 5.9 Containerized execution sandbox

Generated or modified code must not execute directly on the host environment.

The execution pattern for the MVP should be:

- build or reuse a problem-specific base image
- mount dataset cache read-only where possible
- mount workspace read-write
- mount artifact output directory
- disable network by default
- enforce time and memory limits
- allow GPU passthrough only through explicit runtime policy
- capture stdout, stderr, exit code, and resource usage

### 5.10 Deterministic verification before promotion

Verification should be its own subsystem, not an optional postscript.

Before a run is promoted from promising to accepted, the system should perform deterministic checks appropriate to the research problem:

- compare against declared baseline
- compare against relevant historical internal work
- rerun or replay checks as required by policy
- split and schema validation checks
- artifact presence checks
- metric sanity checks
- output contract validation
- postmortem creation on failure or rejection

LLMs may summarize or interpret verification results, but they do not replace the verification itself.

### 5.11 Policy engine for budgets and approvals

A separate policy layer should decide whether an operator, skill, or orchestrator action may proceed.

The policy layer must handle:

- compute budget ceilings
- full-text read ceilings
- allowed hardware profiles
- network access permissions
- long-running job thresholds
- model usage policy
- skill capability policy
- orchestrator permission scopes

### 5.12 External orchestrator API pattern

External orchestrators must interact with the lab through the control-plane API, not by writing directly to the database or manipulating workspaces.

The API pattern should be:

- versioned REST endpoints for durable resources
- streaming telemetry through SSE first
- stable JSON payloads and ids
- explicit actor identity for every action
- policy checks before side effects
- artifact and report retrieval via signed or internal local paths exposed through the API

Core orchestrator actions should include:

- create or resume a research cycle
- request operator or skill execution
- read state snapshots and reports
- subscribe to domain events and run telemetry
- add guidance or notes
- pause, cancel, or resume allowed work
- approve or reject gated actions where policy allows

Why this pattern exists:

- makes the lab usable by higher-level agent systems
- avoids brittle UI automation
- keeps all control and monitoring in one durable surface

### 5.13 Derived graph views, not a graph database in v1

The system should store core entities in relational tables and derive graph views when needed.

Examples of graph views:

- citation relationships
- evidence-to-hypothesis links
- hypothesis-to-experiment lineage
- repeated method families
- contradiction clusters
- skill-to-operator usage graphs
- orchestrator-to-cycle action graphs

---

## 6. Recommended MVP Stack Shape

This section defines the canonical architectural stack shape for the MVP.

| Area | Default choice | Why this is the default |
|---|---|---|
| Core language | Python | Best fit for ML workflows, orchestration, adapters, and scientific tooling |
| API / control plane | FastAPI-style Python service | Good typed contracts, async support, OpenAPI generation, local simplicity |
| Durable state | PostgreSQL | Strong transactional model, row locking, JSON, and good fit for queue + state |
| Vector retrieval | pgvector in PostgreSQL | Keeps vector search close to canonical state in v1 |
| Full-text / lexical retrieval | PostgreSQL full-text search | Good enough for metadata-first paper search in v1 |
| Artifact store | Local filesystem | Fits local-first deployment and keeps artifacts inspectable |
| Job queue | Database-backed queue | Simpler than a separate queue service in a single-user MVP |
| Execution isolation | Docker or Podman containers | Practical local sandbox for generated code |
| Workspace isolation | Git worktrees | Clean per-experiment code isolation with clear lineage |
| UI surface | Web UI plus CLI | We want a real phase-1 UI, not CLI only |
| LLM access | Provider-agnostic gateway adapter | Prevents coupling to a single model vendor |
| Embeddings | Provider-agnostic embedding adapter | Allows hosted and local options |
| Skill packages | `skill.md` rooted packages | Human-readable, coding-agent-friendly extension surface |
| Orchestrator integration | REST + SSE over the same control plane | Headless-first, simple, observable, and easy to test |
| Reporting | Markdown rendered in the UI | Easy to diff, store, and inspect |

---

## 7. Major Bounded Contexts

### 7.1 Control Plane

Responsibility:

- create and update `ResearchCharter`
- expose API and CLI commands
- coordinate approvals
- enqueue work for operators
- expose current lab state to users and orchestrators

### 7.2 Research Memory

Responsibility:

- persist all durable entities and relationships
- support retrieval over sources, evidence, hypotheses, runs, notes, reports, and failures
- maintain audit history and job records

Primary record types:

- `ResearchCharter`
- `ResearchState`
- `ProblemProfile`
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
- `ApprovalEvent`
- `DomainEvent`
- `OrchestratorClient`

### 7.3 Source Intake

Responsibility:

- retrieve internal corpus metadata and selected content
- maintain an arXiv metadata warehouse
- perform targeted external retrieval
- fetch HTML or PDF only when explicitly escalated

### 7.4 Literature Intelligence

Responsibility:

- score titles and abstracts together
- deduplicate results across sources
- produce shortlist recommendations
- extract structured evidence from metadata or deeper reads
- preserve provenance and escalation rationale

### 7.5 Ideation and Review

Responsibility:

- generate candidate hypotheses from evidence
- critique for novelty, weakness, redundancy, and likely failure modes
- rank the portfolio before protocol compilation

### 7.6 Protocol Compiler

Responsibility:

- convert approved hypotheses into executable `ExperimentSpec`s
- define controls, baseline, metric, artifacts, stop conditions, and expected outputs
- reject under-specified ideas before code generation begins

### 7.7 Skill Registry and Runtime

Responsibility:

- discover `skill.md` packages from configured roots
- validate skill metadata and structure
- resolve which skills are available for a given operator or research cycle
- record skill activation and execution history
- expose skill catalog and status through UI and API

Pattern note: the skill runtime is part of the core product surface. It is not an afterthought bolted onto prompts.

### 7.8 Build and Execution Lab

Responsibility:

- create isolated workspaces
- apply code changes
- prepare runtime images or environments
- execute runs within policy limits
- capture outputs into `RunRecord`

### 7.9 Verification

Responsibility:

- compare runs to baseline and historical work
- rerun or replay where required
- run leakage and evaluation checks
- create `VerificationReport`
- create `FailurePostmortem` records when needed

### 7.10 Reporting and Lab Notebook

Responsibility:

- generate concise human-readable summaries
- produce markdown report bundles per cycle
- summarize literature screening, selected papers, experiments, verification, and open questions

### 7.11 Approvals and Policy

Responsibility:

- enforce approval requirements
- block disallowed actions
- persist approval history
- expose pending approvals to the user and, where permitted, orchestrators

### 7.12 Orchestrator Gateway

Responsibility:

- authenticate external orchestrators
- expose versioned research-cycle and run APIs
- expose SSE telemetry streams
- enforce orchestrator permission scopes
- record all external control actions as domain events

Pattern note: in v1 this is a logical boundary inside the control-plane service, not a separate deployment.

---

## 8. Primary Data and Lineage Model

### 8.1 Canonical research lineage

```text
SourceRecord / PaperCard
    -> EvidenceCard
        -> HypothesisCard
            -> ExperimentSpec
                -> RunRecord
                    -> VerificationReport
                        -> ReportBundle / AcceptedFinding
```

### 8.2 Skill and orchestration lineage

```text
SkillDefinition
    -> SkillBinding
        -> SkillExecutionRecord
            -> OperatorReport / DomainEvent

OrchestratorClient
    -> OrchestratorSession
        -> OrchestratorCommand
            -> DomainEvent / ApprovalEvent / Job
```

### 8.3 Important lineage rules

- A `HypothesisCard` must cite one or more `EvidenceCard`s.
- An `ExperimentSpec` must reference the `HypothesisCard` it operationalizes.
- A `RunRecord` must reference the exact `ExperimentSpec`, workspace lineage, and bound skills used.
- A promoted claim must reference at least one `VerificationReport`.
- A `FailurePostmortem` must reference the failed or rejected run and describe classification and next-step insight.
- A `SkillExecutionRecord` must reference the skill version, operator, research cycle, and outputs it influenced.
- Every orchestrator action must be attributable to an actor identity and appear in the audit trail.

---

## 9. Operator Contract Pattern

Operators should be implemented as typed units of work rather than arbitrary prompt calls.

A good mental model is:

```text
Operator(input_state, config, assembled_context, bound_skills)
  -> OperatorResult(
       state_patch,
       emitted_events,
       created_artifacts,
       approvals_requested,
       next_actions,
       operator_report,
       skill_execution_records
     )
```

Operator design rules:

- operators must be idempotent where practical
- operators must emit durable outputs before downstream work is queued
- prompts must be versioned and referenced in outputs
- skill applications must be explicit and recorded
- policy must be checked before side effects occur
- operator reports must be inspectable by a human or orchestrator

---

## 10. Critical Workflow Patterns

### 10.1 Research intake pattern

```text
problem statement
-> charter creation
-> source scope selection
-> policy initialization
-> baseline planning
```

### 10.2 Literature triage pattern

```text
problem context + baseline context
-> query planning
-> arXiv metadata retrieval
-> internal corpus retrieval
-> targeted external retrieval
-> dedupe
-> title + abstract screening together
-> shortlist ranking
-> optional HTML fetch with reason
-> optional PDF fetch with reason
-> evidence extraction
```

### 10.3 Skill selection and execution pattern

```text
operator role + research state + policy
-> skill resolver
-> eligible skill set
-> context assembly
-> skill execution
-> skill execution record
-> operator output
```

Important rule: no skill executes as invisible prompt glue. It must leave lineage.

### 10.4 Hypothesis to experiment pattern

```text
evidence cards
-> hypothesis generation
-> critique / redundancy filtering
-> portfolio ranking
-> scheduler or human selects candidate
-> protocol compiler creates ExperimentSpec
-> preflight checks
-> build workspace and patch
-> execute
```

Important rule: no direct “paper insight -> code run” shortcut should bypass `ExperimentSpec`.

### 10.5 Verification and promotion pattern

```text
completed run
-> baseline comparison
-> historical comparison
-> metric sanity checks
-> rerun or replay checks
-> verification report
-> promoted finding or failure postmortem
```

### 10.6 External orchestrator control pattern

```text
orchestrator authenticates
-> opens or resumes session
-> subscribes to event stream
-> reads current state
-> issues allowed command
-> policy check
-> job creation / action result
-> events and reports returned
```

Important rule: external orchestrators can request work, not bypass the control plane.

---

## 11. Storage Pattern

### 11.1 System of record

The system of record should be:

- PostgreSQL for structured state, queueing, audit events, skill registry state, and vector references
- local filesystem for large artifacts and cached external assets

### 11.2 Filesystem layout pattern

```text
/data
  /artifacts
    /runs
    /reports
    /literature
    /patches
    /postmortems
  /cache
    /arxiv
    /embeddings
    /external
  /workspaces
  /exports

/repo
  /skills
```

### 11.3 Artifact philosophy

Artifacts should be treated as durable evidence, not temporary scratch by default.

This includes:

- run logs
- metric snapshots
- generated patches
- literature notes
- extracted evidence summaries
- rendered reports
- failure postmortems
- skill execution diagnostics

---

## 12. Search and Retrieval Pattern

The retrieval system should combine:

- lexical search over title, abstract, authors, tags, notes, and postmortems
- vector search over semantic embeddings
- structured filters such as source type, recency, problem relevance, and read state

At minimum there should be separate logical search views for:

- title and abstract metadata
- deeper full-text notes or extracted sections
- internal corpus documents
- historical run reports and failure memory
- skill catalog and examples

---

## 13. Execution Pattern

Each supported problem compiles into a `ProblemProfile` that defines:

- dataset or source references
- offline validation metric
- expected runtime envelope
- allowed hardware profile
- artifact contract
- known constraints
- optional external benchmark interfaces

For each candidate experiment:

```text
create isolated worktree
-> apply patch
-> preflight
-> execute in sandbox
-> collect artifacts
-> archive workspace metadata
-> optionally keep patch for review
```

Run failures should be classified rather than lumped together. Examples:

- build failure
- dependency failure
- OOM or resource limit
- runtime exception
- metric parse failure
- invalid artifact output
- policy rejection
- harness mismatch
- skill misuse or skill contract violation

---

## 14. Verification Pattern

A promoted result should generally have:

- baseline comparison on the declared metric
- comparison against relevant historical internal work
- confirmation that the intended split or evaluation surface was used
- confirmation that no configured leakage or contamination signals were detected
- required artifacts present and parseable
- a rerun or replay note
- a reviewer summary describing whether the improvement is robust, tentative, or likely spurious
- a postmortem if the result is rejected or inconclusive

---

## 15. Human and Orchestrator Interaction Pattern

The product should feel like a researcher’s control tower, not a black box.

### 15.1 Human interaction model

- use the UI to create or resume a cycle, inspect state, review reports, and intervene
- use the CLI for direct local control and debugging
- keep every recommendation linked to evidence and lineage

### 15.2 Orchestrator interaction model

- use the API to create cycles, query state, monitor events, and issue allowed commands
- provide scoped read and write permissions
- treat telemetry streams as the primary monitoring interface

### 15.3 Required approval surfaces

The user should be able to clearly review and approve or reject:

- deeper reads beyond budget
- expensive or long-running experiments
- network-enabled runs
- promotion of headline claims
- sensitive orchestrator-issued actions where policy requires confirmation

### 15.4 Explainability pattern

Every surfaced object should answer “why is this here?”

Examples:

- a shortlisted paper should show title/abstract score and escalation reason
- a hypothesis should show supporting evidence and critique summary
- a promoted run should show baseline and historical comparison
- a skill should show when and why it was bound to an operator
- an orchestrator action should show actor, scope, and result

---

## 16. Repository and Folder Structure Pattern

A practical repository shape for the MVP is:

```text
repo/
  apps/
    api/
    worker/
    web/
    cli/
  libs/
    schemas/
    core/
    orchestration/
    storage/
    retrieval/
    literature/
    ideation/
    protocols/
    execution/
    verification/
    reporting/
    skills/
    adapters/
      arxiv/
      corpus/
      external_search/
      llm/
      embeddings/
      git/
      container/
  prompts/
    planning/
    literature/
    ideation/
    coding/
    verification/
    reporting/
  skills/
    literature/
    ideation/
    coding/
    verification/
    reporting/
  configs/
    problems/
    policies/
    models/
    skills/
  docs/
    context/
      prd.md
      system_patterns.md
      phased_implementation_plan.md
      tech_context.md
  tests/
    unit/
    integration/
    e2e/
    fixtures/
```

Structure rules:

- canonical schemas live in one place
- prompts are versioned assets, not hidden strings in application code
- skills are repo-visible assets, not buried in application internals
- adapters must not invert dependencies
- benchmark and problem configs live in files, not prompt text

---

## 17. Key Architectural Decisions (ADR Snapshot)

- **ADR-001** — Build the core in Python.
- **ADR-002** — Use shared `ResearchState` instead of freeform agent memory.
- **ADR-003** — Choose PostgreSQL + pgvector as the canonical storage path.
- **ADR-004** — Use a database-backed job queue instead of a separate workflow engine in v1.
- **ADR-005** — Treat title + abstract together as the default literature surface.
- **ADR-006** — Prefer HTML or machine-readable full text before PDF when escalating paper reads.
- **ADR-007** — Support modular skill packages rooted in `skill.md`.
- **ADR-008** — Expose a versioned REST + SSE orchestrator API from the control plane.
- **ADR-009** — Execute generated code inside isolated containers and separate workspaces.
- **ADR-010** — Baseline first, always.
- **ADR-011** — Verification is separate from generation.
- **ADR-012** — Keep a real phase-1 UI instead of CLI only.

---

## 18. Explicit Anti-Patterns

The following approaches should be considered out of scope or explicitly rejected for the MVP:

1. Agent swarm as architecture.
2. Brute-force mirroring of arXiv full-text PDFs.
3. Giving every model the entire research history and corpus by default.
4. Running generated code directly on the host machine.
5. Using prompt text as policy logic.
6. Hiding custom behavior in undocumented ad hoc prompt fragments instead of skills, configs, or code.
7. Letting external orchestrators write directly to the database or execution runtime.
8. Jumping from hypothesis directly to code patch without protocolization.
9. Using notebooks as the product backbone.

---

## 19. Evolution Path

### Phase 1 — Local ML lab core

- single-user local runtime
- scoped research problems
- internal corpus retrieval
- arXiv metadata warehouse and literature triage
- skill registry and first-party skills
- orchestrator API and event stream
- experiment execution and verification loop

### Phase 2 — Better memory, richer UI, broader skill catalog

- stronger dashboard and timeline views
- richer historical comparison
- more robust skill packaging and validation
- broader first-party skill library

### Phase 3 — Optional scale-up

- optional remote workers
- object storage replacement for filesystem artifacts
- more advanced retrieval and ranking models
- optional MCP or other compatibility facades on top of the orchestrator API
- support for additional research domains through new adapters and skills

---

## 20. Open Questions

- Should third-party skills require signing or trust prompts in the first local release?
- Should orchestrator approvals ever count as equivalent to a human approval for specific scopes?
- When should we add WebSocket support in addition to SSE, if ever?
- Which parts of failure reflection should be standardized in shared core versus left to skill packages?
- How much skill-specific deterministic code should be allowed before a behavior should become part of the shared core?

---

## 21. Recommended Next Step

The next document should be `phased_implementation_plan.md`, which turns this architecture into a build sequence.
