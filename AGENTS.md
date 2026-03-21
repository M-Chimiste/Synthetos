# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

**ML Laboratory Co-Scientist** — a local-first, single-user system for running end-to-end ML research loops. The system helps researchers define problems, triage literature, generate experiment ideas, execute code locally, verify results, and prepare submissions (Kaggle focus for MVP).

**Current status:** Phase 0 (Foundation) is in progress. The repository contains planning documents in `project_docs/` and initial scaffolding.

## Key Design Documents

- `project_docs/co-scientist_prd.md` — Product requirements, MVP scope, success metrics
- `project_docs/co-scientist_system_patterns.md` — Architecture baseline, system patterns, design principles
- `project_docs/co-scientist_tech_context.md` — Concrete tech stack, repo shape, service breakdown, coding standards
- `project_docs/co-scientist_phased_implementation_plan.md` — 6-phase delivery roadmap (Phase 0-5)
- `project_docs/kaggle-arxiv-example.txt` — Reference for arXiv metadata via Kaggle dataset
- `project_docs/m-chimiste-arxiv-harvester-example.txt` — Reference for arXiv metadata harvesting

## Architecture (Three Core Loops)

1. **Explore** — Problem intake → metadata-first literature screening → evidence synthesis → ranked hypothesis portfolio
2. **Experiment** — Hypothesis → ExperimentSpec → code generation → containerized local execution
3. **Verify** — Result verification → historical comparison → failure memory → human-readable report

### Critical Architectural Decisions

- **Operator-over-shared-state**, not agent-to-agent messaging. Typed operators read/write a shared `ResearchState` — no hidden prompt history as memory.
- **State machine orchestration** with explicit transitions and append-only audit trail (not freeform conversational workflow).
- **Metadata-first literature triage**: title+abstract screening before full text. For arXiv, prefer HTML over PDF.
- **Task-scoped context assembly**: operators receive only relevant evidence/data, not entire project state. Each operator gets a scoped `ContextPack` with a token budget, allowed sources, and deterministic ordering.
- **Portfolio search**: maintain ranked hypothesis portfolio, not greedy single-path.
- **Hexagonal architecture**: all external systems (arXiv, models, datasets, git, containers) behind adapter interfaces.
- **Containerized execution**: generated code runs in GPU-capable Docker containers with resource limits, not on the host.
- **Evidence before hypothesis, hypothesis before code**: never jump directly from task description to generated code.

### Planned Monorepo Structure

```
apps/           — api/ worker/ web/ cli/
libs/           — schemas/ core/ orchestration/ storage/ retrieval/ literature/
                  ideation/ protocols/ execution/ verification/ reporting/
                  adapters/ (arxiv/ corpus/ llm/ embeddings/ git/ container/ benchmark/)
prompts/        — versioned prompt assets by phase (planning/ literature/ ideation/ coding/ verification/ reporting/)
configs/        — problems/ policies/ models/ execution/ prompts/
tests/          — unit/ integration/ fixtures/
scripts/
```

Key structure rules: canonical schemas in one place (`libs/schemas/`), core domain code must not depend on vendor SDKs, adapters depend on core interfaces (not reverse), prompts are versioned file assets not strings in code, config is in files not prompt text.

## Tech Stack (MVP)

### Backend
- **Python 3.12** with **uv** for package/env management
- **FastAPI** + **Pydantic v2** for API and schemas
- **SQLAlchemy 2** + **Alembic** for ORM and migrations
- **PostgreSQL** + **pgvector** for state, vector search, and DB-backed job queue
- **Typer** for CLI
- **structlog** for structured logging
- Key libs: `httpx`, `tenacity`, `jinja2`, `orjson`, `psycopg`

### Frontend
- **React** + **TypeScript** + **Vite**
- **TanStack Query** for data layer
- **Tailwind CSS** for styling
- Keep it thin — control-tower visibility, not an analytics suite

### Execution
- **Docker Engine** + **NVIDIA Container Toolkit** for GPU-capable sandboxed experiment runs
- **Git worktrees** for per-run workspace isolation
- Local filesystem artifact store under `MLLAB_HOME`

### Tooling
- **ruff** — linting and formatting
- **pytest** — tests (with **testcontainers** for integration tests needing Postgres/Docker)
- **pyright** — static type checking
- **vitest** — frontend tests
- **Playwright** — minimal e2e UI tests

## Development Commands (Planned)

Local dev runs infrastructure in containers, application code on host with hot reload:

```bash
# Infrastructure
docker compose up postgres        # Start Postgres (with pgvector)

# Backend
uv sync                           # Install backend deps
alembic upgrade head              # Run migrations
uv run uvicorn apps.api:app       # Start API
uv run python -m apps.worker      # Start worker

# Frontend
npm install                       # Install frontend deps
npm run dev                       # Start web UI

# Testing
uv run pytest                     # Run backend tests
uv run ruff check .               # Lint
uv run pyright                    # Type check
```

## Key Conventions

- **Typed Python throughout**: Pydantic models at boundaries, SQLAlchemy models separate from domain schemas, no untyped dicts across subsystem boundaries.
- **Operator contract**: typed input state, config, context pack, model route, output schema, emitted events, artifact references, operator report.
- **Every schema change through migrations** (Alembic). Every entity gets created/updated timestamps. Domain events are append-only.
- **Model routing is config-driven** (YAML in `configs/models/`), supporting role-based routing (planner, triage, synthesizer, critic, coder, verifier, reporter) across hosted and local model backends.
- **Prompts are versioned assets** under `prompts/`, not strings in Python files. Every model call records prompt ID, version/checksum, and model route.
- **Container defaults**: network disabled, datasets read-only, resource limits enforced, no secrets injected unless explicitly required.
- **Reports**: markdown source + rendered HTML in UI. Required types: literature screening, evidence summary, hypothesis review, run summary, verification report, failure postmortem, cycle summary.

## Core Data Model Entities

`ResearchCharter`, `ResearchState`, `PaperCard`, `EvidenceCard`, `HypothesisCard`, `ExperimentSpec`, `RunRecord`, `VerificationReport`, `FailurePostmortem`, `ReportBundle`, `SkillDefinition`, `SkillBinding`, `SkillExecutionRecord`, `ApprovalEvent`, `DomainEvent`

## Environment

- Credentials in `.env` (gitignored) — includes API keys for model providers, Kaggle
- Sensitive files gitignored: `config/creds.json`, `client_secret.json`, `.env*`
- Large directories gitignored: `models/`, `data/`, `database/`, `temp_data/`
- Artifact storage under `MLLAB_HOME` env var (outside git repo)

## Notes
- Claude will be reviewing all of your work.
- After each coding session please update project_status.md with the current project status (what was done, what needs to be done next).
