# System Patterns

**Product:** Synthetos (ML Laboratory Co-Scientist)\
**Role:** Architect\
**Status:** Working Draft v4\
**Scope:** Local small-scale ML laboratory with autonomy roadmap\
**Last Updated:** 2026-04-09

---

## 1. Purpose

This document defines the canonical architecture for the ML Laboratory Co-Scientist.

It answers six questions:

1. What is the system made of?
2. How do the major parts relate to each other?
3. What architectural patterns are required for discovery, paper analysis, experimentation, verification, and autonomy?
4. How do `skill.md` packages fit into the architecture without turning the system into prompt spaghetti?
5. How should external orchestrator agents use and monitor the lab without bypassing policy or provenance?
6. How should we separate durable evidence artifacts from advisory review artifacts?

This document is architecture-first.  It defines shape, boundaries, data flow, and major patterns.  It does not pin package versions; those belong in `tech_context.md`.

It is downstream of `prd.md` and upstream of `phased_implementation_plan.md` and `tech_context.md`.

---

## 2. Architecture Summary

The ML Laboratory Co-Scientist should be built as a **stateful research operating system**, not as a swarm of agents chatting in the dark.

The core architectural decision remains:

> The system runs as typed operators over a shared `ResearchState`, backed by durable storage, explicit policy, modular skills, and an append-only audit trail.

The revised product is organized around four loops:

1. **Discover** — research intake, retrieval planning, multi-source search, ranking, shortlist formation, and discovery exports.
2. **Analyze** — selected-paper ingestion, typed paper graph construction, graph-aware QA, coverage verification, and paper analysis packets.
3. **Experiment** — evidence synthesis, hypothesis portfolio management, protocol compilation, sandboxed execution, verification, and reporting.
4. **Learn** — remediation, directional signal tracking, autonomous looping, failure memory, and cross-charter procedural patterns.

Two horizontal layers cut across all four loops:

- **Skill layer** — `skill.md` packages that add modular behavior, context rules, and optional deterministic hooks.
- **Orchestrator API layer** — a stable control-plane surface for external agents to create, monitor, and steer work.

---

## 3. System Design Principles

### 3.1 Local-first by default

The system must run on a single developer workstation without requiring cluster orchestration or multi-tenant infrastructure.

### 3.2 Shared state over agent conversation

Durable state lives in structured records, artifacts, skill bindings, and audit events.  Prompt history is not the source of truth.

### 3.3 Task-scoped context over global context dumping

Each operator and each skill should receive only the context needed for that task.

### 3.4 Metadata before full text

Literature discovery must follow the same funnel a careful researcher would use:

```text
title + abstract together
-> shortlist
-> HTML or other machine-readable full text when needed
-> PDF only when necessary
```

### 3.5 Two-depth paper analysis

Paper understanding should run at two depths:

- **automatic metadata-depth analysis** during discovery for ranking, relevance, and shortlist reasoning
- **deeper full-text analysis** only for shortlisted papers or later research steps that require richer evidence

### 3.6 Deterministic core, probabilistic edge

LLMs are useful for synthesis, ideation, critique, remediation, and report drafting.  They should not own bookkeeping, policy, lineage, or state transitions.

### 3.7 Evidence before hypothesis, hypothesis before code

The system should move through durable intermediates instead of collapsing directly from retrieval into execution.

### 3.8 Mechanical failures are not research findings

Dependency issues, timeouts, OOMs, parse failures, and invalid artifact outputs should route through a remediation path before they become first-class scientific reflections.

### 3.9 Signal matters more than binary pass-fail

Verification should not stop at baseline comparisons.  The architecture should support directional signal, frontier tracking, and autonomous decisioning.

### 3.10 Skills are modular overlays, not shadow architecture

Skills should extend the system in explicit, inspectable ways.  A skill may influence context assembly, prompting, heuristics, or deterministic helper logic, but it does not become a hidden second control plane.

### 3.11 API-first control plane

Everything the UI can do should flow through the control-plane API so humans and orchestrator agents share the same operational surface.

### 3.12 Review artifacts are advisory, not canonical evidence

Paper review outputs and LLM critiques may help prioritize attention, but canonical evidence must remain grounded in source records, paper analysis packets, verification artifacts, and durable state.

### 3.13 Narrow now, extensible later

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
|  - charter and cycle API                                           |
|  - orchestrator API                                                |
|  - discovery and analysis APIs                                     |
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
              | - pgvector         |   | - discovery                |
              | - jobs             |   | - paper analysis           |
              | - audit/events     |   | - ideation                 |
              | - skill registry   |   | - protocol compilation     |
              | - pattern memory   |   | - execution                |
              +---------+----------+   | - remediation              |
                        |              | - verification             |
                        |              | - reporting                |
                        |              +-------------+--------------+
                        |                            |
                        v                            v
              +--------------------+   +----------------------------+
              | Artifact Store     |   | Skill Runtime              |
              | local filesystem   |   | - skill discovery          |
              | reports, runs,     |   | - validation               |
              | discovery exports, |   | - binding / resolution     |
              | paper graphs,      |   | - execution records        |
              | patches            |   +-------------+--------------+
              +---------+----------+                 |
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
                         | - Semantic Scholar/OpenAlex |
                         | - HTML / PDF fetchers       |
                         | - LLM / embeddings gateway  |
                         | - graph / chunk utilities   |
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

Operators and skills do not own hidden state.

Use the following terminology:

- `ResearchCharter` = the project definition and top-level research container
- `ResearchCycle` = one bounded research loop executed within a charter
- `ResearchState` = the logical aggregate of everything that has occurred within a charter across its cycles; it is not a single database row but an aggregate assembled from associated artifacts and records

The system supports one active charter at a time due to GPU constraints.  Users can swap between charters but should not run them concurrently.

A `ResearchState` should reference, at minimum:

- `ResearchCharter`
- scoped problem definition
- discovery sessions and retrieval plans
- `SourceRecord` / `PaperCard` entities
- `DiscoveryView` artifacts
- `PaperAnalysisPacket` entities
- `PaperReviewArtifact` entities
- `EvidenceCard` entities
- `HypothesisCard` portfolio
- `ExperimentSpec` queue
- `RunRecord` history
- `VerificationReport` history
- `FailurePostmortem` history
- `RemediationAction` history
- `MetricFrontier` state
- `CanonicalPattern` links
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
-> discovery_ready
-> discovery_screened
-> analysis_ready
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

The system should keep an append-only audit log of domain events.  This is not full event sourcing for every read model, but it is a durable event trail for every meaningful action.

Example event types:

- `research_charter_created`
- `discovery_query_planned`
- `source_retrieval_executed`
- `paper_title_abstract_screened`
- `paper_shortlisted`
- `paper_analysis_requested`
- `paper_analysis_completed`
- `paper_review_completed`
- `fulltext_fetch_requested`
- `evidence_extracted`
- `skill_bound_to_operator`
- `skill_executed`
- `hypothesis_generated`
- `experiment_spec_created`
- `run_started`
- `run_failed`
- `run_remediation_attempted`
- `run_verified`
- `directional_signal_recorded`
- `frontier_updated`
- `postmortem_created`
- `canonical_pattern_updated`
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

External systems must sit behind adapters.  Core research logic should not know the details of a source API, the LLM provider, or the container runtime.

The core should depend on interfaces such as:

- `DiscoveryAdapter`
- `CorpusAdapter`
- `ExternalSearchAdapter`
- `PaperIngestionAdapter`
- `GraphExtractionAdapter`
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
3. structured analysis artifacts
4. advisory review artifacts

A paper should move through lifecycle states such as:

```text
retrieved
-> title_abstract_screened
-> shortlisted
-> html_fetched
-> pdf_fetched
-> paper_analysis_completed
-> evidence_extracted
```

Pattern rule: metadata screening happens by default; deeper fetch is an exception that requires a reason.

When full text is required:

- prefer HTML or other machine-readable full text first
- use PDF as a fallback when HTML is unavailable or low quality
- normalize both paths into the same internal full-text representation so downstream analysis does not branch on source format

### 5.6 Two-depth paper analysis pattern

Paper analysis should not be all-or-nothing.

**Depth 1: metadata analysis**

Runs automatically during discovery and produces lightweight reasoning over:

- title
- abstract
- authors
- venue
- year
- source
- likely method family
- likely contribution type
- shortlist rationale

**Depth 2: full analysis**

Runs only for shortlisted papers or later research steps that require richer evidence.  Produces:

- structure-aware chunks
- typed paper graph
- graph-aware QA index
- reproducibility notes
- coverage diagnostics
- linked figures and tables

Why this pattern exists:

- preserves the metadata-first funnel
- controls cost and latency
- allows deep analysis to re-enter the loop later for validation or regeneration

### 5.7 Separate-but-linked artifact pattern for analysis and review

Paper analysis and paper review should be stored as separate artifact types.

`PaperAnalysisPacket` should represent:

- structured extraction
- provenance-linked graph state
- coverage diagnostics
- locateable evidence
- reproducibility cues

`PaperReviewArtifact` should represent:

- strengths and weaknesses
- questions to investigate
- advisory critique
- optional scores or reviewer-style judgments

Pattern rules:

- both artifacts may reference the same paper and chunk provenance
- both may appear in the same report bundle
- review artifacts must not replace analysis packets as canonical paper-grounded evidence

### 5.8 Retrieval view pattern

The system should expose retrieval **views** rather than an unbounded menu of ranking modes.

Required v1 views:

- **Stable** — precise, reproducible, confidence-leaning retrieval
- **Discovery** — novelty- and diversity-leaning retrieval for adjacent work and overlooked ideas

Optional internal preset:

- **Balanced** may exist as an internal or API-only preset in v1 but need not be a mandatory user-facing mode

Why this pattern exists:

- simplifies UX and testing
- preserves two clearly distinct researcher workflows
- avoids early tuning sprawl

### 5.9 Portfolio search, not greedy search

The system should maintain a ranked portfolio of hypotheses and experiment specs rather than following one proposal to completion before considering alternatives.

This means:

- multiple hypotheses can survive review
- multiple experiment specs can be queued
- failure memory informs future ranking
- directional signal informs future ranking
- the scheduler can pick the next experiment by expected value, not creation order

### 5.10 Skill package pattern

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
      hooks.py
      fixtures/
      tests/
      schemas/
```

Pattern rules:

- skills are discovered from configured paths
- skills must validate before activation
- skills may request context, not global state
- skills may not bypass policy, approvals, or durable state writes
- every skill execution must emit a `SkillExecutionRecord`

### 5.11 Skill trust tier pattern

The first local release should use trust tiers rather than mandatory signing.

Suggested trust tiers:

- **first-party trusted** — enabled by default
- **user-local trusted** — explicit local opt-in
- **third-party untrusted** — manifest-visible but blocked from higher-risk behavior until approved

Higher-risk capabilities should require stronger trust, especially:

- Python hooks
- filesystem write access beyond allowed artifact paths
- network access
- run-control mutations

### 5.12 Ephemeral workspaces with durable lineage

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
- remediation lineage if applicable

### 5.13 Containerized execution sandbox

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

### 5.14 Auto-remediation pattern

Mechanical failures should route through a remediation subsystem before full postmortem handling.

The remediation pattern should be:

```text
run failure
-> deterministic failure classification
-> focused LLM remediation when class is known
-> broader debug remediation when needed
-> bounded retry budget
-> success updates run lineage
-> exhaustion falls through to postmortem
```

Pattern rules:

- remediation actions are durable artifacts
- remediation is policy-gated
- remediation history must be visible in reports and run detail
- successful remediation should not count the same way as an unrecoverable research failure

### 5.15 Deterministic verification before promotion

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

### 5.16 Directional signal pattern

After core verification, the system should classify the research direction of a successful run.

Suggested signals:

- `advancing`
- `stalled`
- `regressing`
- `noisy`
- `breakthrough`

Signal classification should use:

- current metric delta
- recent comparable run history
- significance thresholds
- constraint metric checks
- frontier comparison

Why this pattern exists:

- enables better next-step decisions
- supports autonomy without blind looping
- turns repeated experimentation into a research trajectory rather than isolated runs

### 5.17 Frontier tracking pattern

The system should maintain a metric frontier per charter and hypothesis line.

A frontier record should capture:

- best-known metric value
- run that achieved it
- direction of improvement
- runs since last improvement
- constraint violations if relevant

This record powers:

- stall detection
- breakthrough detection
- completion summaries
- autonomy decisions

### 5.18 Autonomous loop pattern

When autonomous mode is enabled, the system should operate as a budget-aware re-entrant loop rather than a one-shot chain.

Pattern:

```text
pick hypothesis
-> compile or update experiment spec
-> execute
-> remediate if mechanical failure
-> verify
-> classify directional signal
-> continue / vary / pivot / regenerate
-> stop on budget or termination condition
-> emit completion report
```

Pattern rules:

- budgets must be enforced before each costly action
- repetition detection should prevent useless loops
- context summarization should prevent prompt overflow
- the loop should always end with a readable completion artifact

### 5.19 Policy engine for budgets and approvals

A separate policy layer should decide whether an operator, skill, or orchestrator action may proceed.

When multiple policy layers apply, precedence should be:

1. hard system policy and orchestrator token scopes
2. user-configured policy or charter-level settings
3. autonomy mode or operator defaults

The policy layer must handle:

- compute budget ceilings
- full-text read ceilings
- reranker budget controls
- allowed hardware profiles
- network access permissions
- long-running job thresholds
- model usage policy
- remediation fix permissions
- skill capability policy
- autonomy mode
- checkpoint review behavior
- orchestrator permission scopes

### 5.20 Human-gated checkpoint pattern

The first shipped release should support configurable checkpoint gates.

Recommended gate types:

- after every run
- after every N runs
- before cost or hardware escalation
- before result promotion
- before network-enabled execution

This allows:

- minimal gating in full automation mode
- tighter cost control when desired
- safer rollout of autonomy without redesigning the core

### 5.21 External orchestrator API pattern

External orchestrators must interact with the lab through the control-plane API, not by writing directly to the database or manipulating workspaces.

The API pattern should be:

- versioned REST endpoints for durable resources
- streaming telemetry through SSE first
- stable JSON payloads and ids
- explicit actor identity for every action
- policy checks before side effects
- artifact and report retrieval through API-managed handles

Core orchestrator actions should include:

- create or resume a charter-scoped cycle
- request operator or skill execution
- read state snapshots and reports
- subscribe to domain events and run telemetry
- add guidance or notes
- pause, cancel, or resume allowed work
- approve or reject gated actions where policy allows

### 5.22 Derived graph views, not a graph database in v1

The system should store core entities in relational tables and derive graph views when needed.

Examples of graph views:

- citation relationships
- discovery clusters
- paper-analysis mind graphs
- evidence-to-hypothesis links
- hypothesis-to-experiment lineage
- repeated method families
- contradiction clusters
- skill-to-operator usage graphs
- orchestrator-to-cycle action graphs

---

## 6. Recommended MVP Stack Shape

This section defines the canonical architectural stack shape for the MVP.

| Area                          | Default choice                                                       | Why this is the default                                                       |
| ----------------------------- | -------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Core language                 | Python                                                               | Best fit for ML workflows, orchestration, adapters, and scientific tooling    |
| API / control plane           | FastAPI-style Python service                                         | Good typed contracts, async support, OpenAPI generation, local simplicity     |
| Durable state                 | PostgreSQL                                                           | Strong transactional model, row locking, JSON, and good fit for queue + state |
| Vector retrieval              | pgvector in PostgreSQL                                               | Keeps vector search close to canonical state in v1                            |
| Full-text / lexical retrieval | PostgreSQL full-text search plus local lexical indexing where useful | Good fit for metadata-first paper search in v1                                |
| Artifact store                | Local filesystem                                                     | Fits local-first deployment and keeps artifacts inspectable                   |
| Job queue                     | Database-backed queue                                                | Simpler than a separate queue service in a single-user MVP                    |
| Execution isolation           | Docker or Podman containers                                          | Practical local sandbox for generated code                                    |
| Workspace isolation           | Git worktrees                                                        | Clean per-experiment code isolation with clear lineage                        |
| UI surface                    | Web UI plus CLI                                                      | We want a real phase-1 UI, not CLI only                                       |
| LLM access                    | Provider-agnostic gateway adapter                                    | Prevents coupling to a single model vendor                                    |
| Embeddings                    | Provider-agnostic embedding adapter                                  | Allows hosted and local options                                               |
| Skill packages                | `skill.md` rooted packages                                           | Human-readable, coding-agent-friendly extension surface                       |
| Orchestrator integration      | REST + SSE over the same control plane                               | Headless-first, simple, observable, and easy to test                          |
| Reporting                     | Markdown rendered in the UI                                          | Easy to diff, store, and inspect                                              |

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
- support retrieval over sources, discovery state, evidence, hypotheses, runs, notes, reports, and failures
- maintain audit history and job records

Primary record types:

- `ResearchCharter`
- `ResearchState`
- `ProblemProfile`
- `PaperCard`
- `DiscoverySession`
- `DiscoveryView`
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
- `ApprovalEvent`
- `DomainEvent`
- `OrchestratorClient`

### 7.3 Discovery

Responsibility:

- retrieve internal corpus metadata and selected content
- maintain an arXiv metadata warehouse
- perform targeted external retrieval
- deduplicate and rank results
- maintain explicit discovery state and outputs
- fetch HTML or PDF only when explicitly escalated

### 7.4 Paper Analysis

Responsibility:

- ingest selected papers
- create structure-aware chunks
- extract typed graph nodes and relations
- support graph-aware QA and locate workflows
- compute coverage verification
- emit paper analysis packets and optional advisory review artifacts

### 7.5 Literature Intelligence

Responsibility:

- score titles and abstracts together
- deduplicate results across sources
- produce shortlist recommendations
- extract structured evidence from metadata or deeper reads
- preserve provenance and escalation rationale

### 7.6 Ideation and Review

Responsibility:

- generate candidate hypotheses from evidence
- critique for novelty, weakness, redundancy, and likely failure modes
- rank the portfolio before protocol compilation

### 7.7 Protocol Compiler

Responsibility:

- convert approved hypotheses into executable `ExperimentSpec`s
- define controls, baseline, metric, artifacts, stop conditions, and expected outputs
- reject under-specified ideas before code generation begins

### 7.8 Skill Registry and Runtime

Responsibility:

- discover `skill.md` packages from configured roots
- validate skill metadata and structure
- resolve which skills are available for a given operator or research cycle
- record skill activation and execution history
- expose skill catalog and status through UI and API

### 7.9 Build and Execution Lab

Responsibility:

- create isolated workspaces
- apply code changes
- prepare runtime images or environments
- execute runs within policy limits
- capture outputs into `RunRecord`

### 7.10 Remediation

Responsibility:

- classify mechanical failures
- assemble remediation context
- apply bounded fix attempts
- update run lineage and retry plans
- hand off unresolved failures to postmortem generation

### 7.11 Verification and Signal

Responsibility:

- compare runs to baseline and historical work
- rerun or replay where required
- run leakage and evaluation checks
- create `VerificationReport`
- classify directional signal
- maintain frontier state
- create `FailurePostmortem` records when needed

### 7.12 Reporting and Lab Notebook

Responsibility:

- generate concise human-readable summaries
- produce markdown report bundles per cycle
- summarize discovery, selected papers, experiments, verification, and open questions

### 7.13 Pattern Memory

Responsibility:

- consolidate reusable positive and negative patterns across charters
- preserve evidence counts and staleness context
- expose patterns for retrieval into future operators

### 7.14 Approvals and Policy

Responsibility:

- enforce approval requirements
- block disallowed actions
- persist approval history
- expose pending approvals to the user and, where permitted, orchestrators

### 7.15 Orchestrator Gateway

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
    -> DiscoveryView
    -> PaperAnalysisPacket
        -> EvidenceCard
            -> HypothesisCard
                -> ExperimentSpec
                    -> RunRecord
                        -> VerificationReport
                            -> ReportBundle / AcceptedFinding
```

### 8.2 Advisory review lineage

```text
PaperCard
    -> PaperReviewArtifact
        -> ReportBundle
```

### 8.3 Skill and orchestration lineage

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

### 8.4 Learning lineage

```text
RunRecord
    -> RemediationAction
    -> VerificationReport
        -> DirectionalSignal
        -> MetricFrontier
        -> FailurePostmortem
            -> CanonicalPattern
```

### 8.5 Important lineage rules

- A `HypothesisCard` must cite one or more `EvidenceCard`s.
- An `ExperimentSpec` must reference the `HypothesisCard` it operationalizes.
- A `RunRecord` must reference the exact `ExperimentSpec`, workspace lineage, and bound skills used.
- A promoted claim must reference at least one `VerificationReport`.
- A `FailurePostmortem` must reference the failed or rejected run and describe classification and next-step insight.
- A `RemediationAction` must reference the run, attempt number, fix type, and resulting retry.
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

### 10.2 Discovery pattern

```text
problem context + baseline context
-> query planning
-> internal corpus retrieval
-> arXiv metadata retrieval
-> targeted external retrieval
-> dedupe
-> title + abstract screening together
-> shortlist ranking
-> stable or discovery view generation
-> optional HTML fetch with reason
-> optional PDF fetch with reason
-> discovery exports
```

### 10.3 Two-depth paper analysis pattern

```text
automatic metadata analysis during discovery
-> shortlisted paper selected
-> ingest full text when justified
-> structure-aware chunking
-> typed graph extraction
-> graph-aware QA support
-> coverage verification
-> paper analysis packet
-> optional advisory paper review artifact
```

### 10.4 Skill selection and execution pattern

```text
operator role + research state + policy
-> skill resolver
-> eligible skill set
-> context assembly
-> skill execution
-> skill execution record
-> operator output
```

Important rule: no skill executes as invisible prompt glue.  It must leave lineage.

### 10.5 Hypothesis to experiment pattern

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

### 10.6 Remediation and retry pattern

```text
failed run
-> classify failure
-> choose focused or broad remediation
-> apply permitted fix
-> restage if needed
-> retry within budget
-> hand off to postmortem if exhausted
```

### 10.7 Verification and promotion pattern

```text
completed run
-> self-critic or quick pre-check where configured
-> baseline comparison
-> historical comparison
-> metric sanity checks
-> rerun or replay checks
-> verification report
-> directional signal classification
-> frontier update
-> promoted finding or failure postmortem
```

### 10.8 Autonomous loop pattern

```text
pick hypothesis
-> compile or update experiment spec
-> execute
-> remediate if needed
-> verify
-> classify signal
-> continue / vary / pivot / regenerate
-> stop on budget or policy boundary
-> emit completion report
```

### 10.9 External orchestrator control pattern

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
    /discovery
    /paper_analysis
    /paper_reviews
    /runs
    /reports
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

- discovery exports
- paper analysis packets
- paper review artifacts
- run logs
- metric snapshots
- generated patches
- literature notes
- extracted evidence summaries
- rendered reports
- failure postmortems
- remediation histories
- skill execution diagnostics

---

## 12. Search and Retrieval Pattern

The retrieval system should combine:

- lexical search over title, abstract, authors, tags, notes, and postmortems
- vector search over semantic embeddings where useful
- structured filters such as source type, recency, relevance, and read state
- explicit retrieval views for stable and discovery modes

At minimum there should be separate logical search views for:

- title and abstract metadata
- deeper full-text notes or extracted sections
- internal corpus documents
- historical run reports and failure memory
- skill catalog and examples
- canonical pattern memory

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

Run failures should be classified rather than lumped together.  Examples:

- build failure
- dependency failure
- OOM or resource limit
- timeout
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
- a rerun or replay note where policy requires it
- a reviewer summary describing whether the improvement is robust, tentative, or likely spurious
- a postmortem if the result is rejected or inconclusive
- a directional signal and frontier update if the run is valid

---

## 15. Human and Orchestrator Interaction Pattern

The product should feel like a researcher’s control tower, not a black box.

### 15.1 Human interaction model

- use the UI to create or resume a cycle, inspect state, review reports, and intervene
- use the CLI for direct local control and debugging
- keep every recommendation linked to evidence and lineage

### 15.2 Orchestrator interaction model

- use the API to create charters and cycles, query state, monitor events, and issue allowed commands
- provide scoped read and write permissions
- treat telemetry streams as the primary monitoring interface

### 15.3 Required approval surfaces

The user should be able to clearly review and approve or reject:

- deeper reads beyond budget
- expensive or long-running experiments when configured
- profile escalations and resource step-ups
- network-enabled runs
- promotion of headline claims
- sensitive orchestrator-issued actions where policy requires confirmation

### 15.4 Explainability pattern

Every surfaced object should answer “why is this here?”

Examples:

- a shortlisted paper should show title/abstract score and escalation reason
- a paper-analysis node should show the source chunk and confidence
- a hypothesis should show supporting evidence and critique summary
- a promoted run should show baseline, historical, and frontier comparison
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
    discovery/
    analysis/
    literature/
    ideation/
    protocols/
    execution/
    remediation/
    verification/
    reporting/
    memory/
    skills/
    adapters/
      arxiv/
      corpus/
      external_search/
      paper_ingestion/
      graph/
      llm/
      embeddings/
      git/
      container/
  prompts/
    planning/
    discovery/
    analysis/
    ideation/
    coding/
    remediation/
    verification/
    reporting/
  skills/
    literature/
    analysis/
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
- **ADR-007** — Use two-depth paper analysis: metadata by default, full analysis by escalation.
- **ADR-008** — Store paper analysis packets separately from advisory paper review artifacts.
- **ADR-009** — Expose stable and discovery retrieval views as the required v1 retrieval modes.
- **ADR-010** — Support modular skill packages rooted in `skill.md`.
- **ADR-011** — Use trust tiers rather than mandatory skill signing in the first local release.
- **ADR-012** — Expose a versioned REST + SSE orchestrator API from the control plane.
- **ADR-013** — Execute generated code inside isolated containers and separate workspaces.
- **ADR-014** — Route mechanical failures through auto-remediation before full postmortem.
- **ADR-015** — Verification is separate from generation.
- **ADR-016** — Directional signal and frontier tracking are first-class architectural concepts.
- **ADR-017** — Keep a real phase-1 UI instead of CLI only.

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
9. Treating advisory paper review scores as trusted acceptance signals.
10. Using notebooks as the product backbone.

---

## 19. Evolution Path

### Phase 1 — Local ML lab core

- single-user local runtime
- scoped research problems
- internal corpus retrieval
- arXiv metadata warehouse and literature triage
- stable and discovery retrieval modes
- selected paper analysis and graph-aware QA
- skill registry and first-party skills
- orchestrator API and event stream
- experiment execution and verification loop

### Phase 2 — Better memory and autonomy

- auto-remediation
- directional signal and frontier views
- richer dashboard and timeline views
- checkpoint gating and configurable autonomy
- more robust skill packaging and trust controls

### Phase 3 — Cross-charter learning and optional scale-up

- canonical pattern memory
- stronger autonomy loops
- optional remote workers
- object storage replacement for filesystem artifacts
- more advanced retrieval and ranking models
- optional MCP or other compatibility facades on top of the orchestrator API
- support for additional research domains through new adapters and skills

---

## 20. Resolved Follow-up Decisions

### 20.1 When should paper review artifacts be generated?

Paper review artifacts should be generated **only for papers that have been escalated to full-text analysis**.

Recommended rule:

- metadata-only discovery does **not** generate review artifacts
- once a paper is pulled into full-text analysis, the system may generate:
  - a `PaperAnalysisPacket` as the canonical structural artifact
  - a linked `PaperReviewArtifact` as the advisory evaluative artifact

This keeps review generation aligned with deeper evidence and avoids spending model budget on lightly screened papers.

### 20.2 When should reranking be automatic versus explicitly user-controlled?

Reranking should be **automatic by default**, but always **budget-aware and gracefully degradable**.

Recommended v1 behavior:

- in **Stable** mode, automatically rerank the top candidate set when the reranker is available and the policy budget allows it
- in **Discovery** mode, also allow automatic reranking, but keep diversity and novelty signals in the final ordering so reranking does not collapse the result set into near-duplicates
- if the reranker is unavailable, too slow, or outside the active cost/latency budget, the system should fall back automatically to first-stage ranking without blocking the workflow
- user control should exist as an **override**, not as the primary way the system operates

Why this is the best v1 stance:

- the user should not have to micromanage retrieval quality knobs for ordinary use
- automatic reranking improves default quality when affordable
- graceful fallback prevents the system from making retrieval fragile or too expensive

### 20.3 How much human verification should be required before a canonical pattern can influence autonomous planning?

Use a **light-touch default**.

Recommended stance:

- human verification should **not** be required before a canonical pattern can begin influencing autonomous planning
- patterns may influence planning automatically once they meet minimum internal thresholds such as:
  - sufficient supporting evidence count
  - acceptable confidence
  - compatible environment or staleness context
- human verification should remain optional for:
  - promoting a pattern to a higher-trust tier
  - allowing a pattern to influence higher-risk or higher-cost actions
  - curating stale or disputed patterns

This matches the experimental goal: test how far useful automation can go without putting a heavy human bottleneck back into the loop.

### 20.4 When should checkpoint gates default on versus off for new users?

Checkpoint gates should be **off by default unless enabled by configuration or profile**.

Recommended rule:

- checkpoint behavior is determined by policy configuration, user preferences, or chosen operating profile
- the architecture should not hardcode checkpoint gates as globally on for all new users
- onboarding profiles may still choose safer defaults, but the core system should treat checkpointing as a configurable behavior

This keeps the autonomy layer clean and consistent: gating is a policy decision, not an architectural assumption.

## 21. Recommended Next Step

The next document should be `phased_implementation_plan.md`, which turns this revised architecture into a build sequence covering:

- discovery and paper-analysis vertical slices
- automatic reranking and graceful retrieval fallback
- remediation and directional signal milestones
- autonomous loop checkpointing and budget control
- canonical pattern thresholds, trust tiers, and orchestrator policy surfaces
