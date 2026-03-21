# Tech Context

**Product:** ML Laboratory Co-Scientist  
**Role:** Engineer  
**Status:** Working Draft v3  
**Scope:** Local small-scale ML laboratory MVP  
**Last Updated:** 2026-03-21

---

## 1. Purpose

This document translates the current product direction, system patterns, and phased implementation plan into concrete technical choices for the first build.

It answers these questions:

1. What stack are we actually using first?
2. How does the local development environment work?
3. Which services are required versus optional?
4. How do we handle retrieval, skill loading, execution, and orchestration in practice?
5. Which technical decisions are locked now, and which are intentionally deferred?

This document is downstream of `prd.md`, `system_patterns.md`, and `phased_implementation_plan.md`.

---

## 2. Working Assumptions

This tech context assumes the following product decisions are already in force:

- The product is **research-problem-first**, not competition-first.
- The first release is an **ML laboratory**, not a generalized science platform.
- The lab should work against **both internal and external sources**.
- arXiv discovery is **metadata-first**, with **title and abstract reviewed together** before any deeper read.
- arXiv escalation follows **metadata -> HTML or other machine-readable full text when available -> PDF only when necessary**.
- We want **automated low-risk experimentation** without requiring a human to approve every run.
- We still need a **phase-1 UI** with live telemetry, reports, controls, and intervention points.
- The execution layer must support **GPU-capable isolated workloads**.
- Different stages of the workflow may use **different models** behind one routing layer.
- Every experiment should produce durable artifacts, verification output, and when it fails, a **structured postmortem**.
- Historical internal work matters. The system should compare new results against **prior internal runs, reports, and research memory**.
- Modular behavior must be supported through **`skill.md` packages**.
- External orchestrators must be supported through a **stable API plus telemetry streams**.

---

## 3. Canonical Technical Decisions

The following choices should be treated as the default implementation path for the MVP.

### 3.1 Host platform targets

- **Primary host target:** Linux workstation
- **Secondary dev target:** macOS for non-GPU development and UI/API work
- **Windows stance:** not a first-class target; use WSL2 only if needed

### 3.2 Primary languages

- **Backend, workers, adapters, orchestration, verification:** Python
- **Frontend:** TypeScript
- **Configuration:** YAML plus environment variables
- **Documentation and reports:** Markdown rendered as HTML in the UI
- **Skills:** Markdown-first packages rooted in `skill.md`

### 3.3 Core local stack

The canonical local stack for the first implementation is:

- **Python runtime:** Python 3.12
- **Python package manager:** `uv`
- **API framework:** FastAPI
- **Schema layer:** Pydantic v2
- **ORM and migrations:** SQLAlchemy 2 + Alembic
- **Postgres driver:** `psycopg`
- **Frontend:** React + TypeScript + Vite
- **Frontend data layer:** TanStack Query
- **Frontend routing:** TanStack Router or similarly light file-based routing
- **Styling:** Tailwind CSS with a thin local component layer
- **Durable state:** PostgreSQL + `pgvector`
- **Queue:** Postgres-backed jobs table with row-claim semantics
- **Artifact store:** local filesystem
- **Execution backplane:** Docker Engine + NVIDIA Container Toolkit
- **Workspace isolation:** git worktrees
- **Telemetry stream:** domain events persisted in Postgres and exposed through SSE first
- **CLI:** Typer-based Python CLI

### 3.4 Mandatory services for v1

The MVP should assume these services exist from the beginning:

- PostgreSQL
- web frontend
- API/control plane
- worker process
- execution runner with container access

These are baseline product services, not optional nice-to-haves.

### 3.5 Explicitly not required in v1

The MVP should not require these services to be usable:

- Redis
- Celery
- Airflow
- Temporal
- Elasticsearch/OpenSearch
- MLflow
- Kubernetes
- object storage
- graph database
- separate real-time messaging broker

---

## 4. Local Runtime Model

### 4.1 Development mode

During normal development, the system should run with a split model:

- infrastructure in containers
- application code on the host with hot reload

That means:

- Postgres runs in Docker Compose
- optional local model servers can run in Docker Compose
- API runs locally via `uv`
- worker runs locally via `uv`
- web frontend runs locally via `pnpm`

### 4.2 Reproducible demo mode

A second startup path should exist for demos and onboarding:

- bring up Postgres
- bring up API
- bring up worker
- bring up frontend
- optionally bring up a local model server

Docker Compose profiles are sufficient for this once the first vertical slice is stable.

### 4.3 Dynamic experiment execution

Experiment containers are **not** long-running compose services.

They are created on demand by the execution runner. Each run gets:

- its own isolated workspace
- a selected base image
- mounted dataset references
- a mounted artifact output path
- explicit resource limits
- a unique run identifier and telemetry stream

---

## 5. Repository Shape

The monorepo should follow this structure:

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

---

## 6. Service Boundaries

### 6.1 API service

Responsibilities:

- REST API for durable resources
- SSE endpoints for telemetry
- OpenAPI schema generation
- auth and scope checks for humans and orchestrators
- report and artifact access
- approval entrypoints

### 6.2 Worker service

Responsibilities:

- claim queued jobs from Postgres
- run operators
- coordinate skill resolution and context assembly
- emit domain events and reports
- launch execution runs through the execution runner

### 6.3 Web service

Responsibilities:

- render cycle dashboard
- render report bundles
- show run telemetry and approvals
- expose skill catalog and skill usage history

### 6.4 CLI

Responsibilities:

- local developer control
- debugging and fixture workflows
- direct cycle creation and replay helpers

### 6.5 Execution runner

Responsibilities:

- workspace lifecycle
- base-image selection or build
- container launch and teardown
- log and metric collection
- resource enforcement

In v1 this is a library/module invoked by workers, not a separate microservice.

### 6.6 Skill runtime

Responsibilities:

- discover `skill.md` packages
- validate metadata and optional helpers
- resolve eligible skills for each operator
- emit `SkillExecutionRecord`s

In v1 this is also a library/module invoked by workers and surfaced through the API.

---

## 7. Canonical Storage Design

### 7.1 Database role

PostgreSQL is the system of record for:

- research cycles and state transitions
- jobs and job claims
- domain events and audit history
- papers and source records
- evidence, hypotheses, experiment specs, and reports
- skills, skill bindings, and skill execution records
- orchestrator clients, sessions, commands, and approvals
- embeddings and retrieval metadata references

### 7.2 Filesystem role

The filesystem stores:

- run logs
- generated patches
- experiment artifacts
- literature fetches and notes
- rendered reports
- exports
- cached datasets or external assets where appropriate

### 7.3 Local data root

Use a configurable local data root such as:

```text
$LAB_DATA_ROOT/
  artifacts/
  cache/
  workspaces/
  exports/
```

The git repo should stay relatively small. Large caches and artifacts should live under the data root.

### 7.4 Suggested database grouping

Use logical schema grouping or at least naming boundaries for:

- `research_*`
- `source_*`
- `execution_*`
- `report_*`
- `skill_*`
- `orchestrator_*`
- `audit_*`

---

## 8. Skill System Technical Design

### 8.1 Skill package format

Each skill is a directory rooted in `skill.md`.

Recommended structure:

```text
skills/
  literature/
    title_abstract_triage/
      skill.md
      hooks.py                 # optional deterministic helpers
      schemas/                 # optional input/output schemas
      fixtures/                # optional examples and tests
      tests/                   # optional tests
```

### 8.2 `skill.md` contract

The `skill.md` file should include YAML frontmatter so one file remains both human-readable and machine-parseable.

Example:

```md
---
id: literature.title_abstract_triage
version: 0.1.0
phase: literature
allowed_operators: [literature_screen]
preferred_models: [retrieval_summarizer]
context_inputs:
  - research_charter
  - source_candidates
outputs:
  - screening_decisions
capabilities:
  - source.read_metadata
  - source.request_fulltext
risk_level: low
---

# Title + Abstract Triage

## Purpose
Screen title and abstract together to decide shortlist priority.

## When to use
Use after metadata retrieval and before deeper reading.

## Required behavior
- consider title and abstract jointly
- produce shortlist rationale
- propose escalation reason only when needed
```

### 8.3 Skill loader and validator

Implementation stance:

- parse frontmatter from `skill.md`
- validate against a Pydantic `SkillManifest`
- store the rendered body as the human-readable instructions
- compute a content hash for version tracking
- validate optional `hooks.py` exports when present
- reject malformed or unsafe skill packages during load

### 8.4 Skill resolution

The worker should resolve skills using:

- operator type
- phase
- research problem profile
- policy and capability requirements
- enable/disable flags
- explicit cycle-level bindings

The result should be a **small bound skill set** per operator invocation.

### 8.5 Skill persistence model

Minimum tables or entities:

- `SkillDefinition`
- `SkillVersion`
- `SkillBinding`
- `SkillExecutionRecord`
- `SkillValidationIssue`

### 8.6 Skill hooks

Allow optional deterministic helper hooks in `hooks.py` for narrow use cases such as:

- pre-assembly context shaping
- deterministic scoring helpers
- post-processing and validation of structured outputs

Do **not** let hooks become an alternate orchestration system.

### 8.7 Skill authoring ergonomics

The repo should ship:

- a skill template
- a skill validation CLI command
- fixture examples
- docs for writing first-party and custom skills

---

## 9. Orchestrator API Technical Design

### 9.1 API style

The v1 orchestrator surface should be:

- **REST/JSON** for durable resource operations
- **SSE** for real-time event and telemetry streams
- **OpenAPI 3.1** for schema visibility and client generation

Do not split this into a separate gateway service in v1. Keep it in the same FastAPI control-plane service.

### 9.2 Core resources

Suggested resource families:

- `/api/v1/cycles`
- `/api/v1/problems`
- `/api/v1/sources`
- `/api/v1/hypotheses`
- `/api/v1/experiments`
- `/api/v1/runs`
- `/api/v1/reports`
- `/api/v1/approvals`
- `/api/v1/skills`
- `/api/v1/orchestrators`
- `/api/v1/events/stream`

### 9.3 Must-have actions

The API must support:

- create and update research cycles
- read cycle state snapshots
- list and fetch reports
- request allowed operator execution
- pause, cancel, and resume allowed jobs or runs
- submit notes or steering directives
- fetch skill catalog and skill usage history
- read pending approvals and record allowed decisions
- subscribe to domain events and run telemetry

### 9.4 Auth and scopes

Use local API tokens with explicit scopes in v1.

Suggested scopes:

- `cycles.read`
- `cycles.write`
- `runs.read`
- `runs.control`
- `reports.read`
- `skills.read`
- `skills.bind`
- `events.read`
- `approvals.read`
- `approvals.write`
- `admin.local`

Every orchestrator action should record:

- actor id
- token or client id
- scope used
- target resource
- result

### 9.5 Event streaming model

Use **SSE first**.

Event delivery approach:

- persist domain events in Postgres
- expose stream endpoints that tail events by `last_event_id`
- allow clients to resume from checkpoints
- expose run telemetry as event records or structured stream chunks

This is simpler and more durable than a separate real-time broker in v1.

### 9.6 Idempotency and retries

For externally triggered mutations, support:

- client-supplied idempotency key where useful
- safe retry behavior for command endpoints
- explicit status responses for already-applied actions

### 9.7 Client SDK

Ship a minimal Python SDK first.

Responsibilities:

- token handling
- typed models
- event stream helper
- convenience methods for common actions

---

## 10. Source Retrieval and Research Memory

### 10.1 arXiv strategy

Use Postgres as the local warehouse for arXiv metadata.

Technical stance:

- store title, abstract, categories, authors, dates, ids, and links in Postgres
- support incremental sync from a bulk metadata harvester
- allow targeted API search when needed
- treat HTML fetch and PDF fetch as separate escalation operations

### 10.2 Internal corpus strategy

Support internal ingestion for:

- papers and notes
- prior run summaries
- reports and postmortems
- selected code or experiment metadata where useful

### 10.3 Retrieval strategy

Use hybrid retrieval:

- lexical search in Postgres
- vector search via `pgvector`
- structured filters for source type, recency, relevance, and read depth

### 10.4 Read-depth preservation

Every source match should preserve whether the evidence comes from:

- metadata only
- HTML or machine-readable deeper read
- PDF-based deeper read
- internal note or report

---

## 11. Model Gateway and Routing

### 11.1 Routing model

The model gateway should support role-based routing.

Suggested logical roles:

- planning / orchestration
- retrieval synthesis
- literature screening
- hypothesis generation
- protocol drafting
- coding
- evaluation / verification
- report writing

### 11.2 Hosted and local model support

The gateway should support both:

- hosted provider adapters
- local inference adapters

A cycle, operator, or skill may prefer one model route, but the control plane should own the final routing decision.

### 11.3 Recording requirements

Every model call that affects durable outputs should record:

- provider or local runtime
- model identifier
- prompt or template identifier
- major generation parameters
- cost or token usage when available
- bound skills in effect

---

## 12. Execution Backplane

### 12.1 Base images

Use a mix of:

- a few reusable base images for common ML stacks
- on-demand image builds for research-problem-specific needs

Most specialized environments should be built on demand from config, not pre-baked forever.

### 12.2 Runner contract

The execution runner should accept a `RunSpec` containing:

- workspace path
- image reference or build recipe
- command
- env vars
- mounts
- hardware profile
- timeout and memory limits
- network mode
- artifact output path

### 12.3 GPU support

GPU passthrough should be allowed through Docker + NVIDIA Container Toolkit only when the `RunSpec` and policy allow it.

### 12.4 Telemetry capture

The runner must capture:

- stdout and stderr
- structured status transitions
- resource usage snapshots
- metric outputs
- artifact manifests

### 12.5 Failure capture

The runner must classify failures and persist the classification to `RunRecord` and `FailurePostmortem` generation.

---

## 13. Verification and Postmortem Pipeline

### 13.1 Verification stance

Every experiment should be tested and verified.

Minimum verification bundle:

- baseline comparison
- historical comparison
- artifact validation
- schema and split checks where applicable
- metric sanity checks
- promotion or rejection decision

### 13.2 Postmortem generation

Every failed or rejected run should generate a structured postmortem with fields such as:

- failure type
- likely root cause
- evidence observed
- what was learned
- whether the hypothesis should be revised, searched again, or abandoned
- suggested next actions

### 13.3 Feedback loops

Verification and postmortems should feed back into:

- hypothesis ranking
- literature re-querying
- skill recommendations
- protocol revisions

---

## 14. UI and Report Rendering

### 14.1 Phase-1 UI views

The first UI should include:

- cycle list and cycle detail
- event timeline
- source and paper shortlist view
- hypothesis and experiment queue view
- active run telemetry view
- reports and postmortems view
- skill catalog and usage view
- approvals panel

### 14.2 Report rendering

Reports should be stored as Markdown and rendered to HTML in the UI.

Why this is the default:

- markdown is easy to diff and generate
- rendered HTML is readable for users
- the same artifact is useful for coding agents and humans

### 14.3 Artifact access

The UI should link to logs, patches, report bundles, and relevant artifacts through API-served metadata, not direct filesystem assumptions.

---

## 15. Config and Secrets

### 15.1 Config loading

Use:

- checked-in YAML config for default profiles
- environment variables for secrets and machine-specific overrides
- optional per-user local override files ignored by git

### 15.2 Important config domains

- database
- data root
- model providers
- skill discovery paths
- problem profiles
- policy thresholds
- execution profiles
- telemetry settings
- orchestrator token scopes

### 15.3 Example environment variables

```text
LAB_ENV=dev
LAB_DB_URL=postgresql+psycopg://...
LAB_DATA_ROOT=/path/to/data
LAB_MODEL_CONFIG=/path/to/models.yaml
LAB_SKILL_PATHS=/repo/skills:/user/skills
LAB_LOCAL_MODEL_BASE_URL=http://localhost:11434
LAB_API_TOKEN=...
LAB_ENABLE_GPU=true
```

---

## 16. Testing Strategy

### 16.1 Unit tests

Cover:

- state transitions
- skill parsing and validation
- policy checks
- retrieval scoring helpers
- API schema models

### 16.2 Integration tests

Cover:

- worker claiming jobs from Postgres
- event streaming
- skill resolution and binding
- arXiv metadata retrieval path
- execution runner contract
- verification pipeline

### 16.3 End-to-end tests

Cover:

- create cycle -> literature triage -> protocol -> run -> verification -> report
- orchestrator client end-to-end control flow
- custom skill load and execution

### 16.4 Fixtures

Create reusable fixtures for:

- small literature sets
- internal reports and postmortems
- fake runs and metrics
- sample `skill.md` packages
- API tokens and scope models

---

## 17. Coding Standards

- prefer typed interfaces and explicit schemas over dynamic dict passing
- keep prompts versioned and stored as assets
- keep skills repo-visible and testable
- keep deterministic policy logic in Python and config, not prompt prose
- record all external side effects through durable events
- do not let the web UI become the only way to operate the system

---

## 18. First Build Sequence

The first implementation sequence should be:

1. Postgres + migrations + base schemas
2. FastAPI control plane + OpenAPI docs
3. worker runtime + job queue + event stream
4. minimal web UI
5. skill loader + validation + catalog endpoints
6. research cycle creation and retrieval pipeline
7. arXiv metadata warehouse integration
8. title + abstract triage operators and reports
9. protocol compiler
10. execution runner and telemetry
11. verification and postmortems
12. orchestrator SDK and compatibility tests

---

## 19. Deferred Technical Choices

The following are intentionally deferred until after the MVP loop works:

- Redis or separate queue infra
- workflow engines like Temporal
- Elasticsearch/OpenSearch
- graph database
- WebSocket as the primary stream protocol
- MCP facade on top of the orchestrator API
- object storage for artifacts
- remote worker pools
- signed third-party skill marketplace mechanics

---

## 20. Recommended Immediate Next Step

Turn this into an initial repository bootstrap with:

- database schema stubs
- API resource skeletons
- skill package template
- first two literature skills
- orchestrator token and event-stream scaffolding
