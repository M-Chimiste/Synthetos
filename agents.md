# AGENTS.md

This file gives coding agents a concise operating brief for work in this repository.

## Project Snapshot

- Product: **Synthetos**
- Goal: a single-user ML research system for end-to-end research loops
- Current state: **implemented through Phase 2**
- Immediate focus: **stabilizing and extending the existing codebase**, with the next major product areas starting in Phase 3+

This is no longer a planning-only repository. The repo now contains working backend, worker, CLI, web, migrations, and unit-test coverage for the foundation, discovery, and analysis layers.

## Source of Truth

Read these before making structural decisions:

- `project_docs/co_scientist_prd.md` - product scope, MVP boundaries, user jobs, success criteria
- `project_docs/co_scientist_system_patterns.md` - architecture patterns, domain model, design rules
- `project_docs/co_scientist_tech_context.md` - implementation choices, stack, service layout, coding standards
- `project_docs/co_scientist_phased_implementation_plan.md` - roadmap and phase sequencing
- `project_docs/project_status.md` - best current summary of what is implemented versus what is still pending

`CLAUDE.md` is also a useful repo-local architecture summary, but `project_status.md` is the quickest way to understand current repo reality.

## What This System Is

Synthetos is intended to support four connected research loops:

1. Discover
2. Analyze
3. Experiment
4. Learn

It is meant to behave like a bounded, inspectable research control tower, not a black-box swarm of chat agents.

Two horizontal layers matter across those loops:

- the **Skill system** for optional task-specific tools and context
- the **Orchestrator API** for external control and telemetry via REST/SSE

## Current Repo Reality

Implemented today:

- **Phase 0** foundations: FastAPI API, worker, Typer CLI, React web shell, auth/scope checks, jobs, domain events, SSE, Alembic migrations, core cycle/state flows
- **Phase 1** discovery: arXiv metadata search, problem profiles, discovery sessions, metadata analysis, stable/discovery views, reports, evaluation hooks, resumable corpus import path
- **Phase 2** analysis: HTML-first full-text ingestion with PDF+Docling fallback, structure-aware chunking, typed paper graphs with optional AGE projection, coverage diagnostics, review artifacts, persisted analysis reports, graph-aware QA/locate, evidence extraction, contradiction/redundancy detection

Still not implemented:

- Phase 3+ experiment, remediation, autonomous loop, and cross-charter memory features
- full end-to-end integration coverage for the complete discovery -> analysis runtime path
- real-environment validation for live model endpoints, real-paper ingestion/fallback, and AGE-vs-relational behavior

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
- Paper-keyed analysis reads use the **latest completed** analysis session.

## Runtime Model

- Postgres runs in Docker via `docker compose`.
- API, worker, and web are expected to run on the host during development.
- Experiment workloads are still intended to run as sibling Docker containers with GPU passthrough, not Docker-in-Docker.
- Artifacts are written under `LAB_DATA_ROOT`, including discovery and analysis report bundles.

## Actual Monorepo Shape

Current top-level structure:

```text
apps/
libs/
skills/
configs/
tests/
project_docs/
docker/
```

Notable implemented app/library areas:

- `apps/api` - REST API routers for charters, cycles, state, jobs, events, skills, discovery, analysis
- `apps/worker` - job claimer/executor loop for discovery and analysis operators
- `apps/cli` - Typer commands including DB, corpus, discovery, and analysis flows
- `apps/web` - React/TanStack frontend
- `libs/discovery` - Phase 1 discovery pipeline
- `libs/analysis` - Phase 2 analysis pipeline
- `libs/adapters` - LLM, embeddings, ingestion, graph, and source adapters
- `libs/storage` - SQLAlchemy models and Alembic migrations
- `libs/schemas` - canonical Pydantic boundary types

## Primary Stack

- Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, psycopg, Typer
- Frontend: React, TypeScript, Vite, TanStack Query, TanStack Router, Tailwind CSS
- Database: PostgreSQL with pgvector and optional Apache AGE
- Embeddings: `gte-modernbert`, 768 dimensions
- Model gateway: local OpenAI-compatible endpoints plus hosted OpenAI, Anthropic, and Google
- Execution: Docker/Podman plus git worktrees for isolation
- Tooling: `uv`, `ruff`, `pyright`, `pytest`, `vitest`, `Playwright`

Structured outputs are a first-class requirement. Generated data should validate into typed schemas whenever possible.

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
- `SkillDefinition`
- `DomainEvent`, `Job`

## Implementation Guardrails

- Prefer typed models and explicit schemas at subsystem boundaries.
- Keep canonical schemas in `libs/schemas/`.
- Store prompts as versioned files, not inline strings.
- Keep config in YAML plus environment variables, not prompt text.
- Every schema change should go through Alembic migrations.
- Record lineage for model calls, reports, and verification artifacts.
- Preserve the operator -> job -> domain event pattern instead of adding hidden workflow shortcuts.
- Keep container execution sandboxed by default when Phase 3 work begins: network disabled, data read-only, limits enforced.
- Add modular behavior through `skill.md` packages instead of hardcoding everything into the core.
- Build vertical slices that preserve durable artifacts and readable reports, not disconnected helpers.

## Agent Working Rules

- Treat the documents in `project_docs/` as the source of truth over ad hoc assumptions.
- Do not assume the repo is still in planning mode; inspect the implemented code first.
- Preserve hexagonal boundaries; do not let domain code depend directly on vendor or transport layers.
- Optimize for inspectability, reproducibility, and durable state.
- Evidence before hypothesis before code: build flows that keep provenance visible.
- If you introduce a new subsystem, connect it back to one of the four core loops or a horizontal layer.
- Prefer extending existing discovery/analysis patterns over inventing a second workflow style.
- When changing paper analysis behavior, make sure API, worker, schemas, CLI, and web contracts stay aligned.
- When changing paper-keyed analysis reads, preserve the latest-completed-session semantics unless product docs explicitly change them.

## Expected Environment

Important environment variables called out in the repo guidance:

- `LAB_DB_URL`
- `LAB_DATA_ROOT`
- `LAB_MODEL_CONFIG`
- `LAB_SKILL_PATHS`
- `LAB_API_PORT`
- `LAB_AUTO_INIT_DB`

Artifacts are expected under `LAB_DATA_ROOT`.

## Practical Commands

These commands are expected to work in the current repo state:

```bash
# Infrastructure
docker compose up -d postgres

# Backend / worker
uv sync --extra dev --extra reranker
uv run synthetos db init
uv run uvicorn apps.api.main:app --reload
uv run python -m apps.worker

# Frontend
cd apps/web && npm install
cd apps/web && npm run dev

# Corpus / workflows
uv run synthetos corpus import-arxiv --path <jsonl>
uv run synthetos discovery start ...
uv run synthetos analysis run --paper-id <uuid> --charter-id <uuid> --cycle-id <uuid>

# Quality
uv run ruff check .
uv run pyright
uv run pytest
cd apps/web && npm run build
```

## Current Verification Baseline

At the time of the latest repo update:

- `uv run ruff check .` passes
- `UV_CACHE_DIR=/tmp/uv-cache uv run pyright` passes
- `uv run pytest` passes
- `cd apps/web && npm run build` passes

What still needs real-environment validation:

- live Postgres migration/bootstrap checks
- real-paper HTML ingestion and PDF fallback
- configured LLM endpoints for graph extraction/review/evidence/QA
- AGE projection versus relational fallback
- end-to-end integration coverage across discovery -> analysis
