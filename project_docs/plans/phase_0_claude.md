# Phase 0 Implementation Plan -- Foundation, Shared State, Skill Skeleton, and API Spine

## Context

Synthetos is an ML research system currently in pre-implementation. The repo contains only planning docs, CLAUDE.md, agents.md, .env, and .gitignore. Phase 0 creates the product backbone: repo structure, local services, durable state, state transitions, operator contract, model gateway, event stream, skill discovery, initial dashboard shell, and orchestrator API skeleton.

## Resolved Design Decisions

- **Package structure**: Single `pyproject.toml` at repo root; `apps/` and `libs/` as namespace packages
- **ID strategy**: UUIDv7 (time-sortable, native Postgres UUID type) via `uuid-utils`
- **Apache AGE**: Include in Docker image and `CREATE EXTENSION`, but no graph features until Phase 2
- **SSE streaming**: Polling-based (500ms) for Phase 0; upgrade to LISTEN/NOTIFY later if needed
- **ResearchState**: Not an ORM model -- assembled by a service function from related tables into a `ResearchStateSnapshot` Pydantic model
- **Domain events**: `jsonb` payload column with `event_type` discriminator string; per-event Pydantic payload models
- **Job queue**: `SELECT ... FOR UPDATE SKIP LOCKED` row-claim semantics on a `jobs` table
- **Structured output**: `complete_structured()` method on LLM adapters with provider-specific implementations (JSON schema for OpenAI-compat, tool-use for Anthropic, response_schema for Google)

---

## Build Sequence (10 Steps)

### Step 1: Repository Skeleton and Tooling Bootstrap

Create the monorepo structure, Python project config, and frontend scaffold.

**Files:**
```
pyproject.toml                    # Python 3.12, all backend deps, ruff/pyright config
alembic.ini
docker-compose.yml                # Postgres with pgvector + AGE
apps/__init__.py
apps/api/__init__.py
apps/worker/__init__.py
apps/cli/__init__.py
apps/web/package.json             # React + Vite + TS + TanStack + Tailwind
apps/web/vite.config.ts
apps/web/tsconfig.json
apps/web/tailwind.config.ts
apps/web/postcss.config.js
apps/web/index.html
apps/web/src/main.tsx
apps/web/src/App.tsx
libs/__init__.py
libs/schemas/__init__.py
libs/core/__init__.py
libs/storage/__init__.py
libs/adapters/__init__.py
libs/adapters/llm/__init__.py
libs/adapters/embeddings/__init__.py
libs/skills/__init__.py
libs/orchestration/__init__.py
prompts/.gitkeep
skills/.gitkeep
configs/models.yaml               # Model routing config template
configs/policies/.gitkeep
tests/__init__.py
tests/unit/__init__.py
tests/integration/__init__.py
tests/e2e/__init__.py
tests/fixtures/__init__.py
tests/conftest.py
```

**Key details:**
- `pyproject.toml` declares: fastapi, pydantic, pydantic-settings, sqlalchemy[asyncio], alembic, psycopg[binary], typer, structlog, httpx, tenacity, jinja2, orjson, uvicorn, uuid-utils, anthropic, openai, google-genai. Dev: ruff, pyright, pytest, pytest-asyncio.
- `docker-compose.yml` uses a Postgres image with pgvector; AGE installed via init script. Init SQL runs `CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS age;`
- Frontend: React 19, Vite, TanStack Query + Router, Tailwind CSS v4

---

### Step 2: Configuration, Logging, and Core Types

Establish settings loading and structured logging used by all subsequent modules.

**Files:**
```
libs/core/config.py               # Pydantic Settings (LAB_DB_URL, LAB_DATA_ROOT, etc.)
libs/core/logging.py              # structlog JSON config
libs/core/types.py                # NewType IDs (CharterId, CycleId, JobId, EventId), CycleStatus enum
libs/core/clock.py                # Abstracted time source for testability
```

**`CycleStatus` enum values:** `created`, `discovery_ready`, `discovery_screened`, `analysis_ready`, `evidence_ready`, `portfolio_ready`, `protocol_ready`, `running`, `verifying`, `reporting`, `closed`

---

### Step 3: Database Foundation and Core Schema

Stand up Postgres, migration framework, and canonical tables.

**Files:**
```
libs/storage/base.py              # DeclarativeBase, engine/session factories
libs/storage/migrations/env.py    # Alembic env
libs/storage/migrations/versions/ # Initial migration
libs/storage/models/__init__.py   # Model registry
libs/storage/models/research.py   # ResearchCharter, ResearchCycle
libs/storage/models/jobs.py       # Job (queue)
libs/storage/models/events.py     # DomainEvent
libs/storage/models/skills.py     # SkillDefinition, SkillBinding
libs/storage/models/orchestrator.py  # OrchestratorClient, ApiToken
libs/storage/models/lineage.py    # ModelCallRecord
```

**Key tables:**
| Table | Key columns |
|-------|------------|
| `research_charters` | id (uuid7 pk), title, description, problem_statement, source_scope (jsonb), status, created_at, updated_at |
| `research_cycles` | id (uuid7 pk), charter_id (fk), status (CycleStatus enum), config (jsonb), created_at, updated_at, started_at, completed_at |
| `jobs` | id (uuid7 pk), cycle_id (fk), job_type, status (pending/claimed/running/completed/failed/cancelled), payload (jsonb), result (jsonb), claimed_by, claimed_at, heartbeat_at, priority, created_at, completed_at |
| `domain_events` | id (uuid7 pk), charter_id (fk nullable), cycle_id (fk nullable), event_type, payload (jsonb), actor_type, actor_id, created_at |
| `skill_definitions` | id (uuid7 pk), skill_id (varchar unique), version, phase, trust_tier, manifest (jsonb), content_hash, enabled, discovered_at, source_path |
| `orchestrator_clients` | id (uuid7 pk), name, description, enabled, created_at |
| `api_tokens` | id (uuid7 pk), client_id (fk), token_hash, scopes (text[]), created_at, expires_at, revoked |
| `model_call_records` | id (uuid7 pk), cycle_id (fk nullable), job_id (fk nullable), provider, model_id, prompt_template_id, role, input_tokens, output_tokens, cost_estimate, created_at |

---

### Step 4: Domain Layer -- State Machine, Events, and Operator Contract

Define the core domain logic everything else builds on.

**Files:**
```
libs/schemas/charter.py           # ResearchCharter Pydantic schemas (Create, Read, Update)
libs/schemas/cycle.py             # ResearchCycle schemas
libs/schemas/state.py             # ResearchStateSnapshot
libs/schemas/events.py            # DomainEvent schemas, per-event payload models
libs/schemas/jobs.py              # Job schemas
libs/schemas/common.py            # Pagination, error responses
libs/core/state_machine.py        # CycleStateMachine with ALLOWED_TRANSITIONS dict
libs/core/events.py               # EventEmitter service (insert + notify SSE subscribers)
libs/core/operators.py            # OperatorInput/OperatorOutput protocols
libs/core/research_state.py       # assemble_research_state() function
```

---

### Step 5: API Service Foundation (parallel with Steps 6, 7)

FastAPI app with core CRUD endpoints and SSE streaming.

**Files:**
```
apps/api/main.py                  # App factory, middleware, lifespan
apps/api/deps.py                  # DI: get_db, get_settings, get_current_client
apps/api/auth.py                  # Token validation, scope checking (dev bypass option)
apps/api/routers/__init__.py
apps/api/routers/health.py        # GET /health, GET /ready
apps/api/routers/charters.py      # /api/v1/charters CRUD
apps/api/routers/cycles.py        # /api/v1/cycles CRUD + resume
apps/api/routers/state.py         # /api/v1/state/{charter_id} snapshot
apps/api/routers/events.py        # /api/v1/events/stream SSE (polling-based)
apps/api/routers/jobs.py          # /api/v1/jobs list/detail (read-only)
libs/core/services/charter_service.py
libs/core/services/cycle_service.py
```

**SSE:** `StreamingResponse` with `text/event-stream`, accepts `last_event_id` query param, polls domain_events every 500ms.

**Auth:** Token-based from `api_tokens` table with scope checks. Configurable dev bypass.

---

### Step 6: Worker Runtime and Job Queue (parallel with Steps 5, 7)

Worker process that claims and executes jobs.

**Files:**
```
apps/worker/main.py               # Entry point, main claim loop
apps/worker/claimer.py            # SELECT FOR UPDATE SKIP LOCKED claim logic
apps/worker/executor.py           # Dispatch job_type -> operator
apps/worker/heartbeat.py          # Periodic heartbeat updater
libs/core/services/job_service.py # Create/claim/complete/fail jobs
```

**Claim SQL:** `UPDATE jobs SET status='claimed', claimed_by=$wid WHERE id = (SELECT id FROM jobs WHERE status='pending' ORDER BY priority DESC, created_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *`

---

### Step 7: Model Gateway (parallel with Steps 5, 6)

LLM and embedding adapters supporting hosted + local models through one interface.

**Files:**
```
libs/adapters/llm/base.py         # LLMAdapter protocol: complete(), complete_structured()
libs/adapters/llm/openai_compat.py # LMStudio, Ollama, VLLM (OpenAI-compatible API)
libs/adapters/llm/anthropic_adapter.py  # Anthropic native SDK
libs/adapters/llm/openai_adapter.py     # OpenAI hosted
libs/adapters/llm/google_adapter.py     # Google Gemini
libs/adapters/llm/router.py       # Role-based router (reads configs/models.yaml)
libs/adapters/llm/structured.py   # Pydantic model -> provider-specific structured output
libs/adapters/embeddings/base.py  # EmbeddingAdapter protocol: embed(), embed_batch()
libs/adapters/embeddings/openai_compat.py
libs/schemas/model_gateway.py     # CompletionRequest/Response, ModelRole enum
configs/models.yaml               # Role -> provider/model mapping
```

**`complete_structured()`** accepts a Pydantic model class as `response_model`, returns a validated instance. Provider-specific: JSON schema mode for OpenAI-compat, tool-use for Anthropic, response_schema for Google.

---

### Step 8: Skill Foundation

Skill discovery, validation, persistence, and catalog API.

**Files:**
```
libs/skills/loader.py             # Walk LAB_SKILL_PATHS, find skill.md files
libs/skills/parser.py             # Parse YAML frontmatter + markdown body
libs/skills/validator.py          # Validate against SkillManifest Pydantic model
libs/skills/registry.py           # Upsert SkillDefinitions, query catalog
libs/schemas/skills.py            # SkillManifest, SkillDefinition schemas
apps/api/routers/skills.py        # /api/v1/skills catalog endpoint
skills/example/skill.md           # First-party example skill with YAML frontmatter
```

**Trust tiers:** `first_party_trusted` (repo `skills/`), `user_local_trusted` (user paths), `third_party_untrusted` (everything else).

---

### Step 9: Telemetry and SSE Wiring

Connect worker event emission to API SSE delivery to UI consumption.

**Files:**
```
libs/core/pubsub.py               # In-process event fan-out for API
apps/api/routers/events.py        # Enhance with filtered streams, resume support
libs/core/services/telemetry_service.py  # Query recent events, format for SSE
```

**Job control:** `POST /api/v1/jobs/{id}/cancel`, `/pause`, `/resume` endpoints update job status. Worker checks on heartbeat.

---

### Step 10: Minimal UI Shell and CLI

Dashboard and CLI that satisfy exit criteria.

**Frontend files (`apps/web/src/`):**
```
router.tsx                        # TanStack Router setup
api/client.ts                     # Typed fetch wrapper
api/hooks.ts                      # TanStack Query hooks
pages/Dashboard.tsx               # Active charter, cycle status, recent events
pages/CharterCreate.tsx           # Charter creation form
pages/CharterDetail.tsx           # Charter detail + cycles list
pages/CycleDetail.tsx             # Cycle detail + state + events + jobs
pages/Events.tsx                  # Event browser with live SSE
pages/Skills.tsx                  # Skill catalog browser
components/EventStream.tsx        # SSE-connected live event feed
components/StatusBadge.tsx        # Status display component
components/Layout.tsx             # App shell
```

**CLI files:**
```
apps/cli/main.py                  # Typer app
apps/cli/commands/charter.py      # charter create/list/show
apps/cli/commands/cycle.py        # cycle create/list/show
apps/cli/commands/skill.py        # skill list/validate/discover
apps/cli/commands/db.py           # db init/migrate (wraps alembic)
```

---

## Dependency Graph

```
Step 1 -> Step 2 -> Step 3 -> Step 4 -+-> Step 5 (API)     -+-> Step 9 -> Step 10
                                       +-> Step 6 (Worker)  -+
                                       +-> Step 7 (Gateway)  +-> Step 8 (Skills)
```

Steps 5, 6, 7 are the three major parallel workstreams after Step 4.

---

## Exit Criteria Verification

| Criterion | Covered by |
|-----------|-----------|
| User creates charter + cycle from UI or CLI | Steps 5, 10 |
| Cycle persisted and visible in dashboard | Steps 3, 5, 10 |
| Worker claims job, emits events, updates state | Steps 4, 6 |
| UI streams state changes without refresh | Steps 9, 10 |
| One hosted + one local model through same gateway | Step 7 |
| System discovers first-party skill via UI/API | Steps 8, 10 |
| External client creates cycle + subscribes to events via API | Steps 5, 9 |

---

## Risks

- **Apache AGE Docker image**: AGE is less mature than pgvector. Mitigate by installing but not depending on it for Phase 0 features.
- **Structured output across providers**: Each LLM provider handles it differently. Mitigate by building provider-specific `complete_structured()` from the start with retry-with-correction for malformed JSON.
- **UI scope creep**: Strictly limit to: create charter, create cycle, dashboard, event browser, skill catalog. No report rendering, no discovery views in Phase 0.

---

## Testing Strategy for Phase 0

- **Unit tests**: State machine transitions, event emission, skill parsing/validation, job claim logic, model gateway routing
- **Integration tests**: Charter/cycle CRUD via API, worker job claim-execute-complete cycle, SSE event delivery, skill discovery from filesystem
- **Fixture**: Sample skill.md package, test charter/cycle data, mock LLM responses
