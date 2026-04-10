# Phase 1 — Discovery Pipeline MVP

## Context

Phase 0 stood up the Synthetos backbone: monorepo, Postgres + pgvector, charter/cycle/job/event ORM, FastAPI with token auth and SSE event stream, an operator-dispatching worker, a role-based LLM gateway (Anthropic/OpenAI/Google/local), a `skill.md` loader with trust tiers, and a React dashboard. The state machine knows about the discovery states but nothing actually moves a cycle through them yet.

Phase 1 turns that scaffolding into a real research-discovery loop: a researcher (or orchestrator) defines a problem on a charter, the system retrieves candidates from the local ~56 GB / ~3 M-record pre-embedded arXiv corpus *and* the live arXiv API, ranks them with hybrid BM25 + dense retrieval, optionally reranks with a local cross-encoder, runs metadata-depth LLM analysis over title + abstract, exposes Stable and Discovery views, and emits a discovery report consumable from the UI and the orchestrator API. This is the first vertical slice that produces an artifact a human (or another agent) can act on.

Key user-confirmed decisions:

- **Corpus** lives at [artifacts/arxiv-embedded.jsonl](artifacts/arxiv-embedded.jsonl) — JSONL, **~56 GB, 2,995,533 records**, every record already carries a 768-dim `Alibaba-NLP/gte-modernbert-base` embedding plus title, abstract, authors, categories, search_text, content_hash, and `_synthetos_format: synthetos.arxiv.embedded.v1`. Phase 1 owns importing it once into a new table; **no re-embedding required** for the cold corpus. Raw embedded payload is roughly 18 KB/record (mostly the 768 floats serialized as JSON), so a binary `COPY` into pgvector is a meaningful win over JSON inserts.
- **External source for v1**: arXiv live Atom API only. Other sources (Semantic Scholar, OpenAlex) are deferred.
- **Reranker**: local cross-encoder, GPU-friendly, with graceful fallback when missing/slow/over-budget.
- **First-stage rank**: hybrid Postgres `tsvector` BM25 + pgvector cosine, fused with reciprocal rank fusion (RRF).

---

## Scope

In scope (mapped to plan §6.2 A–G):

- A. Wire research charter intake into a discovery workflow (source-scope + view selection + free-form notes / orchestrator hints).
- B. Internal corpus adapter (over the imported arXiv table) + arXiv live API adapter + cross-source dedupe.
- C. Metadata-depth LLM analysis operator over title + abstract.
- D. First-stage hybrid ranking, Stable + Discovery views, optional rerank with fallback, MMR diversity for Discovery.
- E. `DiscoverySession` artifacts (ranked set, shortlist, step log, stats), exposed in UI and API.
- F. Optional Recall@K / Precision@K / MRR evaluation hooks when ground truth is supplied.
- G. First-party literature skills (problem scoping, title/abstract triage, shortlist critique, escalation rationale).

Out of scope (Phase 2+): full-text fetch, structure-aware chunking, paper graph, evidence cards, hypotheses, execution.

---

## Architectural shape

```
charter ─┐
         ▼
    discovery_intake (operator)
         │  → ProblemProfile + DiscoverySession (created)
         ▼
    discovery_search (operator)
         │  → fan-out to source adapters
         │       ├── internal_corpus (BM25 + pgvector → RRF)
         │       └── arxiv_live      (Atom API → metadata only)
         │  → dedupe → PaperCard rows w/ first_stage_score
         ▼
    discovery_rerank (operator)        [skipped/fallback if budget/unavailable]
         │  → cross-encoder over top-N → rerank_score
         ▼
    discovery_analyze (operator)
         │  → LLM metadata-depth analysis (title+abstract+authors+venue)
         │  → MetadataAnalysisPacket per shortlist candidate
         ▼
    discovery_finalize (operator)
         │  → Stable view + Discovery view (MMR diversified)
         │  → DiscoveryReport bundle
         │  → cycle: discovery_ready → discovery_screened
```

Each box is a registered operator following the Phase 0 [OperatorInput → OperatorResult pattern](apps/worker/executor.py). The chain runs as separate jobs to keep restarts/pause/cancel cheap; the worker advances cycle status via `state_patch["cycle_status"]` exactly as in [_apply_state_patch](apps/worker/main.py#L91).

---

## Work breakdown

### 1. Schemas & migrations

New SQLAlchemy models under [libs/storage/models/](libs/storage/models/), Pydantic DTOs under [libs/schemas/](libs/schemas/), one Alembic migration `20260411_000001_phase1_discovery.py` revising `20260410_000001`.

Tables:

| Table | Purpose | Key columns |
|---|---|---|
| `arxiv_corpus` | Imported pre-embedded arXiv records (system-wide, not charter-scoped) | `arxiv_id PK`, `title`, `abstract`, `authors JSONB`, `categories JSONB`, `created_date`, `updated_date`, `doi`, `source_url`, `pdf_url`, `search_text`, `content_hash`, `embedding VECTOR(768)`, `embedding_model_id`, `tsv tsvector` (generated, GIN-indexed), HNSW index on `embedding` |
| `problem_profiles` | Per-cycle scoped problem statement + retrieval config | `cycle_id FK`, `query_text`, `notes`, `source_scope JSONB`, `view_preference`, `rerank_policy JSONB`, `budget JSONB` |
| `discovery_sessions` | One row per cycle's discovery run | `cycle_id FK`, `status`, `view`, `started_at`, `completed_at`, `stats JSONB`, `step_log JSONB`, `report_artifact_path` |
| `paper_cards` | Candidate papers within a discovery session | `session_id FK`, `charter_id FK`, `source` (`internal_corpus` \| `arxiv_live`), `external_id`, `dedupe_key` (normalized arxiv_id/doi), `title`, `abstract`, `authors JSONB`, `venue`, `year`, `published_at`, `first_stage_score`, `bm25_score`, `dense_score`, `rerank_score`, `final_score`, `view_membership JSONB`, `triage_status`, `metadata_analysis JSONB` (nullable until analysis runs), `created_at`. Unique index on `(session_id, dedupe_key)`. |
| `discovery_evaluations` | Optional ground-truth metrics | `session_id FK`, `metric`, `k`, `value`, `source` (`user_supplied` \| `auto`) |

Notes:

- `arxiv_corpus.tsv` is a `GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || abstract)) STORED` column with a GIN index. This gives BM25-style lexical retrieval natively, no extra service.
- HNSW index on `embedding` (`vector_cosine_ops`, `m=16`, `ef_construction=64`) — fits inside one Postgres instance and is fast enough for ~3 M rows. Note: the on-disk index will be sizable (rough order ~10 GB); plan disk accordingly.
- `paper_cards` carries denormalized title/abstract so internal vs live results unify; metadata-analysis JSON lives alongside, optionally promoted to a typed column later.
- The Phase 0 [naming convention](libs/storage/base.py) and timestamp/UUID conventions are mirrored exactly. JSONB fields use `postgresql.JSONB(astext_type=sa.Text())`.

Pydantic schemas mirror the [charter.py pattern](libs/schemas/charter.py) (`from_attributes=True`, `*Create`, `*Read`, `*Update` shapes). New module: [libs/schemas/discovery.py](libs/schemas/discovery.py) for `ProblemProfile{Create,Read}`, `DiscoverySession{Create,Read,Summary}`, `PaperCardRead`, `DiscoveryReport`, `EvaluationMetricRead`.

### 2. Corpus importer

New CLI command in [apps/cli/](apps/cli/) (Typer): `synthetos corpus import-arxiv --path artifacts/arxiv-embedded.jsonl [--limit N] [--resume]`.

- Streams the JSONL line-by-line with `orjson` (avoid loading 56 GB into RAM).
- Validates `_synthetos_format == "synthetos.arxiv.embedded.v1"` and `embedding_model_id == "Alibaba-NLP/gte-modernbert-base"` per record; rejects mismatches.
- `COPY`-style bulk insert via `psycopg`'s binary `copy_from` for throughput; falls back to batched `INSERT ... ON CONFLICT (arxiv_id) DO UPDATE` when `--resume` is set.
- Tracks progress via a tiny `corpus_import_runs` table (or a JSON checkpoint under `LAB_DATA_ROOT/cache/corpus_import.json` — pick the simpler one) so a crash mid-import resumes by `content_hash`.
- Builds the HNSW index *after* the bulk load completes (`CREATE INDEX CONCURRENTLY`). The lexical GIN index on `tsv` is generated automatically.
- Emits structlog progress every 50k rows.

This is a one-time cold-load operation. Live updates come from the arXiv adapter, not the importer.

### 3. Source adapters

New package [libs/adapters/sources/](libs/adapters/sources/) — one base protocol, two implementations.

[libs/adapters/sources/base.py](libs/adapters/sources/base.py)

```python
class SourceAdapter(Protocol):
    name: str  # "internal_corpus" | "arxiv_live"
    async def search(self, query: SourceQuery) -> list[SourceHit]: ...
    async def fetch_metadata(self, ids: list[str]) -> list[SourceHit]: ...
    async def close(self) -> None: ...
```

`SourceHit` is a Pydantic DTO with the union of fields needed to populate a `paper_cards` row (no embedding required from live sources — they only contribute to lexical first-stage). `SourceQuery` carries text, top_k, date filters, category filters, and the dedupe key strategy.

[libs/adapters/sources/internal_corpus.py](libs/adapters/sources/internal_corpus.py)

- Hybrid retrieval over `arxiv_corpus`:
  - **Lexical**: `SELECT ... ORDER BY ts_rank_cd(tsv, plainto_tsquery('english', :q)) DESC LIMIT :k`
  - **Dense**: query embedding from `EmbeddingsRouter` (see §4) → `ORDER BY embedding <=> :qvec LIMIT :k`
  - **Fusion**: RRF over the two ranked lists with `k=60` and merged top_k = `max(k_lex, k_dense)`. Returns per-hit `bm25_score`, `dense_score`, `first_stage_score = rrf_score`.
- Pure SQL via SQLAlchemy 2 async session — no separate index server.

[libs/adapters/sources/arxiv_live.py](libs/adapters/sources/arxiv_live.py)

- Async `httpx.AsyncClient` against `http://export.arxiv.org/api/query`.
- Vendors only the *query construction + Atom parsing* slice from [github.com/M-Chimiste/arxiv-harvester](https://github.com/M-Chimiste/arxiv-harvester) (no upstream dependency — copy + adapt minimal code with attribution in a `NOTICE` comment, then prune).
- Honors a 3-second min interval between requests (arXiv ToS) via a token bucket.
- Returns metadata only: title, abstract, authors, categories, dates, links. No embeddings.
- `tenacity` retry on 5xx / `429`.

[libs/adapters/sources/dedupe.py](libs/adapters/sources/dedupe.py)

- Cross-source dedupe key: prefer `doi`, fall back to canonicalized `arxiv_id` (strip version), fall back to `sha1(lower(title) + first_author_surname)`.
- Merge strategy: prefer the row with embedding (i.e. internal_corpus) and union `view_membership`. Live-only rows mark `embedding_source = "needs_embed"`; an optional follow-up step (post-rerank) can lazy-embed them.

### 4. Embeddings router

[libs/adapters/embeddings/router.py](libs/adapters/embeddings/router.py) — mirrors [LLM router](libs/adapters/llm/router.py). Reads new section `embeddings:` in `configs/models.yaml`:

```yaml
embeddings:
  default:
    provider: local
    model: Alibaba-NLP/gte-modernbert-base
    base_url: http://localhost:8080/v1   # text-embeddings-inference or vllm
    dimension: 768
```

The corpus is already embedded with this exact model, so query-time embeddings *must* come from the same checkpoint or cosine results will be garbage. Validate dimension == 768 at startup; fail loudly otherwise.

A reusable singleton-per-process `EmbeddingsRouter` is injected into the internal_corpus adapter and into the (future) Phase 2 chunkers.

### 5. Reranker

[libs/adapters/reranker/base.py](libs/adapters/reranker/base.py) defines:

```python
class Reranker(Protocol):
    async def rerank(self, query: str, docs: list[RerankDoc], top_k: int) -> list[RerankResult]: ...
    async def health(self) -> bool: ...
```

[libs/adapters/reranker/local_cross_encoder.py](libs/adapters/reranker/local_cross_encoder.py)

- Loads a small cross-encoder lazily (default: `BAAI/bge-reranker-v2-m3`, configurable). Uses `sentence-transformers` CrossEncoder with GPU autodetect.
- Batched scoring over the top-N from first-stage (default N=100, configurable per-cycle in `ProblemProfile.rerank_policy`).
- Honors a wall-clock budget (`rerank_policy.budget_seconds`); if it would exceed, raises `RerankBudgetExceeded`.

[libs/adapters/reranker/no_op.py](libs/adapters/reranker/no_op.py) — returns inputs unchanged with `rerank_score = first_stage_score`. Used when:

1. The local cross-encoder model isn't downloaded yet, or
2. The reranker raises `RerankBudgetExceeded`, or
3. `rerank_policy.enabled = false` on the `ProblemProfile`.

The chooser logic lives in [libs/discovery/rerank_strategy.py](libs/discovery/rerank_strategy.py) and is what the `discovery_rerank` operator calls. Every fallback emits a `discovery.rerank_skipped` event with the reason — this is the "graceful degradation" the plan requires.

### 6. Discovery library — operators, ranking, views

New top-level package [libs/discovery/](libs/discovery/):

```
libs/discovery/
  __init__.py
  problem.py            # ProblemProfile build/normalize from charter intake
  ranking.py            # rrf_fuse(), score utilities
  views.py              # build_stable_view(), build_discovery_view() (MMR)
  rerank_strategy.py    # choose reranker, fallback, budget enforcement
  metadata_analysis.py  # LLM call orchestration, structured output schema
  reports.py            # render DiscoveryReport bundle (markdown + json)
  operators/
    intake.py           # discovery_intake operator
    search.py           # discovery_search operator
    rerank.py           # discovery_rerank operator
    analyze.py          # discovery_analyze operator
    finalize.py         # discovery_finalize operator
```

Each operator module exposes a single `async def run(op_input: OperatorInput) -> OperatorResult` and is registered in [apps/worker/executor.py](apps/worker/executor.py) the same way `_echo_operator` is. Pattern per operator:

1. Open a session via the worker's session factory.
2. Load the `DiscoverySession` + `ProblemProfile` rows for the cycle.
3. Do its slice of work (search, rerank, analyze, etc.).
4. Persist new/updated `paper_cards` rows.
5. Append a step entry to `discovery_sessions.step_log`.
6. Return an `OperatorResult` with:
   - `events`: typed events from `DiscoveryEvents` enum (see §9).
   - `state_patch`: only the *finalize* operator sets `cycle_status: "discovery_screened"`.
   - `artifacts`: paths to any files written under `LAB_DATA_ROOT/artifacts/discovery/<session_id>/`.

**Ranking — [libs/discovery/ranking.py](libs/discovery/ranking.py)**

```python
def rrf_fuse(rankings: list[list[str]], *, k: int = 60) -> dict[str, float]:
    """Reciprocal rank fusion over multiple ranked id lists."""
```

Used by `internal_corpus.search` and again in `discovery_finalize` if needed.

**Views — [libs/discovery/views.py](libs/discovery/views.py)**

- `build_stable_view(cards, top_k)` → top_k by `final_score` descending. Deterministic given same scores.
- `build_discovery_view(cards, top_k, lambda_param=0.7)` → MMR diversification using cosine over the same gte-modernbert vectors (or, for live-only cards lacking embeddings, fall back to category overlap as the diversity proxy).

`view_membership` on each `paper_cards` row records which views it belongs to (`["stable", "discovery"]`).

**Metadata-depth analysis — [libs/discovery/metadata_analysis.py](libs/discovery/metadata_analysis.py)**

```python
class MetadataAnalysisPacket(BaseModel):
    likely_method_family: str
    likely_contribution_type: Literal["benchmark","method","theory","survey","application","artifact","other"]
    shortlist_fit: float                  # 0..1
    escalation_rationale: str             # why (or why not) escalate to full text
    relevance_to_problem: float           # 0..1
    one_line_summary: str
    risks_or_caveats: list[str]
```

Called via [ModelRouter.complete_structured](libs/adapters/llm/router.py) with `role=ModelRole.metadata_analysis` (already wired in Phase 0 to the local Ollama endpoint). Concurrent over the top-N candidates with `asyncio.Semaphore` rate limit. Each result is stored on the `paper_cards.metadata_analysis` JSONB column. The operator emits one `discovery.paper_metadata_analyzed` event per packet so the SSE stream stays useful.

### 7. API surface

New router [apps/api/routers/discovery.py](apps/api/routers/discovery.py), mounted under `/api/v1` in [apps/api/main.py](apps/api/main.py). Follows the [charters router pattern](apps/api/routers/charters.py) (`Depends(get_db)`, `Depends(require_scope(...))`):

| Method | Path | Scope | Purpose |
|---|---|---|---|
| `POST` | `/charters/{charter_id}/discovery` | `cycles.write` | Create a discovery session on the active cycle (or create cycle inline). Body = `ProblemProfileCreate`. Enqueues `discovery_intake` job. |
| `GET` | `/discovery/{session_id}` | `cycles.read` | `DiscoverySessionRead` with status, stats, view config, step log. |
| `GET` | `/discovery/{session_id}/papers` | `cycles.read` | Paginated `PaperCardRead`, filterable by `view`, `triage_status`, `min_score`. |
| `GET` | `/discovery/{session_id}/papers/{paper_id}` | `cycles.read` | Single card incl. metadata analysis packet. |
| `POST` | `/discovery/{session_id}/papers/{paper_id}/triage` | `cycles.write` | Manual override: shortlist / drop / escalate. |
| `GET` | `/discovery/{session_id}/report` | `cycles.read` | Renders + returns the `DiscoveryReport` bundle (markdown + JSON), suitable for download. |
| `POST` | `/discovery/{session_id}/evaluation` | `cycles.write` | Submit ground truth labels; computes Recall@K / Precision@K / MRR and stores in `discovery_evaluations`. |

Two new scopes added in [apps/api/auth.py](apps/api/auth.py): `discovery.read` is an alias for `cycles.read`; no new admin scopes. (Alternatively reuse cycles scopes — pick one in implementation; the existing `cycles.*` scopes already cover this semantically and adding new ones risks proliferation.)

The existing SSE stream at `/api/v1/events/stream` already carries every domain event with charter_id/cycle_id filters, so progress monitoring needs no new endpoint — clients just subscribe and look for `discovery.*` event types.

Hand-maintained TS types added to [apps/web/src/api/client.ts](apps/web/src/api/client.ts) and TanStack Query hooks to [apps/web/src/api/hooks.ts](apps/web/src/api/hooks.ts), exactly mirroring the existing charter pattern (no codegen — Phase 0 is manual).

### 8. Web UI

Minimum useful UI lives in [apps/web/src/routes/](apps/web/src/routes/):

- **`charters/$charterId/discovery/new.tsx`** — Form to create a `ProblemProfile`: query text, source scope checkboxes (internal_corpus, arxiv_live), view preference (stable/discovery/both), rerank toggle, budget slider. Submit → POST → redirect to session detail.
- **`discovery/$sessionId.tsx`** — Session header (status, stats, step log), tabbed paper list with **Stable** and **Discovery** view tabs, per-paper card showing title/abstract/scores/metadata-analysis summary, triage buttons, link to download report.
- **`discovery/$sessionId/report.tsx`** — Rendered markdown view of the discovery report.

The existing [EventStream component](apps/web/src/components/EventStream.tsx) is reused on the session detail page filtered by `cycle_id`, so the user sees live `discovery.papers_discovered`, `discovery.rerank_skipped`, `discovery.paper_metadata_analyzed`, and `discovery.session_finalized` events as they happen.

### 9. Events taxonomy

New module [libs/core/event_types.py](libs/core/event_types.py) (referenced but not yet created in Phase 0) with a `DiscoveryEvents` `StrEnum`:

```python
class DiscoveryEvents(StrEnum):
    intake_completed              = "discovery.intake_completed"
    search_started                = "discovery.search_started"
    papers_discovered             = "discovery.papers_discovered"
    sources_deduped               = "discovery.sources_deduped"
    rerank_started                = "discovery.rerank_started"
    rerank_completed              = "discovery.rerank_completed"
    rerank_skipped                = "discovery.rerank_skipped"          # incl. reason
    paper_metadata_analyzed       = "discovery.paper_metadata_analyzed"
    view_built                    = "discovery.view_built"
    session_finalized             = "discovery.session_finalized"
    evaluation_recorded           = "discovery.evaluation_recorded"
```

Event type strings stay namespaced with a `discovery.` prefix so the SSE consumer in the web app can filter cleanly. Existing job lifecycle events (`job_started`, `job_completed`, etc.) are emitted by the worker exactly as they are today.

### 10. Skills (first-party literature pack)

New first-party skills under [skills/literature/](skills/literature/), each a `skill.md` file with the existing [manifest schema](libs/schemas/skills.py):

| Skill id | Phase | Allowed operators | Risk |
|---|---|---|---|
| `literature.problem_scoping` | discovery | `discovery_intake` | low |
| `literature.title_abstract_triage` | discovery | `discovery_analyze` | low |
| `literature.shortlist_critique` | discovery | `discovery_finalize` | low |
| `literature.escalation_rationale` | discovery | `discovery_analyze`, `discovery_finalize` | low |

Each skill body is a Markdown prompt template that the operator pulls in via the `SkillRegistry` and prepends to its system message. None require `python.hooks`, `fs.write`, or `network.access`, so they all qualify as `first_party_trusted`. Discovered automatically by the existing [skills loader](libs/skills/loader.py) once the skill files exist under the configured `LAB_SKILL_PATHS`.

The actual operator-side skill consumption (scoped context assembly) is intentionally **minimal in Phase 1** — just look up by id and inject the prompt body. Full skill-aware context assembly is a Phase 2+ concern.

### 11. Configs

- Add `embeddings:` block to [configs/models.yaml](configs/models.yaml) (see §4).
- Add `roles.metadata_analysis` is already present — verify its provider can return JSON-mode structured outputs against the local Ollama endpoint; if not, route to `anthropic` for Phase 1 reliability and revisit later.
- New file [configs/discovery/defaults.yaml](configs/discovery/defaults.yaml):
  ```yaml
  first_stage:
    top_k: 200
    rrf_k: 60
  rerank:
    enabled: true
    top_n: 100
    budget_seconds: 30
    model: BAAI/bge-reranker-v2-m3
  views:
    stable_top_k: 25
    discovery_top_k: 25
    discovery_mmr_lambda: 0.7
  analysis:
    analyze_top_n: 25
    concurrency: 4
  ```
  Loaded by `ProblemProfile` builder as the defaults; users override per-cycle via the intake form.

### 12. Tests

Following the existing [tests layout](tests/):

**Unit ([tests/unit/](tests/unit/))**
- `test_rrf.py` — RRF fusion, tie-breaking, edge cases.
- `test_dedupe.py` — DOI / arxiv-id / title-hash key generation.
- `test_views.py` — Stable view determinism, MMR diversification.
- `test_rerank_strategy.py` — Fallback chain (model missing → no_op, budget exceeded → no_op, normal → cross-encoder).
- `test_metadata_analysis_schema.py` — Pydantic model accepts/rejects sample LLM outputs.
- `test_arxiv_live_parser.py` — Atom parsing fixtures.
- `test_corpus_importer.py` — Streams a 5-record fixture JSONL into a temp DB and verifies inserts + index existence.

**Integration ([tests/integration/](tests/integration/))** — uses `testcontainers[postgres]`:
- `test_internal_corpus_search.py` — Seeds 100 fixture rows, runs hybrid search, asserts expected ordering.
- `test_discovery_pipeline.py` — End-to-end through all five operators in-process, asserts cycle transitions, paper_cards population, view membership, report file existence.
- `test_discovery_api.py` — Spins up FastAPI test client, exercises POST/GET endpoints with a token.

**Fixtures ([tests/fixtures/](tests/fixtures/))**
- `arxiv_sample.jsonl` — 20 hand-picked records (real arXiv ids) covering several categories.
- `arxiv_live_atom.xml` — Recorded arXiv Atom response for offline testing.
- Charter / cycle / discovery_session factories using `factory-boy`.

### 13. CLI

Add a Typer command group to [apps/cli/](apps/cli/):

- `synthetos corpus import-arxiv [--path] [--limit] [--resume]` — see §2.
- `synthetos discovery run --charter-id <uuid> --query "..." [--view stable|discovery|both] [--rerank/--no-rerank]` — convenience wrapper that creates a charter+cycle if missing, posts a discovery session, and tails events. Useful for headless testing without the web UI.

---

## Critical files to be created or touched

**Created:**

- [libs/storage/models/corpus.py](libs/storage/models/corpus.py)
- [libs/storage/models/discovery.py](libs/storage/models/discovery.py)
- [libs/storage/models/papers.py](libs/storage/models/papers.py)
- [libs/storage/migrations/versions/20260411_000001_phase1_discovery.py](libs/storage/migrations/versions/20260411_000001_phase1_discovery.py)
- [libs/schemas/discovery.py](libs/schemas/discovery.py)
- [libs/schemas/papers.py](libs/schemas/papers.py)
- [libs/core/event_types.py](libs/core/event_types.py)
- [libs/adapters/embeddings/router.py](libs/adapters/embeddings/router.py)
- [libs/adapters/sources/{base,internal_corpus,arxiv_live,dedupe}.py](libs/adapters/sources/)
- [libs/adapters/reranker/{base,local_cross_encoder,no_op}.py](libs/adapters/reranker/)
- [libs/discovery/](libs/discovery/) — full subpackage per §6
- [apps/api/routers/discovery.py](apps/api/routers/discovery.py)
- [apps/web/src/routes/charters/$charterId/discovery/new.tsx](apps/web/src/routes/)
- [apps/web/src/routes/discovery/$sessionId.tsx](apps/web/src/routes/)
- [apps/web/src/routes/discovery/$sessionId/report.tsx](apps/web/src/routes/)
- [skills/literature/](skills/) — four skill.md packages
- [configs/discovery/defaults.yaml](configs/)
- Test files per §12

**Touched:**

- [apps/worker/executor.py](apps/worker/executor.py) — register the five new operators.
- [apps/api/main.py](apps/api/main.py) — mount discovery router.
- [apps/api/auth.py](apps/api/auth.py) — only if you decide to add `discovery.*` scopes; otherwise reuse `cycles.*`.
- [apps/web/src/api/client.ts](apps/web/src/api/client.ts), [hooks.ts](apps/web/src/api/hooks.ts) — types + hooks for discovery.
- [apps/web/src/components/Layout.tsx](apps/web/src/components/Layout.tsx) — nav link to a discovery sessions index (optional).
- [configs/models.yaml](configs/models.yaml) — add `embeddings:` block, possibly retarget `metadata_analysis` role.
- [pyproject.toml](pyproject.toml) — add deps: `sentence-transformers`, `feedparser` (or `lxml` for Atom), confirm `orjson`/`psycopg[binary]` are present.

---

## Key reuse from Phase 0

- **OperatorInput / OperatorResult** ([libs/core/operators.py](libs/core/operators.py)) — every new operator follows the existing dataclass contract; no new framework needed.
- **State machine + state_patch flow** ([libs/core/state_machine.py](libs/core/state_machine.py), [apps/worker/main.py](apps/worker/main.py#L91)) — `discovery_finalize` is the only operator that touches `cycle_status`, advancing `discovery_ready → discovery_screened`.
- **emit_event_sync** ([libs/core/events.py](libs/core/events.py)) — already wired into the worker's persist loop; new event types just appear as strings on `domain_events`.
- **ModelRouter.complete_structured** ([libs/adapters/llm/router.py](libs/adapters/llm/router.py)) — for metadata-depth analysis; do not reinvent.
- **SkillRegistry** ([libs/skills/registry.py](libs/skills/registry.py)) — for prompt injection.
- **SSE event stream** ([apps/api/routers/events.py](apps/api/routers/events.py)) — no changes needed; UI just filters by event type prefix.
- **Auth/scopes** ([apps/api/auth.py](apps/api/auth.py)) — reuse existing `cycles.read` / `cycles.write`.

---

## Verification

1. **Migration** — `alembic upgrade head` succeeds on a clean DB; rollback (`alembic downgrade -1`) cleanly reverses Phase 1.
2. **Importer dry-run** — `synthetos corpus import-arxiv --path artifacts/arxiv-embedded.jsonl --limit 10000`. Verify `arxiv_corpus` row count, presence of HNSW index (`\d+ arxiv_corpus` in psql), and that `tsv` is populated. Round-trip a known query.
3. **Full importer** — Run unconstrained import once. Note wall-clock time and final row count. Confirm `EXPLAIN ANALYZE` on a hybrid query uses both the GIN and HNSW indexes.
4. **Internal-only discovery** — Create a charter via UI, kick off a discovery with `arxiv_live` disabled. Confirm the cycle transitions `created → discovery_ready → discovery_screened`, that `paper_cards` populates with sane scores, and that the report renders.
5. **arXiv live discovery** — Same flow with `arxiv_live` enabled. Confirm dedupe collapses duplicates with the internal corpus correctly (pick a query that overlaps).
6. **Reranker fallback** — Force `RerankBudgetExceeded` (set `budget_seconds: 0.001`). Confirm pipeline completes, `discovery.rerank_skipped` event is emitted with `reason="budget_exceeded"`, and `final_score == first_stage_score`.
7. **Reranker happy path** — With a real local cross-encoder, verify rerank_score differs from first_stage_score and ordering changes.
8. **Metadata analysis** — Inspect 5 random `paper_cards.metadata_analysis` packets in the DB; confirm fields populated, schema-valid, and one_line_summary readable.
9. **API contract** — `pytest tests/integration/test_discovery_api.py` green. Hit each endpoint with `httpie` against a real token. Verify 401 without token, 403 without scope.
10. **SSE stream** — Open the web UI on the discovery session page; observe live `discovery.*` events streaming during a run.
11. **Evaluation hook** — Submit a fixture ground-truth set; verify Recall@10 / Precision@10 / MRR computed and stored.
12. **Orchestrator simulation** — From a separate terminal, use `httpx` to (a) create a charter, (b) create a discovery session, (c) subscribe to the SSE stream, (d) fetch the report — *without touching the UI*. This validates the "external client can run discovery without scraping the UI" exit criterion (plan §6.4).
13. **Quality gates** — `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest`, `npm run test`, `npm run typecheck`.

---

## Explicit non-goals for Phase 1

- Full-text fetch (HTML/PDF), structure-aware chunking, paper graphs — Phase 2.
- Evidence cards, hypothesis cards, experiment specs — Phase 3.
- Auto-remediation, directional signal, frontier — Phase 4.
- Autonomous loop, gating, completion reports — Phase 5.
- Cross-charter pattern memory — Phase 6.
- Re-embedding the corpus or supporting alternate embedding models — out of scope; Phase 1 is locked to `gte-modernbert-base`.
- Semantic Scholar / OpenAlex / Crossref — deferred.
- A new OpenAPI codegen pipeline for the web client — Phase 0 stays manual; revisit later.

---

## Open assumptions worth flagging during implementation

1. **`metadata_analysis` LLM role**: currently routes to local Ollama. If the local model can't reliably emit structured JSON via the Anthropic-style tool-calling adapter, switch this role to `anthropic` in `models.yaml` for Phase 1 stability and revisit when the local stack is hardened. Cost is low (title + abstract per call).
2. **`gte-modernbert` query embedding service**: needs a running OpenAI-compatible embedding endpoint serving the exact same checkpoint used to embed the corpus. If one isn't already wired, plan to stand up `text-embeddings-inference` or `vllm` in `docker-compose.yml` as an optional service. Validate dimension at startup.
3. **HNSW build time**: building the HNSW index over ~3 M rows will be measured in tens of minutes to a couple of hours depending on hardware. Build with `CREATE INDEX CONCURRENTLY` after the bulk load so the importer can return promptly, and bump `maintenance_work_mem` for the duration. Disk footprint of the corpus + HNSW index combined is likely ~70–80 GB; verify free space before kicking off the import.
4. **Cross-encoder model download**: first run will need ~1 GB pull. The reranker fallback covers the case where it isn't available, so Phase 1 stays usable even before the model is downloaded.
