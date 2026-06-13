# AGENTS.md

This file gives coding agents a concise operating brief for work in this repository.

## Project Snapshot

- Product: **Synthetos**
- Goal: a single-user ML research system for end-to-end research loops
- Current state: **implemented through the supervised research loop, Phase 4 remediation/signal logic, Phase 5 autonomy, and canonical pattern-memory surfaces**
- Immediate focus: **stabilizing the full discovery -> analysis -> ideation -> protocol -> experiment -> verification -> recommendation/autonomy chain under real integration conditions**

This is not a planning-only repository. It contains working backend, worker, CLI, web, migrations, prompts, first-party skills, pilot fixtures, and unit/contract/integration coverage across the core research loop.

Treat the repo as an active single-researcher project, not a stable product. Schemas, APIs, CLI commands, artifact layouts, and migrations may still move.

## Source of Truth

Read these before making structural decisions:

- `README.md` - current public-facing feature set, quickstart, CLI, quality gates, and known rough edges
- `CLAUDE.md` - current repo-local architecture summary and operating notes
- `project_docs/co_scientist_prd.md` - product scope, MVP boundaries, user jobs, success criteria
- `project_docs/co_scientist_system_patterns.md` - architecture patterns, domain model, design rules
- `project_docs/co_scientist_tech_context.md` - implementation choices, stack, service layout, coding standards
- `project_docs/co_scientist_phased_implementation_plan.md` - roadmap and phase sequencing
- `project_docs/project_status.md` - latest focused status note; currently most useful for the Calm Console frontend redesign status

When documents disagree, prefer the current code and `README.md`/`CLAUDE.md`, then reconcile back to product docs before making architectural changes.

## What This System Is

Synthetos supports four connected research loops:

1. Discover
2. Analyze
3. Experiment
4. Learn

It is meant to behave like a bounded, inspectable research control tower, not a black-box swarm of chat agents.

The agency lives in deterministic code and typed operators. LLMs are used inside operators for probabilistic work such as synthesis, ideation, critique, report writing, and structured extraction; they do not own the orchestration loop.

Horizontal layers that matter across the loops:

- the **Skill system** for optional task-specific tools and context
- the **Orchestrator/API/SSE surfaces** for external control and telemetry
- the **Autonomy layer** for budgeted continue/vary/pivot/halt decisions
- the **Canonical pattern memory** for cross-cycle and cross-charter learning

## Current Repo Reality

Implemented today:

- **Phase 0 foundations:** FastAPI API, worker, Typer CLI, React web shell, auth/scope checks, jobs, domain events, SSE, Alembic migrations, core cycle/state flows
- **Job reliability:** `SELECT FOR UPDATE SKIP LOCKED` claiming, heartbeat supervision, cancellation, deadlines, transient retry/backoff, final-failure side effects, and traceback capture
- **LLM reliability:** role-based model routing, structured calls, validation feedback retry, truncation retry, endpoint concurrency caps, fallback chains, cancellation, and `llm_calls` lineage
- **Phase 1 discovery:** arXiv/internal-corpus metadata search, problem profiles, discovery sessions, metadata analysis, Stable/Discovery views, reports, evaluation hooks, resumable corpus import path
- **Phase 2 analysis:** HTML-first full-text ingestion with PDF+Docling fallback, structure-aware chunking, typed paper graphs with optional AGE projection, coverage diagnostics, review artifacts, persisted analysis reports, graph-aware QA/locate, evidence extraction, contradiction/redundancy detection
- **Phase 3 experiment:** hypothesis generation/critique/ranking, protocol compilation, git-worktree execution setup, sibling Docker runs, run telemetry, run control, deterministic verification, failure postmortems, and experiment web/API/CLI surfaces
- **Phase 4 remediation and signals:** auto-remediation for mechanical failures, retry lineage tracking, directional signal classification, hypothesis-line metric frontiers, deterministic next-step recommendations, remediation APIs/CLI, and experiment UI support for lineage/signal/recommendation state
- **Phase 5 autonomy:** opt-in supervised/autonomous cycle behavior, `loop_deciding`, budget-aware continue/vary/pivot/halt decisions, checkpoint gates, completion reporting, hypothesis lifecycle updates, repetition detection, and context summaries
- **Pattern memory:** canonical pattern consolidation from postmortems, remediations, signals, frontiers, and loop decisions; pattern injection into ideation/remediation/autonomy; curation/decay surfaces
- **Pilot harness:** bundled problem fixtures and CLI flows for contract-validated smoke/evaluation runs
- **Calm Console frontend:** current dashboard visual direction using warm-neutral tokens, pipeline rail, shell/sidebar, and redesigned primary routes

Still rough or incomplete:

- real-environment validation for all live model endpoints and longer autonomous runs
- complete browser verification of the Calm Console redesign across all routes
- consistent redesigned styling on older discovery, cycle, analysis, experiment, pattern-detail, and autonomy surfaces
- CLI parity for some API/dashboard write paths, including protocol compilation, run creation, pattern curation, and autonomy policy updates
- production hardening, multi-user isolation, and deployment guarantees

## Locked Architectural Decisions

Treat these as defaults unless a repository document explicitly changes them:

- Use operator-over-shared-state, not agent-to-agent hidden memory.
- `ResearchCharter` is the project definition; `ResearchCycle` is one bounded research loop within a charter; `ResearchState` is the logical aggregate of everything that has occurred within a charter.
- Keep orchestration explicit with state transitions and append-only domain events.
- Assume only one active charter at a time because GPU-heavy work is not meant to run concurrently.
- Prefer metadata-first literature triage before full-text ingestion.
- Use an HTML-first full-text path for shortlisted papers, with PDF plus Docling as fallback when HTML is unavailable or low quality.
- Keep the relational graph tables canonical; Apache AGE projection is optional and should degrade gracefully.
- Build task-scoped context packs instead of passing entire project state into every step.
- Keep the core deterministic and typed; use LLMs at the probabilistic edge.
- Put every external dependency behind adapters.
- Treat mechanical failures separately from scientific findings.
- Prompts define operator behavior; skills are optional augmentations, not replacements for prompts.
- Policy precedence is: hard system policy and token scopes, then user or charter settings, then autonomy or operator defaults.
- Services in `libs/core/services/` emit events inside the current DB session but do **not** commit; callers own transaction boundaries.
- API code uses async SQLAlchemy sessions; worker and CLI code use sync session factories. Do not mix them.
- Paper-keyed analysis reads use the **latest completed** analysis session.
- Experiment code provenance is generated-then-committed: generated files are written to a git worktree and committed before execution, and the commit SHA is the durable lineage anchor.
- Experiment containers run as sibling Docker containers with GPU passthrough, not Docker-in-Docker.
- Run control semantics are explicit: `pause`, `resume`, `cancel`, and `retry` are first-class behaviors, not just UI/API affordances.
- Telemetry is two-tiered: low-frequency orchestration events in `domain_events`, and high-frequency per-run telemetry in `run_telemetry`.
- Remediation and recommendation logic are **lineage-scoped**, not spec-wide: retry escalation, unresolved-failure checks, and recommendation inputs should be computed from the current `parent_run_id` chain.
- `DirectionalSignal` and `RunRecommendation` are **one-per-run artifacts** and should be updated/reused on replay rather than duplicated.
- Remediation read APIs reuse the existing `cycles.read` scope rather than introducing Phase-4-specific read scopes.
- `invalid_artifact` remediation should prefer a deterministic artifact-path rewrite when there is one clear filename/path mismatch, and only escalate to broad debug when the mismatch is ambiguous.
- Autonomous mode enters `loop_deciding` after verification; supervised mode proceeds to `reporting`.
- Phase 5 hypothesis lifecycle statuses (`active`, `promising`, `stalled`, `deprioritized`, `validated`) are system-managed by autonomy logic, not by the public hypothesis PATCH schema.
- Canonical patterns are shared memory artifacts, but they should inject as bounded context, not override deterministic policy or state-machine rules.

## Runtime Model

- Full-stack Docker Compose can run Postgres, migration, API, worker, and web.
- Host-mode development usually keeps Postgres in Docker while API, worker, CLI, and web run on the host.
- Experiment workloads run as sibling Docker containers with GPU passthrough.
- Artifacts are written under `LAB_DATA_ROOT`, including discovery, analysis, experiment, autonomy, and pilot report bundles.
- The Vite dev server proxies `/api` to `localhost:8000`.

## Actual Monorepo Shape

Current top-level structure:

```text
apps/
libs/
skills/
configs/
prompts/
tests/
project_docs/
docker/
experiments/
scripts/
```

Notable implemented app/library areas:

- `apps/api` - REST API routers for charters, cycles, state, jobs, events, skills, discovery, analysis, experiments, autonomy, and patterns
- `apps/worker` - job claimer/executor loop for discovery, analysis, ideation, protocol, execution, verification, remediation, recommendation, autonomy, and reporting operators
- `apps/cli` - Typer commands including DB, corpus, discovery, analysis, experiment, autonomy, patterns, and pilot flows
- `apps/web` - React/TanStack frontend using the Calm Console design direction
- `libs/core` - config, events, operators, state machine, run context, errors, tokens, and services
- `libs/discovery` - Phase 1 discovery pipeline
- `libs/analysis` - Phase 2 analysis pipeline
- `libs/ideation` - Phase 3 hypothesis generation, critique, and ranking
- `libs/protocols` - Phase 3 protocol compilation and spec validation, including autonomy-driven variation context
- `libs/execution` - Phase 3 workspace setup, container execution, metrics parsing, capture, and telemetry
- `libs/verification` - Phase 3 deterministic verification and failure postmortems
- `libs/remediation` - Phase 4 auto-remediation, signal classification, frontier tracking, and deterministic recommendation logic
- `libs/autonomy` - Phase 5 policy, budget, gates, lifecycle, repetition detection, context summaries, loop decisions, and completion reports
- `libs/patterns` - canonical pattern retrieval, injection, consolidation, decay, and upsert behavior
- `libs/goals` - goal-oriented surfaces/operators
- `libs/pilot` - pilot fixture orchestration and evaluation
- `libs/adapters` - LLM, embeddings, ingestion, graph, source, reranker, git, and container adapters
- `libs/prompts` - versioned prompt template loader
- `libs/storage` - SQLAlchemy models and Alembic migrations
- `libs/schemas` - canonical Pydantic boundary types

## Primary Stack

- Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, psycopg, Typer
- Frontend: React 19, TypeScript, Vite, TanStack Query, TanStack Router, Tailwind CSS 4
- Database: PostgreSQL with pgvector and optional Apache AGE
- Embeddings: `gte-modernbert`, 768 dimensions
- Model gateway: local OpenAI-compatible endpoints plus hosted OpenAI, Anthropic, and Google
- Execution: Docker/Podman plus git worktrees for isolation
- Tooling: `uv`, `ruff`, `pyright`, `pytest`, `vitest`, `Playwright`

Structured outputs are a first-class requirement. Generated data should validate into typed schemas whenever possible.

## State Machine

Cycles follow the strict DAG in `libs/core/state_machine.py`:

```text
created
-> discovery_ready
-> discovery_screened
-> analysis_ready
-> evidence_ready
-> portfolio_ready
-> protocol_ready
-> running
-> verifying
-> loop_deciding  # autonomous mode only
-> reporting
-> closed
```

In supervised mode, verification proceeds directly to `reporting`. In autonomous mode, the recommendation path targets `loop_deciding`, then `loop_decide` chooses whether to continue, vary parameters, pivot hypotheses, halt, pause on a checkpoint gate, or finish because a budget is exhausted.

## Internal Corpus

- The internal corpus is a seeded local arXiv metadata mirror.
- The arXiv metadata corpus is already downloaded and embedded, then incrementally updated through harvesting.
- Discovery stays metadata-first: review title and abstract together before escalating.
- Shortlisted papers move into HTML-first full-text extraction, with PDF+Docling as fallback.

## Implemented Domain Surfaces

Key entities that already exist in code and should usually be reused instead of reinvented:

- `ResearchCharter`, `ResearchCycle`, `ResearchState`
- `ProblemProfile`, `DiscoverySession`, `DiscoveryEvaluation`
- `PaperCard`
- `AnalysisSession`, `IngestedDocument`, `PaperChunk`, `GraphNode`, `GraphEdge`, `CoverageDiagnostic`
- `PaperAnalysisPacket`, `PaperReviewArtifact`, `EvidenceCard`
- `HypothesisSession`, `HypothesisCard`
- `ExperimentSpec`, `RunRecord`, `RunTelemetry`
- `VerificationReport`, `FailurePostmortem`
- `RemediationAction`, `DirectionalSignal`, `MetricFrontier`, `RunRecommendation`
- `CanonicalPattern`
- `AutonomyPolicy`, `AutonomyBudget`, `LoopDecision`, `AutonomyReportResponse`
- `SkillDefinition`
- `DomainEvent`, `Job`, `LLMCall`

## Implementation Guardrails

- Prefer typed models and explicit schemas at subsystem boundaries.
- Keep canonical schemas in `libs/schemas/`.
- Store prompts as versioned files under `prompts/`, not inline strings.
- Keep config in YAML plus environment variables, not prompt text.
- Every schema change should go through Alembic migrations.
- Record lineage for model calls, skill usage, reports, patterns, verification artifacts, and experiment commits.
- Preserve retry lineage via `RunRecord.parent_run_id`; do not introduce a second retry-history mechanism.
- Preserve the API/CLI -> service -> job -> operator -> domain event pattern instead of adding hidden workflow shortcuts.
- Keep container execution sandboxed by default: network disabled, data read-only, limits enforced.
- Add modular behavior through `skill.md` packages instead of hardcoding everything into the core.
- Build vertical slices that preserve durable artifacts and readable reports, not disconnected helpers.
- When changing prompt outputs, keep prompt examples and Pydantic schemas synchronized.
- Use `RetryableOperatorError` or registered transient exception classes for retryable failures; unknown operator errors are treated as permanent.
- Let the LLM reliability layer handle retries, validation feedback, truncation recovery, cancellation, and fallback instead of duplicating that logic in operators.
- When changing autonomous-loop behavior, preserve budget checks, gate handling, repetition detection, and deterministic decision records.
- When changing pattern-memory behavior, keep injection bounded, provenance visible, and curation/decay semantics intact.

## Agent Working Rules

- Treat the documents in `project_docs/` as design constraints, but inspect the implemented code before assuming roadmap text is already shipped.
- Preserve hexagonal boundaries; do not let domain code depend directly on vendor or transport layers.
- Optimize for inspectability, reproducibility, and durable state.
- Evidence before hypothesis before code: build flows that keep provenance visible.
- If you introduce a new subsystem, connect it back to one of the four core loops or a horizontal layer.
- Prefer extending existing discovery/analysis/experiment/autonomy patterns over inventing a second workflow style.
- When changing paper analysis behavior, make sure API, worker, schemas, CLI, prompts, and web contracts stay aligned.
- When changing paper-keyed analysis reads, preserve the latest-completed-session semantics unless product docs explicitly change them.
- When changing experiment behavior, keep run status, container state, telemetry, verification artifacts, remediation artifacts, and pattern inputs aligned.
- When changing Phase 3 operator behavior, preserve the generated-code -> committed-worktree -> container-run lineage chain unless the docs explicitly change it.
- When changing Phase 4 behavior, keep remediation history lineage-scoped, keep old resolved failures from polluting new successful recommendations, and preserve one-per-run signal/recommendation semantics.
- When changing Phase 5 behavior, keep supervised mode working, keep autonomous mode opt-in, and make every continue/vary/pivot/halt decision reconstructable from persisted state/events.
- When changing lineage UI or API behavior, keep `/runs/{id}/lineage` truthful for any node in the retry chain, not just roots.
- When changing frontend surfaces, follow the Calm Console design direction unless the task explicitly asks for a different variant.

## Expected Environment

Important environment variables called out in the repo guidance:

- `LAB_DB_URL`
- `LAB_ENV`
- `LAB_DATA_ROOT`
- `LAB_MODEL_CONFIG`
- `LAB_SKILL_PATHS`
- `LAB_API_PORT`
- `LAB_AUTO_INIT_DB`
- `LAB_JOB_DEFAULT_TIMEOUT_S`
- `LAB_JOB_DEFAULT_MAX_ATTEMPTS`
- `LAB_LLM_LOG_PROMPTS`

Artifacts are expected under `LAB_DATA_ROOT`.

## Practical Commands

These commands are expected to work in the current repo state:

```bash
# Full stack
docker compose up -d

# Host-mode infrastructure
docker compose up -d postgres

# Backend / worker
uv sync --extra dev
uv run synthetos db init
uv run uvicorn apps.api.main:app --reload
uv run python -m apps.worker

# Frontend
cd apps/web && npm install
cd apps/web && npm run dev

# Corpus / workflows
uv run synthetos corpus import-arxiv --path <jsonl>
uv run synthetos discovery run --charter-id <uuid> --query "..."
uv run synthetos analysis run --paper-id <uuid> --charter-id <uuid> --cycle-id <uuid>
uv run synthetos experiment hypothesize --cycle-id <uuid> --charter-id <uuid>
uv run synthetos experiment runs --cycle-id <uuid>
uv run synthetos experiment status --run-id <uuid>
uv run synthetos autonomy policy --cycle-id <uuid>
uv run synthetos patterns consolidate
uv run synthetos patterns decay --force
uv run synthetos pilot list
uv run synthetos pilot run ml_baseline_small
uv run synthetos pilot evaluate ml_baseline_small <cycle_uuid>

# Quality
uv run ruff check .
uv run pyright
uv run pytest
cd apps/web && npm run build
```

Some write paths are API/dashboard-only today, notably protocol compilation, run creation, pattern browsing/curation, and autonomy policy updates.

## Current Verification Baseline

Use the README's quality gates before shipping:

- `uv run ruff check .`
- `uv run pyright`
- `uv run pytest`
- `cd apps/web && npm run build`

Known caveats:

- `cd apps/web && npm run lint` may still be blocked by the ESLint v9 config mismatch noted in `project_docs/project_status.md`.
- Browser verification is still needed for older frontend routes after the Calm Console redesign.
- Real-environment validation should cover live Postgres migration/bootstrap, real-paper ingestion/fallback, configured LLM endpoints, AGE-vs-relational behavior, Docker/GPU execution, run control, artifact capture, remediation retries, and longer autonomous loops.
