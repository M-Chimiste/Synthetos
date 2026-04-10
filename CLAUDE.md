# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Synthetos** -- a single-user ML research system for running end-to-end research loops. Researchers define problems, triage literature (arXiv), generate hypotheses, execute experiments in GPU-capable containers, verify results, and prepare submissions.

**Current status:** Pre-implementation. The repository contains planning/design documents in `project_docs/`. Phase 0 (Foundation) is ready to begin.

## Design Documents

- `project_docs/co_scientist_prd.md` -- Product requirements, MVP scope, success metrics
- `project_docs/co_scientist_system_patterns.md` -- Architecture patterns, design principles, data model
- `project_docs/co_scientist_tech_context.md` -- Tech stack, repo structure, service breakdown, coding standards
- `project_docs/co_scientist_phased_implementation_plan.md` -- 7-phase roadmap (Phase 0-6)

## Architecture

Four core loops: **Discover** (intake -> retrieval -> metadata analysis -> shortlist) -> **Analyze** (full-text ingestion -> graph construction -> QA -> coverage) -> **Experiment** (hypotheses -> protocols -> containerized runs -> telemetry) -> **Learn** (remediation -> signal classification -> frontier tracking -> patterns).

Two horizontal layers: **Skill system** (optional add-on tools/context that augment prompts for specific tasks) and **Orchestrator API** (REST/SSE control plane for external tool integration).

### Critical Architectural Decisions

- **Operator-over-shared-state**, not agent messaging. Typed operators read/write a shared `ResearchState` -- no hidden prompt history as memory.
- **ResearchCharter** = the project definition. **ResearchCycle** = one bounded research loop within a charter. **ResearchState** = logical aggregate of everything that has occurred within a charter across its cycles (not a single DB row).
- **One active charter at a time** due to GPU constraints. Users can swap between charters but not run them concurrently.
- **Metadata-first literature triage**: title+abstract screening before full text. Shortlisted papers use an HTML-first full-text path, with PDF + [Marker](https://github.com/datalab-to/marker) as fallback when HTML is unavailable or low quality.
- **Task-scoped context assembly**: each operator gets a scoped `ContextPack` with token budget, allowed sources, deterministic ordering.
- **Portfolio search**: ranked hypothesis portfolio, not greedy single-path.
- **Hexagonal architecture**: all external systems behind adapter interfaces. Core domain code must not depend on vendor SDKs.
- **Evidence before hypothesis before code**: never jump from task description directly to generated code.
- **Deterministic core, probabilistic edge**: LLMs for synthesis/ideation/critique; Python+config for state, policy, lineage.
- **Prompts vs Skills**: Prompts control overall operator behavior (versioned file assets). Skills are optional add-ons providing tools or additional context for specific task types. Skills augment prompts, they don't replace them.
- **Policy precedence**: hard system policy and token scopes override user-configured policy, which overrides autonomy or operator defaults.

### Runtime Model

- **Infrastructure (Postgres):** Runs in Docker containers via docker-compose
- **Application (API, worker, web):** Runs on host with hot reload
- **Experiment containers:** Spawned as sibling Docker containers (not DinD) with GPU passthrough via Docker SDK. Host machine has 2x RTX 6000 Blackwell GPUs for training/inference.

### Planned Monorepo Structure

```
apps/           -- api/ worker/ web/ cli/
libs/           -- schemas/ core/ orchestration/ storage/ discovery/ analysis/
                   literature/ ideation/ protocols/ execution/ remediation/
                   verification/ reporting/ memory/ skills/
                   adapters/ (arxiv/ corpus/ external_search/ paper_ingestion/
                              graph/ llm/ embeddings/ git/ container/)
prompts/        -- versioned prompt assets (planning/ discovery/ analysis/ ideation/
                   coding/ remediation/ verification/ reporting/)
skills/         -- first-party skill.md packages by phase
configs/        -- YAML config (problems/ policies/ models/ skills/)
tests/          -- unit/ integration/ e2e/ fixtures/
```

## Tech Stack

**Backend:** Python 3.12, uv, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, psycopg, Typer (CLI), structlog, httpx, tenacity, jinja2, orjson

**Database:** PostgreSQL + pgvector (768-dim, gte-modernbert embeddings) + Apache AGE (graph storage), all in one instance

**Frontend:** React, TypeScript, Vite, TanStack Query, TanStack Router, Tailwind CSS

**Model Gateway:** Must support all from day one:
- Local: LMStudio, Ollama, VLLM-compatible endpoints (all OpenAI-compatible API)
- Hosted: OpenAI, Anthropic, Google
- Structured output support is critical -- most generated data validated via structured output

**Embeddings:** gte-modernbert, 768 dimensions. arXiv corpus is already embedded.

**Execution:** Docker containers with NVIDIA Container Toolkit + GPU passthrough. Git worktrees for workspace isolation.

**Quality:** ruff (lint/format), pyright (types), pytest + testcontainers (backend tests), vitest (frontend), Playwright (e2e)

## Internal Corpus

The "internal corpus" is a seeded local arXiv metadata mirror. The arXiv metadata corpus is already downloaded and embedded (gte-modernbert, 768-dim), then incrementally updated through harvesting. Full text is fetched only for shortlisted papers, using HTML first and PDF + [Marker](https://github.com/datalab-to/marker) as fallback.

## Development Commands (Planned)

```bash
# Infrastructure
docker compose up postgres

# Backend
uv sync                           # Install deps
alembic upgrade head              # Run migrations
uv run uvicorn apps.api:app       # Start API
uv run python -m apps.worker      # Start worker

# Frontend
npm install
npm run dev

# Quality
uv run pytest                     # Backend tests
uv run pytest tests/unit/test_foo.py -k test_name  # Single test
uv run ruff check .               # Lint
uv run ruff format .              # Format
uv run pyright                    # Type check
npm run test                      # Frontend tests (vitest)
npx playwright test               # E2e tests
```

## Core Domain Entities

`ResearchCharter`, `ResearchState` (logical aggregate), `ProblemProfile`, `DiscoverySession`, `PaperCard`, `PaperAnalysisPacket`, `EvidenceCard`, `HypothesisCard`, `ExperimentSpec`, `RunRecord`, `VerificationReport`, `FailurePostmortem`, `RemediationAction`, `MetricFrontier`, `DirectionalSignal`, `CanonicalPattern`, `ReportBundle`, `SkillDefinition`, `SkillBinding`, `DomainEvent`

## Environment

- Credentials in `.env` (gitignored for sensitive values)
- Key env vars: `LAB_DB_URL`, `LAB_DATA_ROOT`, `LAB_MODEL_CONFIG`, `LAB_SKILL_PATHS`, `LAB_API_PORT`, `LAB_AUTO_INIT_DB`
- Artifact storage under `LAB_DATA_ROOT` (artifacts/, cache/, workspaces/, exports/)
