# Product Requirements Document

**Product:** ML Laboratory Co-Scientist  
**Role:** Product Manager  
**Status:** Working Draft v3  
**Scope:** Local small-scale ML laboratory MVP  
**Last Updated:** 2026-03-21

---

## 1. Purpose

This document defines the product requirements for the ML Laboratory Co-Scientist.

It answers five questions:

1. What problem are we solving?
2. What does the first product actually do?
3. What is explicitly in scope for the ML laboratory MVP?
4. What requirements must the system satisfy to be useful and trustworthy?
5. What should be deferred until after the ML laboratory core works?

This PRD is the source document for `system_patterns.md`, `phased_implementation_plan.md`, and `tech_context.md`.

---

## 2. Executive Summary

The ML Laboratory Co-Scientist is a local-first research system for machine learning work. It is designed to help a researcher move from a scoped research problem to evidence-grounded experiments, verified results, and human-readable reports.

The first version is not a generalized science platform and it is not a Kaggle-only optimizer. It is a bounded ML laboratory. It should accept a research problem, pull from internal and external sources, triage literature using title and abstract together before deeper reading, generate and test hypotheses, compare outcomes to historical work, and retain reusable failure memory.

The two additions now treated as first-class product requirements are:

1. **Skill support via `skill.md` packages** so custom, modular, task-specific behavior can be added without rewriting the core system.
2. **An orchestrator-facing API** so external agent systems can create, monitor, steer, and intervene in research cycles without bypassing policy or provenance.

The product should feel like a research control tower with bounded autonomy, not a black-box agent swarm.

---

## 3. Problem Statement

Autonomous experimentation is only a small slice of research. Before an experiment is worth running, a researcher usually needs to:

- frame the problem clearly
- understand prior internal work
- inspect recent external literature
- decide which papers are actually worth reading in depth
- translate ideas into valid, testable protocols
- run experiments in isolated environments
- verify outcomes and rule out bad comparisons
- retain failure knowledge so the next attempt is better

Today those steps are fragmented across notebooks, papers, internal notes, experiment logs, terminal sessions, and ad hoc agent prompts.

The result is predictable:

- literature review is expensive and inconsistent
- failures are forgotten
- experiments are hard to reproduce
- agents over-read or over-generate without strong grounding
- there is little clean API surface for higher-level orchestration

We need a product that turns the ML research loop itself into a durable, inspectable system.

---

## 4. Product Vision

Build the best local co-scientist for ML researchers: a system that can ingest a research direction, map the relevant evidence surface, propose and execute credible experiments, verify what happened, and expose the entire process through both a human-facing UI and an orchestrator-facing API.

---

## 5. Goals

### 5.1 Primary goals

- Reduce time from a new ML research problem to a credible baseline and first verified experiments.
- Combine internal corpus memory with external literature discovery in one workflow.
- Preserve the researcher-style literature funnel: **title + abstract together -> shortlist -> HTML/full text if available -> PDF only when necessary**.
- Support automated low-risk experimentation while preserving human intervention and steering.
- Make skills modular so the system can gain new behaviors by loading `skill.md` packages rather than hardcoding everything into the core.
- Expose a stable API so orchestrator agents can use and monitor the system safely.
- Make every result traceable to evidence, prompts, code lineage, runtime, and verification output.
- Treat structured failure memory and postmortems as first-class product assets.

### 5.2 Secondary goals

- Evaluate the product across a few public benchmark tasks, including selected Kaggle competitions, without making the product competition-centric.
- Make the local system good enough that it can later generalize to broader research domains.
- Keep the product usable by a single researcher on a single workstation.

---

## 6. Non-Goals

The ML laboratory MVP will not:

- be a general wet-lab or physical-science execution system
- autonomously publish papers or represent unverified claims as scientific truth
- mirror all arXiv PDFs by default
- require a human to approve every routine low-risk run
- depend on distributed cluster orchestration, Kubernetes, or multi-tenant infrastructure
- let external orchestrators bypass policy, approvals, or durable state
- rely on a hidden chat transcript as the system’s source of truth

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
- decide which papers deserve deeper reading
- propose multiple evidence-grounded directions
- turn a promising direction into a valid experiment plan
- execute and verify experiments locally
- compare results to what we tried before
- preserve failures and lessons learned
- monitor progress live and intervene when needed
- let higher-level orchestrator agents use the same system safely

---

## 8. Product Principles

### 8.1 Research-problem-first

The product is organized around scoped research problems, not around a single benchmark provider.

### 8.2 Metadata before full text

Default literature behavior is:

```text
query plan
-> title + abstract screening
-> shortlist
-> HTML or other machine-readable full text when needed
-> PDF only when necessary
```

### 8.3 Evidence before hypothesis, hypothesis before code

The system should not jump straight from a prompt to a code patch.

### 8.4 Verification before claim

Every experiment is tested. Promoted findings require deterministic verification and clear comparison context.

### 8.5 Local-first and bounded

The system must be usable on one machine with explicit budgets and inspectable artifacts.

### 8.6 Human steerability

The product should automate low-risk work but always expose state, telemetry, and intervention points.

### 8.7 Skills are product surface, not a hack

Behavioral modularity must be deliberate. `skill.md` packages are a supported extension mechanism.

### 8.8 API-first control plane

Everything the UI can do should flow through a durable control plane API so external orchestrators can use the same system.

### 8.9 Task-scoped context

The product should never stuff all history and all documents into every model context. Context must be assembled per task, per phase, per skill, and per operator.

---

## 9. MVP Scope

### 9.1 In scope

#### A. Research intake and problem scoping

- create a `ResearchCharter` from a scoped research problem
- capture goals, datasets, budgets, stop conditions, and constraints
- attach internal and external source scopes

#### B. Research memory and source retrieval

- internal corpus retrieval
- arXiv metadata warehouse in Postgres
- targeted external retrieval for selected sources
- title + abstract screening together
- selective escalation to HTML or PDF

#### C. Literature intelligence

- structured paper/source records
- evidence extraction
- contradiction and redundancy detection
- literature shortlist reports

#### D. Hypothesis and protocol generation

- multiple candidate hypotheses
- critique and ranking
- protocolization into executable `ExperimentSpec`s

#### E. Execution lab

- isolated GPU-capable execution
- automated low-risk experiment runs
- live telemetry and intervention controls
- code lineage and artifact capture

#### F. Verification and research memory updates

- deterministic checks for every run
- comparison to current baseline and historical internal work
- structured failure postmortems
- promotion or rejection of findings

#### G. Reporting

- rendered markdown reports in the UI
- readable summaries for literature, experiments, verification, and cycle outcomes

#### H. Skill system

- discover, validate, enable, disable, and execute `skill.md` packages
- attach skills to operators and research cycles
- store skill execution records and lineage

#### I. Orchestrator API

- create and manage research cycles over API
- monitor events, runs, approvals, and reports
- steer, pause, cancel, or annotate work through a policy-checked interface

### 9.2 Out of scope for the MVP

- generalized non-ML science adapters
- fully autonomous external publication workflows
- third-party multi-user SaaS deployment
- deep graph-native storage
- fully autonomous agent-to-agent society without a shared state model

---

## 10. Core User Workflows

### 10.1 Researcher workflow

```text
define research problem
-> create charter
-> retrieve internal + external sources
-> screen title + abstract together
-> shortlist
-> escalate to HTML/PDF where justified
-> extract evidence
-> generate and critique hypotheses
-> compile experiment spec
-> run experiments
-> verify
-> review report and decide next action
```

### 10.2 Low-risk autonomous workflow

```text
approved charter + policies
-> automated retrieval and screening
-> automated protocol compilation
-> automated low-risk experiments
-> live telemetry to user
-> automatic verification and postmortem creation
-> user intervention only when needed or requested
```

### 10.3 External orchestrator workflow

```text
orchestrator authenticates
-> creates or resumes research cycle
-> subscribes to event stream
-> requests operator or skill execution
-> receives telemetry and reports
-> pauses, cancels, or adds guidance
-> submits approvals where policy allows
```

---

## 11. Functional Requirements

### FR-1 Research Intake

- The product must allow a user or orchestrator to create a `ResearchCharter` for a scoped ML problem.
- The charter must include goal, success criteria, budget envelope, source scope, and stop conditions.
- The product must persist the charter and expose it through UI and API.

### FR-2 Source Retrieval

- The product must retrieve from both internal and external sources.
- The product must support an arXiv metadata warehouse and incremental updates.
- The product must support targeted source retrieval driven by the charter.

### FR-3 Literature Triage

- The product must evaluate title and abstract together during first-pass screening.
- The product must record why a paper or source was shortlisted.
- The product must prefer HTML or machine-readable full text over PDF when available.
- The product must record why any deeper read was requested.

### FR-4 Evidence and Hypothesis Formation

- The product must extract structured evidence from shortlisted sources.
- The product must generate multiple hypotheses, not only one.
- The product must critique and rank hypotheses.
- Each hypothesis must cite supporting evidence.

### FR-5 Protocol Compilation

- The product must compile a hypothesis into an `ExperimentSpec` before execution.
- The `ExperimentSpec` must define baseline, controls, metrics, artifacts, stop conditions, and expected outputs.

### FR-6 Execution

- The product must run experiments in isolated workspaces and containers.
- The product must support GPU-capable runs when required.
- The product must support automated low-risk experimentation.
- The product must stream telemetry to the UI and API during execution.

### FR-7 Verification

- The product must verify every experiment.
- The product must compare results against the declared baseline and relevant historical internal work.
- The product must classify failures and create a structured postmortem for unsuccessful or invalid runs.

### FR-8 Reporting

- The product must generate human-readable reports for literature screening, experiments, verification, postmortems, and cycle summaries.
- Reports must be rendered in the UI and available over API.

### FR-9 Skill System

- The product must support a first-class skill mechanism using `skill.md` packages.
- Skills must be discoverable from configured directories.
- Skills must be enable-able, disable-able, and versioned.
- Skills must declare required context, outputs, and permissions.
- Skill execution must be logged and linked to research state.
- Skills must not bypass policy, provenance, or verification requirements.

### FR-10 Orchestrator API

- The product must expose a stable control-plane API for external orchestrators.
- The API must allow create/read/update of research cycles, reports, approvals, and run control actions.
- The API must expose streaming telemetry for events and run status.
- The API must support orchestrator identity and scoped permissions.
- All orchestrator actions must be auditable.

### FR-11 Policy and Approval

- The product must encode policy separately from prompt text.
- The product must gate high-risk or external actions.
- The product must allow the user to intervene in active work.
- The product must persist approval and rejection decisions.

---

## 12. Non-Functional Requirements

### 12.1 Reliability

- Research state must survive restarts.
- Jobs must be resumable.
- Audit history must be append-only.

### 12.2 Reproducibility

- Accepted results must be replayable from stored lineage.
- Runs must record code lineage, model identifiers, datasets, configs, metrics, and artifacts.

### 12.3 Explainability

- The system must answer why a paper was shortlisted, why a hypothesis exists, why a run was promoted, and why a skill was applied.

### 12.4 Extensibility

- New task behavior should preferentially be added as skills, adapters, or configs instead of core rewrites.

### 12.5 Operability

- A single researcher should be able to run the system locally.
- The phase-1 UI must expose live status, reports, and controls.

### 12.6 API stability

- Orchestrator-facing endpoints must be versioned.
- Event payloads must use stable schemas.

### 12.7 Security and safety

- Generated code must not run directly on the host.
- Skills and orchestrator actions must be subject to capability checks.
- External writes must require explicit policy satisfaction.

---

## 13. Success Metrics

### 13.1 Product success metrics

- Time from charter creation to first baseline run
- Time from charter creation to first verified experiment
- Percentage of experiments with complete lineage and verification records
- Percentage of failed experiments with structured postmortems
- Percentage of shortlisted papers escalated to full text for a documented reason
- Percentage of orchestration actions performed through API instead of ad hoc manual intervention
- Number of reusable first-party and custom skills adopted in real workflows

### 13.2 Quality metrics

- Shortlist precision as judged by the researcher
- Verification pass rate for promoted runs
- Reduction in repeated failed ideas due to failure memory
- Researcher trust in reports and recommendations
- Historical comparison quality against prior internal work

### 13.3 System metrics

- median event-stream latency to UI/API
- run success/failure classification coverage
- skill load and validation success rate
- API contract test pass rate

---

## 14. Risks and Mitigations

| Risk | Why it matters | Mitigation |
|---|---|---|
| Over-reading literature | Wasted time, cost, and noisy evidence | Enforce title + abstract triage, escalation reasons, and full-text budgets |
| Unbounded agent context | Model quality drops and costs rise | Require task-scoped context assembly and skill-declared context needs |
| Fragile experimentation | Broken or irreproducible runs erode trust | Use isolated workspaces, containers, verification, and postmortems |
| Hidden behavior in prompts | Hard to debug or govern | Move durable logic to typed state, policies, configs, and skills |
| Skill sprawl | Custom behavior becomes ungovernable | Require skill validation, versioning, permissions, tests, and audit records |
| External orchestrator misuse | Unsafe or opaque remote control of the lab | Use scoped API tokens, auditable actions, policy checks, and approval gates |
| Public benchmark overfitting | Product becomes competition-specific | Keep benchmarks as evaluation tracks, not the product’s identity |

---

## 15. Release Framing

### 15.1 MVP definition

The MVP is complete when a user or orchestrator can:

1. create a scoped ML research cycle
2. retrieve internal and external sources
3. triage literature with title + abstract together
4. selectively read deeper only when justified
5. generate evidence-backed hypotheses
6. compile and run experiments automatically where policy allows
7. verify every run and create postmortems
8. review rendered reports in a UI
9. use at least a small library of `skill.md` packages
10. drive and monitor the system through a stable orchestrator API

### 15.2 Evaluation tracks

The MVP should be exercised against:

- a small set of public ML benchmark tasks, including selected Kaggle competitions where appropriate
- a set of internal research problems and internal research memory
- retrieval and literature triage tasks against arXiv metadata plus internal corpora

---

## 16. Open Questions

- How strict should third-party skill trust and signing be in the first local release?
- Should orchestrator approvals be allowed for some policy scopes, or should only a human user be able to approve sensitive actions?
- Which benchmark packs best represent the first three ML problem shapes we want to support?
- How much deterministic logic should live inside skill hooks versus shared core services?
- When should we add an MCP facade on top of the orchestrator API, if at all?

---

## 17. Next Document

The next architecture source of truth is `system_patterns.md`, which should translate these product requirements into the canonical system shape.
