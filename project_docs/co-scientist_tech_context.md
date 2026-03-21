# Tech Context

**ML Laboratory Co-Scientist · implementation baseline for the local ML laboratory MVP**

**Role**  
The Engineer

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

This document translates the current product direction, system patterns, and phased implementation plan into concrete technical choices for the first build.

It exists to answer these questions clearly:

1. What stack are we actually using first?
2. How does the local development environment work?
3. Which services are required versus optional?
4. How do we handle storage, execution, model routing, and retrieval in practice?
5. Which technical decisions are locked now, and which are intentionally deferred?

This document is downstream of `system_patterns.md` and `phased_implementation_plan.md`.

It is intentionally practical. It should be specific enough that an engineer can begin scaffolding the repo and local runtime without needing another architecture rewrite.

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

---

## 3. Canonical Technical Decisions

The following choices should be treated as the default implementation path for the MVP.

### 3.1 Host platform targets

- **Primary host target:** Linux workstation
- **Secondary dev target:** macOS for non-GPU development and UI/API work, also possible light metal work
- **Windows stance:** not a first-class target; use WSL2 only if needed

Why this is the default:

- GPU passthrough for experiment containers is materially easier and more reliable on Linux.
- Most ML tooling and container execution patterns are simplest on Linux.
- We can still allow macOS for API, retrieval, and UI development when GPU execution is not required.

### 3.2 Primary languages

- **Backend, workers, adapters, orchestration, verification:** Python
- **Frontend:** TypeScript
- **Configuration:** YAML plus environment variables
- **Documentation and reports:** Markdown with rendered HTML in the UI

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
- **Frontend routing:** lightweight file-based or TanStack Router; keep routing simple
- **Styling:** Tailwind CSS with a minimal component layer
- **Durable state:** PostgreSQL + `pgvector`
- **Queue:** Postgres-backed jobs table with row-claim semantics
- **Artifact store:** local filesystem
- **Execution backplane:** Docker Engine + NVIDIA Container Toolkit
- **Workspace isolation:** git worktrees
- **Telemetry stream:** domain events persisted in Postgres and exposed to the UI through SSE first
- **CLI:** Typer-based Python CLI

### 3.4 Mandatory services for v1

The MVP should assume these services exist from the beginning:

- PostgreSQL
- Web frontend
- API/control plane
- Worker process
- Execution runner with container access

These are not optional nice-to-haves. They are part of the baseline product shape.

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

Some of these may appear later, but they should not be part of the initial local lab baseline.

---

## 4. Recommended Machine Profiles

### 4.1 Minimum development profile

Use this when hosted models are acceptable and the machine is mainly for product development:

- 8 CPU cores
- 32 GB RAM
- 150 GB free SSD space
- Docker installed
- no local GPU required

### 4.2 Recommended lab profile

Use this when the machine will also run local experiments and some local model inference:

- 12+ CPU cores
- 64 GB RAM
- 1 TB NVMe storage
- NVIDIA GPU with enough VRAM for the target workload
- Docker + NVIDIA Container Toolkit

### 4.3 Storage expectation

Storage pressure will come from four places:

- arXiv metadata warehouse
- cached full-text or PDF fetches
- dataset caches
- experiment artifacts and workspaces

The repo should stay small. Large state belongs under a configurable local data root, not inside the git repository.

---

## 5. Local Runtime Model

### 5.1 Development mode

During normal development, the system should run with a split model:

- infrastructure in containers
- application code on the host with hot reload

That means:

- Postgres runs in Docker Compose
- optional local model servers can run in Docker Compose
- API runs locally via `uv`
- worker runs locally via `uv`
- web frontend runs locally via `npm`

Why this is the default:

- faster edit/run/debug loop
- easier stack traces and debugging
- easier IDE integration
- no need to rebuild the whole app container for every backend change

### 5.2 Reproducible demo mode

A second startup path should exist for demos and onboarding:

- bring up Postgres
- bring up API
- bring up worker
- bring up frontend
- optionally bring up a local model server

This can be done with Docker Compose profiles once the first vertical slice is stable.

### 5.3 Dynamic experiment execution

Experiment containers are **not** long-running compose services.

They are created on demand by the execution runner. Each run gets:

- its own isolated workspace
- a selected base image
- mounted dataset references
- a mounted artifact output path
- explicit resource limits
- a unique run identifier and telemetry stream

---

## 6. Repository Shape

The monorepo should follow this general structure:

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
    adapters/
      arxiv/
      corpus/
      llm/
      embeddings/
      git/
      container/
      benchmark/
  prompts/
    planning/
    literature/
    ideation/
    coding/
    verification/
    reporting/
  configs/
    problems/
    policies/
    models/
    execution/
    prompts/
  docs/
    context/
  tests/
    unit/
    integration/
    fixtures/
  scripts/
```

### 6.1 Structure rules

- Canonical schemas must live in one place.
- Core domain code must not depend directly on vendor SDK details.
- Adapters can depend on core interfaces, not the other way around.
- Prompts are versioned assets, not long strings hidden in Python files.
- Config for problems, policies, and model routing should live in files, not prompt text.
- Notebooks may exist for exploration, but not as the product backbone.

---

## 7. Package and Dependency Baseline

### 7.1 Backend dependencies

The first backend pass should assume the following libraries or equivalents:

- FastAPI
- Pydantic v2
- SQLAlchemy 2
- Alembic
- `psycopg`
- `httpx`
- `tenacity`
- `structlog` or equivalent structured logging layer
- `typer`
- `jinja2` or a similarly simple templating layer for reports and prompts where needed
- `orjson` where fast JSON serialization materially helps

### 7.2 Python tooling

- `uv` for dependency and virtual environment management
- `ruff` for linting and formatting
- `pytest` for tests
- `pyright` for static type checking
- `testcontainers` for integration tests that need Postgres or Docker-managed services

### 7.3 Frontend dependencies

The first web UI should stay thin. Use:

- React
- TypeScript
- Vite
- TanStack Query
- Tailwind CSS
- a small component layer, not a large enterprise UI framework
- `react-markdown` or equivalent sanitized markdown rendering stack for report viewing

### 7.4 Avoidable dependency creep

Do not add large framework dependencies unless they remove a real bottleneck.

Examples to avoid in the first pass:

- enterprise workflow engines
- large state-management frameworks the UI does not need
- dedicated search clusters
- notebook-centric orchestration products

---

## 8. Service Breakdown

### 8.1 API / Control Plane

Responsibilities:

- create, update, and inspect research cycles
- expose research state and reports to the UI
- create approval requests
- enqueue jobs
- stream event timelines and run telemetry
- provide a small health and admin surface

Implementation notes:

- FastAPI should be enough for the MVP
- prefer SSE for one-way telemetry first
- use normal HTTP endpoints for pause, cancel, resume, approve, reject, and re-run actions

### 8.2 Worker Process

Responsibilities:

- claim jobs from Postgres
- run typed operators
- persist outputs before enqueueing downstream work
- emit domain events and operator reports
- request approvals when policy blocks the next step

Implementation notes:

- one worker process is enough for the first pass
- concurrency should be limited and explicit
- job claiming should use `FOR UPDATE SKIP LOCKED` or equivalent safe row-claim semantics
- every long-running job should heartbeat so stalled jobs can be recovered

### 8.3 Execution Runner

Responsibilities:

- create or reuse the correct execution image
- create a git worktree workspace
- mount data and artifact paths
- start the experiment container
- stream logs and status back to the system
- collect outputs into a `RunRecord`

Implementation notes:

- this can begin as a library used by the worker
- if it grows complex, it can become a dedicated service later
- the core requirement is durable run control, not service count purity

### 8.4 Web Frontend

Responsibilities:

- show research cycles
- show literature triage progress and shortlist decisions
- show hypothesis portfolio and experiment queue
- show active runs and live telemetry
- show reports, verification outputs, and postmortems
- expose pause/cancel/approve controls

Implementation notes:

- the UI should exist in phase 1
- keep it narrow and practical
- the goal is control-tower visibility, not a polished analytics suite

### 8.5 CLI

Responsibilities:

- bootstrap a research cycle
- trigger or resume phases
- import internal corpus material
- export reports and artifacts
- provide a non-UI control path for power users

The CLI is still useful, but it is not the only required surface.

---

## 9. Durable State and Storage

### 9.1 Canonical state store

Use PostgreSQL as the system of record.

It should hold:

- research cycles
- jobs
- domain events
- approvals
- paper metadata
- evidence cards
- hypotheses
- experiment specs
- run records
- verification reports
- postmortems
- report metadata
- embeddings and retrieval references

### 9.2 Why Postgres is the canonical choice

We need one durable system that can support:

- relational records
- append-only audit history
- queue semantics
- hybrid retrieval support
- concurrent reads and writes
- restartable local operation

SQLite is attractive for tiny prototypes, but not for the product shape we have already chosen.

### 9.3 `pgvector`

Use `pgvector` inside Postgres for semantic retrieval.

It should be used for:

- title+abstract embeddings for arXiv metadata
- internal corpus documents
- evidence summaries
- historical reports
- failure postmortems

### 9.4 Postgres full-text search

Use Postgres full-text search for lexical retrieval in v1.

That is enough for:

- title and abstract search
- author and keyword search
- internal report keyword search
- operator-side filtering before semantic ranking

### 9.5 Filesystem artifact store

Artifacts should live under a configurable local data root.

Recommended variable:

- `MLLAB_HOME`

Recommended layout:

```text
$MLLAB_HOME/
  artifacts/
    runs/
    reports/
    postmortems/
    literature/
      html/
      pdf/
      notes/
  cache/
    arxiv/
    embeddings/
    datasets/
    models/
  workspaces/
  exports/
```

### 9.6 Artifact philosophy

Artifacts are durable evidence, not disposable scratch.

At minimum, preserve:

- generated patches
- run stdout and stderr
- metric snapshots
- verification outputs
- rendered reports
- literature notes
- failure analyses

---

## 10. Queue and Scheduling Approach

### 10.1 Queue pattern

Use a database-backed queue inside Postgres.

The queue should support:

- delayed jobs
- retries
- heartbeats
- job priority
- cancellation
- dead-letter or terminal failure state

### 10.2 Why not Redis/Celery first

A separate queue service adds moving parts before it adds real product value.

For a single-user local lab, the DB-backed queue gives us:

- durability
- auditability
- simpler operations
- easier debugging
- direct linkage between jobs and research state

### 10.3 Scheduler stance

The scheduler should stay modest in v1.

It should decide:

- what phase to run next
- whether an approval is needed
- which hypothesis or experiment has priority
- whether to continue exploration, experiment, verification, or reporting

It should not become a separate workflow platform.

---

## 11. Model Gateway and Routing

### 11.1 Model access stance

Support both **hosted** and **local** models from day one.

The system should present one internal model gateway that can route by task role.

Examples of task roles:

- planner
- literature triage
- synthesis
- critic
- protocol compiler
- coder
- verifier
- reporter

### 11.2 Gateway implementation shape

The internal gateway should normalize two families of backends:

- hosted provider SDKs
- local or self-hosted OpenAI-compatible endpoints

That lets us support combinations such as:

- strong hosted reasoning model for planning and critique
- local fast model for low-cost triage or report drafting
- code-specialized model for patch generation
- smaller verifier model for structured checks that still need LLM help

### 11.3 Local model stance

For local inference, prefer a backend that can expose an OpenAI-compatible API.

This keeps the control plane and worker code simple.

Two acceptable modes for the first pass are:

- a heavier GPU-backed local model server for stronger local inference
- a lighter local model server for development convenience

The product should not hard-code one local model serving product into the core architecture.

### 11.4 Routing policy

Routing should be file-based and explicit.

Example config shape:

```yaml
roles:
  planner: hosted_reasoner
  triage: local_fast
  synthesizer: hosted_reasoner
  critic: hosted_reasoner
  coder: code_model
  verifier: precise_reasoner
  reporter: local_fast
fallbacks:
  planner: [local_reasoner]
  coder: [hosted_reasoner]
```

### 11.5 Context discipline

Do not dump the whole lab state into every model call.

Instead, introduce task-scoped `ContextPack` builders.

Examples:

- `TriageContextPack`
- `EvidenceContextPack`
- `HypothesisContextPack`
- `CodingContextPack`
- `VerificationContextPack`
- `ReportContextPack`

Each pack should have:

- a clear token budget
- explicit allowed sources
- deterministic ordering rules
- truncation behavior
- provenance back to the records it was assembled from

This is a core product behavior, not prompt polish.

---

## 12. Prompt and Operator Assets

### 12.1 Prompt asset layout

Prompts should live in versioned files under `prompts/`.

Do not bury them in application code.

### 12.2 Operator contract

Each operator should be a typed unit of work with:

- input state reference
- config reference
- context pack reference
- model route
- output schema
- emitted events
- artifact references
- operator report

### 12.3 Prompt version tracking

Every operator result should record:

- prompt asset identifier
- prompt version or checksum
- model route used
- generation parameters where material

That record belongs in the durable run history, not only in logs.

---

## 13. Source Retrieval and Research Memory

### 13.1 arXiv strategy

The system should maintain a local Postgres-backed arXiv metadata warehouse.

That means:

- store arXiv metadata locally in Postgres
- keep title and abstract together as the default screening surface
- preserve `published_at` and `updated_at`
- support recency-aware ranking and filtering
- compute embeddings over combined title+abstract text
- support both broad metadata sync and targeted query expansion

### 13.2 arXiv ingestion modes

Use two ingestion modes:

- a bulk or incremental metadata harvester that keeps the local warehouse fresh
- targeted metadata lookups when a research cycle needs more coverage in a specific niche

The local warehouse should be the default query surface. Remote calls should top off coverage, not replace the warehouse.

### 13.3 arXiv retrieval policy

Default flow:

1. query local arXiv metadata warehouse
2. if coverage is insufficient, fetch additional metadata incrementally or through targeted lookup
3. shortlist using title+abstract together
4. escalate to HTML or other machine-readable full text when needed
5. fall back to PDF only when necessary

The system should not brute-force PDFs for a topic.

### 13.4 arXiv data layout

At minimum, preserve these fields:

- arXiv identifier
- title
- abstract
- authors
- categories
- primary category
- published timestamp
- updated timestamp
- version information when available
- comment, DOI, and journal reference when available
- canonical links for abstract page, HTML page when available, and PDF

### 13.5 Internal corpus support

The first internal corpus pass should support:

- local markdown notes
- previous run summaries and reports
- prior postmortems
- local papers and PDFs already owned by the user
- optionally selected research repo material

The initial system should value notes, reports, and existing research artifacts before trying to ingest entire code repositories.

### 13.6 Research memory layers

Treat these as distinct retrieval layers:

- arXiv metadata
- full-text notes or extracted sections
- internal corpus documents
- historical run reports
- failure postmortems

A hit in one layer is not equivalent to a hit in another. The UI and reports should preserve that distinction.

### 13.7 Optional benchmark adapters

Benchmark adapters can exist, but the core lab should not be shaped around one benchmark source.

Kaggle can be treated as one optional benchmark adapter for evaluation problems. It should not define the product architecture.

---

## 14. Research Problem Configuration

The lab should be driven by explicit problem configuration, not hidden prompt state.

A problem config should define:

- problem identifier
- human objective
- target metric and directionality
- source scopes
- dataset references
- evaluation harness
- execution budget
- hardware expectations
- reporting expectations
- approval policy overrides if any

Example shape:

```yaml
id: vision-noisy-label-robustness-v1
name: Improve noisy-label robustness for medium-scale image classification
objective: Improve macro_f1 over the declared baseline without increasing training cost by more than 20 percent.
sources:
  internal_corpus:
    enabled: true
    tags: [vision, noisy-labels]
  external:
    arxiv:
      enabled: true
      categories: [cs.CV, cs.LG]
      max_metadata_results: 500
      fulltext_budget: 20
      date_from: 2023-01-01
execution:
  gpu: required
  max_runtime_minutes: 180
  network: disabled
  image_strategy: on_demand
verification:
  rerun_required: true
reporting:
  generate_cycle_summary: true
model_profile: default_research
```

This config should be stored in `configs/problems/` and snapshotted into the research cycle at creation time.

### 14.1 Dataset and harness handling

The ML lab should treat datasets and evaluation harnesses as first-class runtime inputs.

That means:

- dataset files live outside the repo under the configurable local data root or another declared path
- each dataset reference should have a stable identifier and a recorded version, hash, or fingerprint when practical
- evaluation harness code lives in the repo and is versioned with the rest of the system
- every `RunRecord` should preserve the dataset reference and harness version it used

The experiment runner should mount datasets read-only where possible and should never assume that datasets belong in the git worktree.

---

## 15. Execution Backplane and Sandboxing

### 15.1 Execution backplane choice

Use Docker Engine as the default execution backplane for the MVP.

Why this is the default:

- it is widely supported locally
- GPU passthrough is practical with NVIDIA tooling
- isolated containers are a good baseline for untrusted generated code
- it pairs well with git worktrees and mounted artifact paths

Podman can remain a later compatibility target, not the canonical first path.

### 15.2 GPU support

GPU-capable experiment execution is a hard requirement for the ML lab.

That means:

- the execution runner must be able to request GPU access for a run
- GPU visibility should be controlled by the run spec
- the runtime should record whether a run used GPU resources and which device profile was requested

### 15.3 Workspace pattern

Each run should execute from its own git worktree.

Each workspace should preserve:

- parent commit
- generated patch or diff
- selected config files
- runtime image identifier
- run id

The main working branch should never be mutated by an experiment run.

### 15.4 Base image strategy

Use a mixed strategy:

- maintain a small number of reusable base images for common ML environments
- allow most task-specific images to be built on demand from problem config and experiment needs

This matches the current product direction better than trying to pre-build everything.

### 15.5 Image policy

Base images should be defined in config, versioned, and identifiable in `RunRecord`.

At minimum, record:

- image name
- image digest or immutable identifier
- CUDA or accelerator expectations when relevant
- key package set

### 15.6 Container policy defaults

Default run container behavior:

- network disabled
- dataset mounts read-only where possible
- workspace mount read-write
- artifact output mount writeable
- CPU, memory, and runtime limits enforced
- no secrets injected unless explicitly required
- stdout and stderr captured
- exit code captured

### 15.7 Telemetry from runs

The execution runner should stream:

- phase or step name if available
- log tail
- exit status
- resource usage summary
- heartbeat
- artifact update notifications

SSE is sufficient for the first UI pass.

---

## 16. Verification and Failure Memory

### 16.1 Verification requirement

Every experiment should be tested.

Verification should not be reserved only for top results.

At minimum, each completed run should produce:

- baseline comparison
- metric sanity check
- artifact presence check
- harness validity check
- verification summary

### 16.2 Structured failure memory

When a run fails or is rejected, the system should create a `FailurePostmortem` record.

That record should include as much structure as practical, including:

- failure class
- failure stage
- root cause hypothesis
- relevant log references
- impacted files or components
- whether the hypothesis changed
- whether new literature search is recommended
- recommended next action

### 16.3 LLM-assisted postmortem

The agent may help write and structure the postmortem, but the final record should preserve deterministic evidence such as:

- error type
- exit code
- log excerpts
- resource usage
- missing artifacts
- violated assumptions

### 16.4 Historical comparison

Verification and reporting should compare new results against:

- the declared current baseline for the problem
- prior internal runs for the same or related problem
- previously rejected approaches when relevant

This historical comparison is part of the product and should not be left to human memory.

---

## 17. Reporting and Human Readability

### 17.1 Report formats

The first report layer should emit:

- markdown source
- rendered HTML for UI viewing

This gives us:

- easy diffability
- inspectable artifacts
- easy export
- human-readable in-app viewing

### 17.2 Required report types

At minimum, support:

- literature screening summary
- shortlisted paper report
- evidence summary
- hypothesis review packet
- experiment run summary
- verification report
- failure postmortem
- cycle summary

### 17.3 UI viewing requirement

The web UI must render markdown reports so a user is not forced to read raw markdown files.

Raw markdown should still be available for export and version control.

---

## 18. Frontend Implementation Scope

### 18.1 Phase-1 pages

The first UI should include at least:

- research cycles list
- research cycle detail page
- literature triage view
- hypothesis portfolio view
- runs and telemetry view
- reports and postmortems view
- approvals and controls view

### 18.2 Interaction model

The UI should support:

- creating a new research cycle
- viewing progress by phase
- browsing events in time order
- inspecting the current shortlist and why items were escalated
- monitoring active runs
- cancelling or pausing runs
- approving or rejecting gated actions
- exporting reports

### 18.3 UI philosophy

The UI is a control surface, not a decoration layer.

If a human cannot tell what the lab is doing, why it is doing it, and how to intervene, the product is not ready.

---

## 19. Configuration and Secrets

### 19.1 Config sources

Configuration should come from two sources:

- versioned config files in `configs/`
- environment variables for secrets and machine-specific overrides

### 19.2 Settings loader

Use a typed settings layer based on Pydantic settings or an equivalent pattern.

### 19.3 Core environment variables

At minimum, expect variables for:

- environment name
- Postgres connection
- local data root
- enabled model providers
- provider API keys when used
- local model endpoint URLs when used
- container runtime configuration
- optional default GPU policy

### 19.4 Secret handling stance

For local development:

- use `.env` files excluded from source control
- do not store secrets in the database
- do not mount secrets into experiment containers unless explicitly needed

A more formal secret manager can wait until later.

---

## 20. Coding Standards

### 20.1 Backend code standards

- Prefer typed Python throughout.
- Use Pydantic models for boundary schemas.
- Keep SQLAlchemy models and domain schemas separate.
- Avoid passing untyped dicts across subsystem boundaries.
- Make operator inputs and outputs explicit and serializable.
- Make state transitions explicit in code, not implicit in prompt text.
- Keep policy logic in code and config, not in prompts.

### 20.2 Database standards

- Every schema change must go through migrations.
- Every major entity should have created/updated timestamps.
- Domain events should be append-only.
- Long text blobs should be allowed where useful, but core searchable attributes should still be normalized.

### 20.3 Prompt and model standards

- Prompts are versioned assets.
- Model routing is config-driven.
- Every material generation call should be traceable.
- Context packs must record their source references.

### 20.4 Frontend standards

- Keep components small and state ownership obvious.
- Prefer server-derived truth over duplicated local state.
- Treat the UI as an inspector and controller of durable state.

### 20.5 Git standards

- Keep the main branch human-owned.
- Experiments operate in worktrees.
- Generated code diffs should be preserved as artifacts.
- Accepted code changes should be reviewed before merging into long-lived branches.

---

## 21. Testing Strategy

### 21.1 Testing layers

The system should have four testing layers:

1. unit tests for pure domain logic
2. integration tests for storage, retrieval, and queue behavior
3. execution tests for sandbox and artifact handling
4. end-to-end smoke tests for the local vertical slice

### 21.2 Backend testing tools

Use:

- `pytest`
- `testcontainers` for Postgres and container-dependent integration tests
- fixtures for sample research cycles, paper metadata, and run artifacts

### 21.3 Frontend testing tools

Use:

- `vitest` for component and utility tests
- Playwright for a very small number of end-to-end UI tests

### 21.4 CI stance

A basic CI pipeline should run:

- lint
- type check
- unit tests
- CPU-only integration smoke tests

GPU execution tests can run manually or on a self-hosted runner later.

---

## 22. Logging, Telemetry, and Observability

### 22.1 Logging

Use structured logs throughout.

Every log line that matters should carry:

- research cycle id
- operator id or run id
- job id when relevant
- severity
- event type

### 22.2 Domain events

The system should treat domain events as the primary explainability timeline.

Logs help engineering. Domain events help users and reports.

### 22.3 Metrics stance

The MVP does not need a full Prometheus/Grafana stack.

It does need:

- job counts by status
- active runs
- average phase timings
- failure class counts
- verification outcomes

These can be derived from Postgres and surfaced in the UI first.

### 22.4 Telemetry transport

Use SSE first for live updates to the UI.

WebSockets can wait unless we prove we need them.

---

## 23. Security and Execution Safety

### 23.1 Untrusted code stance

Generated or modified experiment code must be treated as untrusted.

### 23.2 Default protections

- container isolation required
- network disabled by default
- dataset mounts read-only where possible
- resource ceilings enforced
- secrets not passed into runs by default
- no direct execution on the host shell

### 23.3 Gated exceptions

The following should require an explicit approval or policy allowance:

- network-enabled experiment runs
- unusually large compute requests
- external writes or submissions
- full-text budget overrides beyond policy

---

## 24. Build and Startup Workflow

### 24.1 Default local boot sequence

The default development flow should look like this:

1. start Postgres
2. run migrations
3. start API locally
4. start worker locally
5. start frontend locally
6. optionally start local model endpoint

### 24.2 Developer commands

The repo should expose simple commands for:

- install backend deps
- install frontend deps
- run migrations
- start API
- start worker
- start web UI
- run tests
- seed sample data
- import corpus materials

Use either a small `Makefile` or clearly named scripts, but keep the command surface obvious.

### 24.3 Deployment stance

There is no cloud deployment requirement for the first milestone.

The deployable unit for the MVP is a single local machine.

A packaged local demo stack can come later, but should follow the same architecture rather than inventing a second one.

---

## 25. Deferred Decisions

The following decisions should remain open for now:

- exact hosted model vendors
- exact local model server product
- exact set of benchmark adapters beyond the first research problems
- whether verification will eventually use additional deterministic static-analysis tools
- whether experiment telemetry later needs WebSockets instead of SSE
- whether artifact storage later moves to object storage
- whether remote workers are needed after the local lab is stable

These are important, but they should not block scaffolding the MVP.

---

## 26. Immediate Next Engineering Moves

The next engineering tasks implied by this document are:

1. scaffold the monorepo
2. stand up Postgres with `pgvector`
3. create the core schema and migration baseline
4. implement the research cycle API and DB-backed job queue
5. build the worker shell and operator contract
6. build the phase-1 web shell with SSE event streaming
7. implement the arXiv metadata warehouse and title+abstract triage path
8. implement the git worktree + Docker execution runner with GPU support
9. implement verification and postmortem records
10. wire report generation to markdown plus rendered HTML

---

## 27. Decision Summary

The first implementation should be built around this concrete stack:

- Python 3.12 + `uv`
- FastAPI + Pydantic + SQLAlchemy + Alembic
- React + TypeScript + Vite + Tailwind
- PostgreSQL + `pgvector`
- DB-backed queue
- Docker Engine + NVIDIA Container Toolkit for experiment execution
- git worktrees for per-run isolation
- local filesystem artifact store under `MLLAB_HOME`
- provider-agnostic model gateway with both hosted and local backends
- markdown reports rendered in the web UI
- research-problem configs as versioned YAML

This is the technical baseline for the local ML laboratory MVP.
