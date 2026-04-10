# AGENTS.md

This file gives coding agents a concise operating brief for work in this repository.

## Project Snapshot

- Product: **Synthetos**
- Goal: a single-user ML research system for end-to-end research loops
- Current state: **pre-implementation**
- Immediate focus: **Phase 0 (Foundation)** from the phased implementation plan

The repository currently contains planning and architecture documents, not the production codebase yet.

## Source of Truth

Read these before making structural decisions:

- `project_docs/co_scientist_prd.md` - product scope, MVP boundaries, user jobs, success criteria
- `project_docs/co_scientist_system_patterns.md` - architecture patterns, domain model, design rules
- `project_docs/co_scientist_tech_context.md` - implementation choices, stack, service layout, coding standards
- `project_docs/co_scientist_phased_implementation_plan.md` - roadmap and phase sequencing

`CLAUDE.md` is also a useful repo-local summary of the current architecture and conventions.

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

## Locked Architectural Decisions

Treat these as defaults unless a repository document explicitly changes them:

- Use operator-over-shared-state, not agent-to-agent hidden memory.
- `ResearchCharter` is the project definition; `ResearchCycle` is one bounded research loop within a charter; `ResearchState` is the logical aggregate of everything that has occurred within a charter.
- Keep orchestration explicit with state transitions and append-only domain events.
- Assume only one active charter at a time because GPU-heavy work is not meant to run concurrently.
- Prefer metadata-first literature triage before full-text ingestion.
- Use an HTML-first full-text path for shortlisted papers, with PDF plus Docling as fallback when HTML is unavailable or low quality.
- Build task-scoped context packs instead of passing entire project state into every step.
- Keep the core deterministic and typed; use LLMs at the probabilistic edge.
- Put every external dependency behind adapters.
- Treat mechanical failures separately from scientific findings.
- Prompts define operator behavior; skills are optional augmentations, not replacements for prompts.
- Policy precedence is: hard system policy and token scopes, then user or charter settings, then autonomy or operator defaults.

## Runtime Model

- Postgres runs in Docker via `docker compose`.
- API, worker, and web are expected to run on the host during development.
- Experiment workloads run as sibling Docker containers with GPU passthrough, not Docker-in-Docker.

## Planned Monorepo Shape

Target structure from the design docs:

```text
apps/
libs/
prompts/
skills/
configs/
tests/
```

Do not invent a conflicting structure without checking the docs first.

## Primary Stack

- Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, psycopg, Typer
- Frontend: React, TypeScript, Vite, TanStack Query, TanStack Router, Tailwind CSS
- Database: PostgreSQL with pgvector and Apache AGE
- Embeddings: `gte-modernbert`, 768 dimensions
- Model gateway must support local OpenAI-compatible endpoints plus hosted OpenAI, Anthropic, and Google routes
- Execution: Docker or Podman, with git worktrees for workspace isolation
- Tooling: `uv`, `ruff`, `pyright`, `pytest`, `vitest`, `Playwright`

Structured outputs are a first-class requirement. Generated data should validate into typed schemas whenever possible.

## Internal Corpus

- The internal corpus is a seeded local arXiv metadata mirror.
- The arXiv metadata corpus is already downloaded and embedded, then incrementally updated through harvesting.
- Discovery should stay metadata-first: review title and abstract together before escalating.
- Shortlisted papers can move to HTML-first full-text extraction, with PDF as fallback.

## Implementation Guardrails

- Prefer typed models and explicit schemas at subsystem boundaries.
- Keep canonical schemas in `libs/schemas/` once implementation begins.
- Store prompts as versioned files, not inline strings.
- Keep config in YAML plus environment variables, not prompt text.
- Every schema change should go through migrations.
- Record lineage for model calls, experiments, and verification artifacts.
- Keep container execution sandboxed by default: network disabled, data read-only, limits enforced.
- Add modular behavior through `skill.md` packages instead of hardcoding everything into the core.
- Build vertical slices that preserve durable artifacts and readable reports, not disconnected helpers.

## Agent Working Rules

- Treat the documents in `project_docs/` as the source of truth over ad hoc assumptions.
- Since the repo is still pre-implementation, prefer creating thin foundations over speculative full systems.
- Preserve hexagonal boundaries early; do not let domain code depend directly on vendors or transport layers.
- Optimize for inspectability, reproducibility, and durable state.
- Evidence before hypothesis before code: build flows that keep provenance visible.
- If you introduce a new subsystem, connect it back to one of the four core loops or a horizontal layer.
- If you add entities early, prefer the names already called out in the planning docs, such as `ProblemProfile`, `DiscoveryView`, `PaperReviewArtifact`, `SkillExecutionRecord`, and `ApprovalEvent`.

## Expected Environment

Important environment variables called out in the repo guidance:

- `LAB_DB_URL`
- `LAB_DATA_ROOT`
- `LAB_MODEL_CONFIG`
- `LAB_SKILL_PATHS`
- `LAB_API_PORT`
- `LAB_AUTO_INIT_DB`

Artifacts are expected under `LAB_DATA_ROOT`.

## Planned Commands

These are design-target commands and may not work yet until implementation lands:

```bash
# Infrastructure
docker compose up postgres

# Backend
uv sync
alembic upgrade head
uv run uvicorn apps.api:app
uv run python -m apps.worker

# Frontend
npm install
npm run dev

# Quality
uv run pytest
uv run ruff check .
uv run ruff format .
uv run pyright
npm run test
npx playwright test
```

## Current Repo Reality

At the moment, this repository is primarily a planning workspace. When adding code, align it to the documented target architecture instead of optimizing for a temporary shortcut that will need to be undone during Phase 0 or Phase 1.
