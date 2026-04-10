# Tech Context

**Product:** Synthetos (ML Laboratory Co-Scientist)\
**Role:** Engineer\
**Status:** Working Draft v5\
**Scope:** Local small-scale ML laboratory with autonomy roadmap\
**Last Updated:** 2026-04-09

---

## 1. Purpose

This document translates the revised product requirements, system patterns, and phased implementation plan into concrete technical choices for the first build.

It answers these questions:

1. What stack are we actually using first?
2. How do discovery, paper analysis, execution, remediation, and autonomy work in practice?
3. Which services are required versus optional?
4. How do we handle retrieval, reranking, graph construction, skill loading, execution, and orchestration concretely?
5. Which technical decisions are locked now, and which are intentionally deferred?
6. How do we keep the first implementation local, inspectable, and extensible without making it fragile?

This document is downstream of `prd.md`, `system_patterns.md`, and `phased_implementation_plan.md`.

---

## 2. Working Assumptions

This tech context assumes the following product decisions are already in force:

- The product is **research-problem-first**, not competition-first.
- The first release is an **ML laboratory**, not a generalized science platform.
- The lab should work against **both internal and external sources**.
- Discovery is **metadata-first**, with **title and abstract reviewed together** before any deeper read.
- Discovery should maintain **explicit discovery state** and synchronized structured outputs.
- Paper analysis runs at **two depths**:
  - metadata-depth analysis always during discovery
  - full-text paper analysis only after shortlist or later escalation
- Paper review artifacts are **separate but linked** and are generated **only** for papers that have reached full-text analysis.
- v1 retrieval modes are **Stable** and **Discovery**.
- Reranking is **automatic by default**, but must be budget-aware and degrade gracefully.
- We want **automated low-risk experimentation** without requiring a human to approve every run.
- We still need a **phase-1 UI** with live telemetry, reports, controls, and intervention points.
- The execution layer must support **GPU-capable isolated workloads**.
- Different stages of the workflow may use **different models** behind one routing layer.
- Every experiment should produce durable artifacts, verification output, and when it fails, a **structured postmortem**.
- Mechanical failures should route through **auto-remediation** before being treated as full scientific failure cases.
- Successful runs should eventually receive **directional signal** and **frontier tracking**.
- Checkpoint gates are **off unless configured** by policy, profile, or user preference.
- Modular behavior must be supported through **`skill.md` packages**.
- Third-party skill signing is **not required** in the first local release.  Instead we use validation, capability declaration, hashes, and trust tiers.
- External orchestrators must be supported through a **stable API plus telemetry streams**.
- Cross-charter pattern memory should be **light-touch by default**, with no mandatory human verification before a pattern can begin influencing planning.
- In v1, the local internal corpus is a seeded arXiv metadata mirror. It starts from a pre-populated seed and is incrementally updated through harvesting. Full text is fetched only on demand for shortlisted papers.

---

## 3. Canonical Technical Decisions

The following choices should be treated as the default implementation path for the MVP and early autonomy roadmap.

### 3.1 Host platform targets

- **Primary host target:** Linux workstation
- **Secondary dev target:** macOS for non-GPU development and UI/API work
- **Windows stance:** not a first-class target; use WSL2 only if needed

### 3.2 Primary languages

- **Backend, workers, adapters, orchestration, verification, remediation, memory:** Python
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
- **Durable state:** PostgreSQL + `pgvector` + Apache AGE
- **Queue:** Postgres-backed jobs table with row-claim semantics
- **Artifact store:** local filesystem
- **Execution backplane:** Docker Engine (sibling containers, not DinD)
- **GPU:** NVIDIA Container Toolkit with GPU passthrough (2x RTX 6000 Blackwell)
- **Workspace isolation:** git worktrees
- **Telemetry stream:** domain events persisted in Postgres and exposed through SSE first
- **CLI:** Typer-based Python CLI
- **Embeddings:** gte-modernbert (768 dimensions)
- **Full-text extraction:** Docling for shortlisted papers

### 3.4 Database stance

The agreed database posture is:

- **PostgreSQL** is the canonical system of record
- **`pgvector`** provides semantic retrieval in the same Postgres instance
- **Apache AGE** provides graph storage and graph traversal in the same Postgres instance
- we do **not** introduce a separate external graph database in v1

This lets us keep transactional state, vector retrieval, and graph-oriented queries in one local database deployment.

### 3.5 Mandatory services for v1

The MVP should assume these services exist from the beginning:

- PostgreSQL
- web frontend
- API/control plane
- worker process
- execution runner with container access

### 3.6 Explicitly not required in v1

The MVP should not require these services to be usable:

- Redis
- Celery
- Airflow
- Temporal
- Elasticsearch/OpenSearch
- MLflow
- Kubernetes
- object storage
- separate external graph database
- separate real-time messaging broker

---

## 4. Local Runtime Model

### 4.1 Development mode

During normal development:

- infrastructure (Postgres) runs in Docker Compose containers
- application services (API, worker, web) run on the host with hot reload
- experiment containers are spawned as sibling Docker containers with GPU passthrough

That means:

- Postgres runs in a local container via docker-compose
- optional local model servers (LMStudio, Ollama, VLLM) run on the host
- API runs on host via `uv run uvicorn`
- worker runs on host via `uv run python -m apps.worker`, with Docker SDK access to launch experiment containers
- web frontend runs on host via `npm run dev` (Vite)

The worker uses the Docker SDK to create experiment containers directly on the host Docker daemon, enabling GPU passthrough without Docker-in-Docker complexity.

### 4.2 Reproducible demo mode

A second startup path should exist for demos and onboarding:

- `docker compose up postgres` for infrastructure
- `uv run uvicorn apps.api:app` for API
- `uv run python -m apps.worker` for worker
- `npm run dev` for frontend
- optionally start a local model server (LMStudio, Ollama, or VLLM)

### 4.3 Dynamic experiment execution

Experiment containers are **not** long-running compose services.

They are created on demand by the execution runner.  Each run gets:

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
- discovery and analysis read surfaces

### 6.2 Worker service

Responsibilities:

- claim queued jobs from Postgres
- run operators
- coordinate skill resolution and context assembly
- emit domain events and reports
- launch execution runs through the execution runner

### 6.3 Web service

Responsibilities:

- render charter and cycle dashboards
- render discovery views and reports
- render paper analysis packets and review artifacts
- show run telemetry, frontier state, and approvals
- expose skill catalog and skill usage history

### 6.4 CLI

Responsibilities:

- local developer control
- debugging and fixture workflows
- direct charter and cycle creation plus replay helpers
- skill validation commands
- pattern inspection and export helpers

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
- enforce trust tier restrictions

In v1 this is also a library/module invoked by workers and surfaced through the API.

### 6.7 Pattern memory runtime

Responsibilities:

- consolidate `CanonicalPattern`s from completed work
- apply threshold and staleness logic
- expose reusable patterns for planning, remediation, and retrieval

In v1 this can be a library/module plus scheduled worker jobs, not a separate service.

---

## 7. Canonical Storage Design

### 7.1 Database role

PostgreSQL is the system of record for:

- research charters, research cycles, and state transitions
- jobs and job claims
- domain events and audit history
- papers and source records
- discovery sessions, discovery views, and ranking outputs
- paper-analysis packets and review artifacts
- evidence, hypotheses, experiment specs, and reports
- runs, remediation actions, verification reports, frontier state, and canonical patterns
- skills, skill bindings, and skill execution records
- orchestrator clients, sessions, commands, and approvals
- embeddings and retrieval metadata references
- graph-oriented storage and traversal through Apache AGE

`pgvector` should be enabled in the same Postgres cluster for semantic retrieval.  Apache AGE should also be enabled in the same Postgres cluster for graph storage and traversal over paper graphs, citation graphs, and lineage graphs.

### 7.2 Filesystem role

The filesystem stores:

- discovery exports
- paper-analysis exports
- paper review artifacts
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

The git repo should stay relatively small.  Large caches and artifacts should live under the data root.

### 7.4 Suggested database grouping

Use logical schema grouping or at least naming boundaries for:

- `research_*`
- `source_*`
- `discovery_*`
- `analysis_*`
- `execution_*`
- `verification_*`
- `memory_*`
- `report_*`
- `skill_*`
- `orchestrator_*`
- `audit_*`

---

## 8. Discovery and Retrieval Technical Design

### 8.1 Discovery state model

At minimum, discovery should persist:

- `DiscoverySession`
- structured query spec
- retrieval mode (`stable` or `discovery`)
- source filters and time filters where applicable
- candidate paper set
- dedup decisions
- ranking features and scores
- reranking status and fallback reason if reranking was skipped
- shortlist decisions and rationale
- discovery artifacts and metrics

### 8.2 arXiv strategy

arXiv is the primary internal corpus. The full arXiv dataset is already downloaded and embedded using gte-modernbert (768 dimensions).

Technical stance:

- seed the local corpus from a pre-populated arXiv metadata dataset
- store title, abstract, categories, authors, dates, ids, and links in Postgres
- pre-computed embeddings already exist for the full corpus
- support incremental sync from a bulk metadata harvester for new papers
- when a paper is shortlisted for full-text analysis, try HTML first
- if HTML is unavailable or low quality, download the PDF and process it with Docling
- normalize either full-text path into the same internal content representation for downstream chunking and analysis
- treat HTML fetch and PDF fetch as separate escalation operations with explicit provenance

### 8.3 External source strategy

Initial external sources should be adapter-backed and normalized into a common `PaperCard` shape.

Likely initial adapters:

- Semantic Scholar
- OpenAlex
- DBLP where useful
- limited web fallback for source clarification or recent items when required by policy

### 8.4 Retrieval strategy

Use hybrid retrieval, but keep lexical retrieval mandatory as the reliable baseline:

- lexical search in Postgres full-text search with structured relational filters
- vector search via `pgvector`
- structured filters for source type, recency, relevance, and read depth
- optional reranking over a first-stage candidate set
- graph-oriented retrieval through Apache AGE where path structure materially improves results

The canonical database stance is:

- Postgres full-text and relational filtering for lexical and structured retrieval
- `pgvector` in Postgres for semantic retrieval
- Apache AGE in Postgres for graph-oriented retrieval where path structure matters, especially for paper-analysis graphs, citation traversal, and lineage-aware navigation

### 8.5 Stable and Discovery views

**Stable mode** should optimize for precise, reproducible, confidence-leaning retrieval.

**Discovery mode** should preserve novelty and diversity without collapsing results into near-duplicates.

Recommended implementation stance:

- Stable: stronger weight on lexical relevance, shortlist fit, and confidence-oriented ranking features
- Discovery: stronger diversity and novelty terms, plus a postprocessing diversity pass
- Both modes may use automatic reranking when allowed by budget and latency policy

### 8.6 Automatic reranking behavior

Reranking should be **automatic by default**.

Recommended behavior:

- rerank the top-N first-stage candidates when:
  - reranker is available
  - latency and budget thresholds allow it
  - candidate count is large enough to justify reranking
- skip reranking when:
  - reranker is unavailable
  - current request or profile disables it
  - latency or budget policy blocks it

Important rule:

- reranking failure should **not** block discovery
- the system must fall back to first-stage ranking and record the reason

### 8.7 Evaluation support

When a ground-truth target is available, discovery should support:

- hit rate
- MRR
- Recall\@K
- Precision\@K

These metrics should be persisted to the discovery session for comparison of search configurations.

---

## 9. Paper Analysis Technical Design

### 9.1 Two-depth analysis implementation

**Depth 1: metadata analysis**

Implemented as part of the discovery operator output.  No full-text ingestion required.

**Depth 2: full paper analysis**

Triggered only for shortlisted papers or later explicit escalation.

### 9.2 Full-text ingestion

Technical stance:

- HTML-first when a machine-readable source is available
- PDF fallback when HTML is unavailable or low quality
- HTML and PDF ingestion should converge into the same normalized internal full-text representation
- keep provenance by chunk, page, and source location
- normalize extracted elements into a consistent internal representation

### 9.3 Chunking

Prefer structure-aware chunking over naive token windows.

Chunk classes should include:

- section chunks
- paragraph chunks
- figure chunks with captions and nearby context
- table chunks with captions and nearby context
- equation chunks when useful

### 9.4 Graph model

The typed paper graph should support nodes such as:

- paper
- section
- concept
- method
- experiment
- dataset
- figure
- table
- equation

Edges should support structural and semantic relations such as:

- contained\_in
- defines
- proposes
- uses
- evaluates
- illustrates
- compares
- depends\_on

All nodes and edges should carry provenance, confidence, and verification metadata.

Implementation stance:

- keep canonical paper-analysis records in relational tables
- project graph-native relationships into Apache AGE within the same Postgres instance
- use AGE for graph traversal, neighborhood expansion, path queries, and graph-aware QA support
- avoid introducing a separate external graph database in v1

### 9.5 Graph-aware QA and locate

Implementation stance:

- index both chunks and graph node descriptions
- retrieve relevant chunks and nodes
- expand one-hop graph neighbors where useful
- return answers with supporting chunk references and linked graph elements
- support locate operations that return source locations and context snippets

### 9.6 Coverage verification

Coverage checks should compute at least:

- section coverage
- figure coverage
- table coverage
- equation coverage when extracted
- unlinked important artifacts

This should feed both UI diagnostics and downstream confidence handling.

### 9.7 Analysis and review artifact separation

`PaperAnalysisPacket` should store:

- structural extraction
- graph state
- provenance-linked evidence
- coverage diagnostics
- reproducibility notes

`PaperReviewArtifact` should store:

- strengths and weaknesses
- open questions
- critique and reading-priority guidance
- optional reviewer-style scoring

Important rule:

- review artifacts are only created for fully analyzed papers
- review artifacts are advisory and should never replace analysis packets as the canonical evidence artifact

---

## 10. Skill System Technical Design

### 10.1 Skill package format

Each skill is a directory rooted in `skill.md`.

Recommended structure:

```text
skills/
  literature/
    title_abstract_triage/
      skill.md
      hooks.py
      schemas/
      fixtures/
      tests/
```

### 10.2 `skill.md` contract

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
trust_tier_required: third_party_untrusted
---

# Title + Abstract Triage

## Purpose
Screen title and abstract together to decide shortlist priority.
```

### 10.3 Skill loader and validator

Implementation stance:

- parse frontmatter from `skill.md`
- validate against a Pydantic `SkillManifest`
- store the rendered body as the human-readable instructions
- compute a content hash for version tracking
- validate optional `hooks.py` exports when present
- reject malformed or unsafe skill packages during load

### 10.4 Skill trust tiers

Use trust tiers rather than mandatory signing in the first local release.

Suggested tiers:

- `first_party_trusted`
- `user_local_trusted`
- `third_party_untrusted`

Capabilities that should require stronger trust include:

- Python hooks
- network access
- filesystem writes outside artifact roots
- run-control mutations

### 10.5 Skill resolution

The worker should resolve skills using:

- operator type
- phase
- research problem profile
- policy and capability requirements
- trust tier
- enable/disable flags
- explicit cycle-level bindings

The result should be a **small bound skill set** per operator invocation.

### 10.6 Skill persistence model

Minimum tables or entities:

- `SkillDefinition`
- `SkillVersion`
- `SkillBinding`
- `SkillExecutionRecord`
- `SkillValidationIssue`

### 10.7 Skill hooks

Allow optional deterministic helper hooks in `hooks.py` for narrow use cases such as:

- pre-assembly context shaping
- deterministic scoring helpers
- post-processing and validation of structured outputs

Do **not** let hooks become an alternate orchestration system.

---

## 11. Orchestrator API Technical Design

### 11.1 API style

The v1 orchestrator surface should be:

- **REST/JSON** for durable resource operations
- **SSE** for real-time event and telemetry streams
- **OpenAPI 3.1** for schema visibility and client generation

Do not split this into a separate gateway service in v1.  Keep it in the same FastAPI control-plane service.

### 11.2 Core resources

Suggested resource families:

- `/api/v1/charters`
- `/api/v1/cycles`
- `/api/v1/state`
- `/api/v1/discovery`
- `/api/v1/papers`
- `/api/v1/analysis`
- `/api/v1/evidence`
- `/api/v1/hypotheses`
- `/api/v1/experiments`
- `/api/v1/runs`
- `/api/v1/reports`
- `/api/v1/approvals`
- `/api/v1/skills`
- `/api/v1/patterns`
- `/api/v1/orchestrators`
- `/api/v1/events/stream`

### 11.3 Must-have actions

The API must support:

- create and update research charters
- create, resume, and update research cycles
- read charter-scoped state snapshots
- list and fetch discovery artifacts
- list and fetch analysis packets and review artifacts
- request allowed operator execution
- pause, cancel, and resume allowed jobs or runs
- submit notes or steering directives
- fetch skill catalog and skill usage history
- read pending approvals and record allowed decisions
- subscribe to domain events and run telemetry

### 11.4 Auth and scopes

Use local API tokens with explicit scopes in v1.

Suggested scopes:

- `charters.read`
- `charters.write`
- `cycles.read`
- `cycles.write`
- `state.read`
- `discovery.read`
- `analysis.read`
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

### 11.5 Event streaming model

Use **SSE first**.

Event delivery approach:

- persist domain events in Postgres
- expose stream endpoints that tail events by `last_event_id`
- allow clients to resume from checkpoints
- expose run telemetry as event records or structured stream chunks

This is simpler and more durable than a separate real-time broker in v1.

### 11.6 Idempotency and retries

For externally triggered mutations, support:

- client-supplied idempotency key where useful
- safe retry behavior for command endpoints
- explicit status responses for already-applied actions

### 11.7 Client SDK

Ship a minimal Python SDK first.

Responsibilities:

- token handling
- typed models
- event stream helper
- convenience methods for common actions

---

## 12. Model Gateway and Routing

### 12.1 Routing model

The model gateway should support role-based routing.

Suggested logical roles:

- planning / orchestration
- retrieval synthesis
- metadata analysis
- paper analysis
- paper review
- hypothesis generation
- protocol drafting
- coding
- remediation / debugging
- evaluation / verification
- report writing
- summarization / context compression

### 12.2 Hosted and local model support

The gateway must support all of the following from day one:

- **Local (OpenAI-compatible API):** LMStudio, Ollama, VLLM-compatible endpoints
- **Hosted frontier:** OpenAI, Anthropic (native SDK), Google (native SDK)

A cycle, operator, or skill may prefer one model route, but the control plane should own the final routing decision.

**Structured output** is critical: most generated data should be validated via structured output (JSON mode / tool-use based). The gateway must support structured output across all providers.

### 12.3 Recording requirements

Every model call that affects durable outputs should record:

- provider or local runtime
- model identifier
- prompt or template identifier
- major generation parameters
- cost or token usage when available
- bound skills in effect

---

## 13. Execution Backplane

### 13.1 Base images

Use a mix of:

- a few reusable base images for common ML stacks
- on-demand image builds for research-problem-specific needs

Most specialized environments should be built on demand from config, not pre-baked forever.

### 13.2 Runner contract

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

### 13.3 GPU support

GPU passthrough should be allowed only when the `RunSpec` and policy allow it.

### 13.4 Telemetry capture

The runner must capture:

- stdout and stderr
- structured status transitions
- resource usage snapshots
- metric outputs
- artifact manifests

### 13.5 Failure capture

The runner must classify failures and persist the classification into `RunRecord` and postmortem generation inputs.

---

## 14. Remediation Technical Design

### 14.1 Remediation stance

Mechanical failures should be retried before a full scientific postmortem is generated.

### 14.2 Failure classes

At minimum support:

- `dependency_failure`
- `oom_or_resource_limit`
- `timeout`
- `runtime_exception`
- `metric_parse_failure`
- `invalid_artifact_output`

### 14.3 Remediation operator

Add an `auto_remediate_operator` that runs before the postmortem operator.

Input should include:

- failure classification
- stderr and run logs
- generated code or relevant patch lineage
- experiment spec
- prior remediation attempts

### 14.4 Fix primitives

Support fix actions such as:

- run-level mutations
- spec-level mutations
- dependency additions
- code patching
- profile step-up where policy allows
- timeout extension where policy allows

### 14.5 Remediation policy

Recommended config area:

```yaml
remediation:
  enabled: true
  max_attempts_per_run: 3
  allowed_fix_types:
    - add_dependency
    - reduce_batch_size
    - step_up_profile
    - extend_timeout
    - modify_hyperparameter
    - patch_code
  blocked_fix_types:
    - change_base_image
  model_route: debugger
```

Important rule:

- if remediation fails or is exhausted, the system falls through to full postmortem generation with the remediation history attached

---

## 15. Verification, Signal, and Frontier Design

### 15.1 Verification stance

Every experiment should be tested and verified.

Minimum verification bundle:

- baseline comparison
- historical comparison
- artifact validation
- schema and split checks where applicable
- metric sanity checks
- promotion or rejection decision

### 15.2 Directional signal

Add a `DirectionalSignal` concept to successful or valid runs.

Suggested signal classes:

- `advancing`
- `stalled`
- `regressing`
- `noisy`
- `breakthrough`

### 15.3 Frontier tracking

Maintain a `MetricFrontier` per charter and hypothesis line.

Store at least:

- best metric value
- best run id
- direction of improvement
- runs since last improvement
- constraint status where relevant

### 15.4 Quick critic pass

Support an optional low-cost self-critic before the full verification suite where useful.  This is a pre-filter, not a replacement for deterministic checks.

### 15.5 Feedback loops

Verification, signal, and frontier outputs should feed back into:

- hypothesis ranking
- next-step recommendations
- autonomous planning
- canonical pattern memory

---

## 16. Autonomy and Pattern Memory

### 16.1 Autonomy modes

Support:

- `supervised`
- `autonomous`

Checkpoint gates should be **off unless configured**.

### 16.2 Budget tracking

Cycle-level budgets should support at least:

- total compute budget
- total run budget
- wall-clock budget
- per-hypothesis run budget

### 16.3 Autonomous loop support

The loop should support:

- select hypothesis
- compile or update experiment spec
- execute
- remediate if needed
- verify
- classify signal
- continue, vary, pivot, or regenerate
- stop on budget or policy boundary

### 16.4 Repetition detection and summarization

Add technical support for:

- repeated-spec detection
- low-variance repeated-result detection
- long-history summarization and context compression

### 16.5 Canonical pattern memory

`CanonicalPattern` should capture at minimum:

- pattern type
- polarity
- trigger conditions
- proven actions
- disproven actions
- evidence count
- supporting references
- staleness context
- last validated timestamp

### 16.6 Pattern influence thresholds

Patterns may begin influencing planning without mandatory human verification, but should still pass internal thresholds such as:

- minimum evidence count
- acceptable confidence
- compatible environment assumptions
- no strong staleness warning

Human review can still promote patterns to higher-trust use.

---

## 17. UI and Report Rendering

### 17.1 Phase-1 UI views

The first UI should include:

- cycle list and cycle detail
- discovery view with Stable and Discovery modes
- event timeline
- paper shortlist and escalation view
- paper analysis packet view
- paper review artifact view
- hypothesis and experiment queue view
- active run telemetry view
- frontier and verification view
- reports and postmortems view
- skill catalog and usage view
- approvals panel

### 17.2 Report rendering

Reports should be stored as Markdown and rendered to HTML in the UI.

Why this is the default:

- markdown is easy to diff and generate
- rendered HTML is readable for users
- the same artifact is useful for coding agents and humans

### 17.3 Artifact access

The UI should link to logs, patches, report bundles, discovery exports, and analysis artifacts through API-served metadata, not direct filesystem assumptions.

---

## 18. Config and Secrets

### 18.1 Config loading

Use:

- checked-in YAML config for default profiles
- environment variables for secrets and machine-specific overrides
- optional per-user local override files ignored by git

### 18.2 Important config domains

- database
- data root
- model providers
- skill discovery paths
- discovery backends and reranker controls
- problem profiles
- policy thresholds
- remediation settings
- autonomy settings
- pattern thresholds
- execution profiles
- telemetry settings
- orchestrator token scopes

### 18.3 Example environment variables

```text
LAB_ENV=dev
LAB_DB_URL=postgresql+psycopg://...
LAB_DATA_ROOT=/path/to/data
LAB_REPO_ROOT=/workspace
LAB_HOST_REPO_ROOT=/host/path/to/repo
LAB_MODEL_CONFIG=/path/to/models.yaml
LAB_SKILL_PATHS=/repo/skills:/user/skills
LAB_LOCAL_MODEL_BASE_URL=http://localhost:11434
VITE_LAB_API_BASE=http://127.0.0.1:8000
```

---

## 19. Testing Strategy

### 19.1 Unit tests

Cover:

- state transitions
- skill parsing and validation
- policy checks
- retrieval scoring helpers
- reranking fallback rules
- graph extraction helpers
- remediation parsing and fix-primitive validation
- directional signal helpers
- API schema models

### 19.2 Integration tests

Cover:

- worker claiming jobs from Postgres
- event streaming
- skill resolution and binding
- arXiv metadata retrieval path
- external source normalization
- discovery artifact generation
- paper analysis pipeline
- execution runner contract
- remediation flow
- verification and frontier pipeline

### 19.3 End-to-end tests

Cover:

- create cycle -> discovery -> shortlist -> paper analysis -> evidence -> protocol -> run -> verification -> report
- reranker available vs unavailable paths
- orchestrator client end-to-end control flow
- custom skill load and execution
- supervised vs autonomous loop behavior

### 19.4 Fixtures

Create reusable fixtures for:

- small literature sets
- internal reports and postmortems
- analyzed paper fixtures
- fake runs and metrics
- sample `skill.md` packages
- API tokens and scope models
- canonical pattern fixtures

---

## 20. Coding Standards

- prefer typed interfaces and explicit schemas over dynamic dict passing
- keep prompts versioned and stored as assets
- keep skills repo-visible and testable
- keep deterministic policy logic in Python and config, not prompt prose
- record all external side effects through durable events
- do not let the web UI become the only way to operate the system
- keep advisory artifacts clearly separated from canonical evidence artifacts

---

## 21. First Build Sequence

The first implementation sequence should be:

1. Postgres + migrations + base schemas
2. FastAPI control plane + OpenAPI docs
3. worker runtime + job queue + event stream
4. minimal web UI
5. skill loader + validation + catalog endpoints
6. research charter creation, cycle creation, and discovery pipeline
7. arXiv metadata warehouse and external source adapters
8. stable and discovery retrieval views
9. automatic reranking with graceful fallback
10. full paper analysis pipeline
11. evidence extraction and hypothesis portfolio
12. protocol compiler
13. execution runner and telemetry
14. remediation and directional signal
15. autonomous loop support
16. canonical pattern memory
17. orchestrator SDK and compatibility tests

---

## 22. Deferred Technical Choices

The following are intentionally deferred until after the MVP loop works:

- Redis or separate queue infra
- workflow engines like Temporal
- Elasticsearch/OpenSearch
- WebSocket as the primary stream protocol
- MCP facade on top of the orchestrator API
- object storage for artifacts
- remote worker pools
- signed third-party skill marketplace mechanics
- any separate external graph database beyond Postgres + Apache AGE

---

## 23. Recommended Immediate Next Step

Turn this into an initial repository bootstrap with:

- database schema stubs for discovery, analysis, remediation, and frontier state
- Postgres extension setup for `pgvector` and Apache AGE
- API resource skeletons for cycles, discovery, analysis, runs, and reports
- skill package template with trust-tier metadata
- first literature and analysis skills
- orchestrator token and event-stream scaffolding
- reranking policy and fallback scaffolding
- remediation action and directional signal schema stubs
