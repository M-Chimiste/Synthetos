# Synthetos

**ML Laboratory Co-Scientist** — a local-first, single-user system for running end-to-end ML research loops. Define problems, triage literature, generate experiment ideas, execute code in sandboxed containers, verify results, and prepare submissions.

## Architecture

Three core loops drive the research process:

1. **Explore** — Problem intake, metadata-first literature screening, evidence synthesis, ranked hypothesis portfolio
2. **Experiment** — Hypothesis to ExperimentSpec, code generation, containerized local execution with GPU support
3. **Verify** — Result verification, historical comparison, failure memory, human-readable reports

The system uses **operator-over-shared-state** orchestration: typed operators read/write a shared `ResearchState` through an explicit state machine with append-only audit trail. All external systems (arXiv, models, Docker, git) sit behind adapter interfaces (hexagonal architecture).

## Project Structure

```
apps/
  api/          FastAPI REST API
  worker/       Background job worker
  web/          React + TypeScript control-tower UI
  cli/          Typer CLI
libs/
  schemas/      Canonical Pydantic schemas
  core/         State machine, config, ID generation
  orchestration/ Job queue, worker, operator registry
  storage/      SQLAlchemy models, Alembic migrations, services
  literature/   Literature intake and screening
  ideation/     Evidence extraction, hypothesis generation
  execution/    Docker execution, artifact collection, failure classification
  verification/ Result verification, postmortems
  reporting/    Report quality scoring, templates
  retrieval/    Source retrieval adapters
  adapters/     External system adapters (arXiv, LLM, embeddings, containers)
  skills/       Skill manifest, loader, dependency validation
  sdk/          Python client SDK (sync + async)
prompts/        Versioned Jinja2 prompt templates by phase
configs/        Policy, model routing, execution profiles
skills/         First-party skill definitions (15 skills)
tests/          Unit, integration, and fixture files
scripts/        Catalog generation and utilities
docs/           SDK quickstart, skill authoring guide
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12 |
| Package manager | uv |
| API | FastAPI + Pydantic v2 |
| Database | PostgreSQL + pgvector |
| ORM | SQLAlchemy 2 + Alembic |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, TanStack Query |
| Execution | Docker Engine + NVIDIA Container Toolkit |
| Workspace isolation | Git worktrees |
| Linting | ruff |
| Testing | pytest (backend), vitest + Testing Library (frontend) |

## Getting Started

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker (with Docker Compose)
- Node.js + pnpm
- PostgreSQL 16 with pgvector (or use the provided Docker Compose)

### Setup

```bash
# Clone and enter the repo
git clone <repo-url> && cd Synthetos

# Copy environment config
cp .env.example .env

# Start Postgres
docker compose up -d postgres

# Install backend dependencies and run migrations
uv sync
alembic upgrade head

# Install frontend dependencies
pnpm install

# Start the API server
uv run uvicorn apps.api:app --host 127.0.0.1 --port 8000

# Start the background worker (separate terminal)
uv run python -m apps.worker

# Start the web UI (separate terminal)
pnpm --dir apps/web dev
```

### Environment Variables

See [.env.example](.env.example) for all configuration options. Key variables:

| Variable | Description |
|----------|-------------|
| `LAB_DB_URL` | PostgreSQL connection string |
| `LAB_DATA_ROOT` | Local artifact storage directory |
| `LAB_MODEL_CONFIG` | Path to model routing config |
| `LAB_POLICY_CONFIG` | Path to policy config |
| `LAB_SKILL_PATHS` | Comma-separated skill directories |
| `LAB_AUTO_INIT_DB` | Auto-initialize DB on startup |

## Development

### Running Tests

```bash
# Backend tests
uv run pytest

# Backend tests with coverage
uv run pytest --cov

# Frontend tests
pnpm --dir apps/web test

# Lint
uv run ruff check .
```

### Key Conventions

- **Typed Python throughout** — Pydantic models at boundaries, no untyped dicts across subsystems
- **Operator contract** — Typed input state, config, context pack, model route, output schema, emitted events
- **Schema changes through migrations** — Every entity has created/updated timestamps, events are append-only
- **Prompts are versioned assets** in `prompts/`, not strings in Python files
- **Container defaults** — Network disabled, datasets read-only, resource limits enforced
- **Model routing is config-driven** via YAML, supporting role-based routing across model backends

### SDK

A Python client SDK is available for programmatic access:

```python
from libs.sdk import SynthetoClient

with SynthetoClient(base_url="http://localhost:8000") as client:
    result = client.create_cycle({
        "title": "Tabular Classification Baseline",
        "problem_statement": "Establish a baseline on the Iris dataset.",
        "success_criteria": {"target_metric": "accuracy > 0.95"},
    })
    print(result["cycle"]["public_id"])
```

See [docs/sdk/quickstart.md](docs/sdk/quickstart.md) for full documentation.

### Skills

The system includes 15 first-party skills across literature, ideation, coding, and verification phases. Custom skills can be added under `skills/` — see [docs/skills/authoring-guide.md](docs/skills/authoring-guide.md).

## Phase Status

| Phase | Status |
|-------|--------|
| Phase 0 — Foundation | Complete |
| Phase 1 — Literature Intake | Complete |
| Phase 2 — Evidence & Hypotheses | Complete |
| Phase 3 — Execution Lab MVP | Complete |
| Phase 4 — Verification | Complete |
| Phase 5.1 — Hardening | Complete |
| Phase 5.2 — Pilot Exercises | Not started |

## License

Private. All rights reserved.
