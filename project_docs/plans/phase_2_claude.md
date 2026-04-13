# Phase 2 — Full Paper Analysis and Evidence Pipeline

## Context

Phase 0 (foundation) and Phase 1 (discovery pipeline) are complete. The system can create research charters, run discovery with internal corpus + arXiv, rank/rerank papers, do metadata-depth analysis (title+abstract), build Stable/Discovery views, and export discovery reports.

Phase 2 turns shortlisted papers into deep, structured understanding. It adds full-text ingestion, typed paper graphs, graph-aware QA, coverage verification, review artifacts, and evidence extraction — bridging discovery and hypothesis generation.

## Design Decisions

- **Persisted full-text artifact**: A new `ingested_documents` table stores the normalized document structure (sections, figures, tables, equations), raw content, fetch metadata, and quality assessment. Chunks are derived from this artifact. Re-chunking or re-extraction never requires re-fetching. The ingestion operator writes this artifact; the chunking operator reads from it.
- **Model-driven contradiction/redundancy**: Each new evidence card is compared against existing cards in the cycle. **Canonical prefilter rule**: embed the new claim, retrieve existing evidence cards with embedding cosine similarity > 0.7 (via pgvector). No concept-overlap check — embedding similarity is the sole gate. For each candidate pair passing the threshold, call LLM (`ModelRole.paper_analysis`) to classify as contradictory/redundant/independent with reasoning. Results stored as structured flags on the evidence card.
- **AGE optional, relational canonical**: `graph_nodes` and `graph_edges` relational tables are the canonical graph store and always work. AGE projection is attempted if the extension is available, skipped gracefully if not. Graph QA falls back to SQL joins + CTE-based traversal over relational tables when AGE is unavailable. The `GraphAdapter` protocol has two implementations: `AgeGraphAdapter` and `RelationalGraphAdapter`.
- **Reuse cycles scopes**: Analysis API routes use `cycles.read` and `cycles.write` scopes. No new scopes introduced.
- **One analysis session per paper, latest-wins reads**: Keeps operator scope narrow, failure blast radius small. Re-analyze by creating a new session. **API semantics for paper-keyed endpoints** (`/papers/{id}/analysis-packet`, `/papers/{id}/review`, `/papers/{id}/qa`, `/papers/{id}/locate`): always resolve to the latest *completed* analysis session for that paper. If no completed session exists, return 404. Session-keyed endpoints (`/analysis/{session_id}/...`) always return data for the specific session regardless of completion status. This means re-analysis produces a new session, and once it completes, the paper-keyed endpoints automatically switch to the new data.
- **Chunk before extract**: Graph nodes reference specific chunks for provenance; chunk embeddings also serve QA retrieval.
- **evidence_cards.analysis_depth**: Distinguishes metadata-only evidence (from Phase 1) vs full-text evidence (Phase 2) so downstream consumers can weight appropriately.

---

## Implementation Steps

### Step 1: Database & Schema Foundation

**Migration** — `libs/storage/migrations/versions/20260412_000001_phase2_analysis.py`

New tables:

**`ingested_documents`** — persisted full-text artifact (one per analysis session)
- `id` UUID PK
- `analysis_session_id` FK → analysis_sessions (UNIQUE)
- `paper_card_id` FK → paper_cards
- `fetch_method` VARCHAR(20) — "html" or "pdf_docling"
- `source_url` TEXT — URL that was fetched
- `raw_content` TEXT — original HTML or extracted text
- `normalized_sections` JSONB — list of `{heading, level, content, page_range}`
- `normalized_figures` JSONB — list of `{id, caption, page, content_description}`
- `normalized_tables` JSONB — list of `{id, caption, page, content_description}`
- `normalized_equations` JSONB — list of `{id, latex, context, page}`
- `quality_assessment` JSONB — `{structure_preserved: bool, section_count, figure_count, table_count, equation_count, quality_score: float, quality_warnings: list[str]}`
- `fetch_duration_ms` INTEGER
- `content_hash` VARCHAR(64) — SHA-256 of raw_content for change detection
- `created_at` DATETIME

**`analysis_sessions`** — one per paper being analyzed
- `id` UUID PK
- `cycle_id` FK → research_cycles
- `charter_id` FK → research_charters
- `paper_card_id` FK → paper_cards
- `status` VARCHAR(50) — created, ingesting, chunking, extracting, verifying, reviewing, evidence_extracting, completed, failed
- `stats` JSONB, `step_log` JSONB, `error` TEXT nullable
- `report_artifact_path` TEXT nullable
- `created_at`, `updated_at`, `started_at`, `completed_at` DATETIME
- Indexes: `(cycle_id, created_at)`, `(paper_card_id)`, `(status)`

**`paper_chunks`** — structure-aware chunks derived from ingested_documents
- `id` UUID PK
- `analysis_session_id` FK → analysis_sessions CASCADE
- `paper_card_id` FK → paper_cards CASCADE
- `chunk_type` VARCHAR(50) — section, paragraph, figure, table, equation
- `section_path` TEXT — e.g. "3.2.1 Experimental Setup"
- `ordinal` INTEGER — position within the paper
- `content` TEXT
- `content_hash` VARCHAR(64)
- `embedding` Vector(768) nullable
- `metadata` JSONB — source_page, bounding_box, caption, parent_section, etc.
- `created_at` DATETIME
- Indexes: `(analysis_session_id, ordinal)`, `(paper_card_id, chunk_type)`
- HNSW index on `embedding`

**`graph_nodes`** — typed graph nodes (canonical relational store)
- `id` UUID PK
- `analysis_session_id` FK → analysis_sessions CASCADE
- `paper_card_id` FK → paper_cards CASCADE
- `node_type` VARCHAR(50) — paper, section, concept, method, experiment, dataset, figure, table, equation
- `label` TEXT, `description` TEXT nullable
- `properties` JSONB, `provenance` JSONB (source chunk IDs, confidence, extraction method/model)
- `age_node_id` VARCHAR(100) nullable — set only when AGE projection succeeds
- `embedding` Vector(768) nullable
- `created_at` DATETIME
- Indexes: `(analysis_session_id, node_type)`, `(paper_card_id)`

**`graph_edges`** — typed relations (canonical relational store)
- `id` UUID PK
- `analysis_session_id` FK → analysis_sessions CASCADE
- `source_node_id` FK → graph_nodes CASCADE
- `target_node_id` FK → graph_nodes CASCADE
- `edge_type` VARCHAR(50) — contained_in, defines, proposes, uses, evaluates, illustrates, compares, depends_on
- `properties` JSONB, `provenance` JSONB
- `confidence` FLOAT nullable
- `age_edge_id` VARCHAR(100) nullable
- `created_at` DATETIME
- Indexes: `(source_node_id)`, `(target_node_id)`, `(analysis_session_id, edge_type)`

**`coverage_diagnostics`** — one per analysis session
- `id` UUID PK
- `analysis_session_id` FK → analysis_sessions CASCADE (UNIQUE)
- `section_coverage` JSONB — `{total, covered, missing: [...]}`
- `figure_coverage` JSONB, `table_coverage` JSONB, `equation_coverage` JSONB
- `unlinked_artifacts` JSONB — list of chunk IDs with no graph links
- `warnings` JSONB — list of warning strings
- `overall_score` FLOAT — 0..1 composite coverage score
- `created_at` DATETIME

**`paper_analysis_packets`** — canonical structured artifact
- `id` UUID PK
- `analysis_session_id` FK → analysis_sessions CASCADE (UNIQUE)
- `paper_card_id` FK → paper_cards CASCADE
- `charter_id` FK → research_charters CASCADE
- `summary` TEXT
- `key_contributions` JSONB, `methods_used` JSONB, `datasets_referenced` JSONB
- `reproducibility_notes` JSONB
- `graph_summary` JSONB — node_counts, edge_counts by type
- `coverage_snapshot` JSONB — copy of coverage_diagnostics at completion
- `chunk_count` INTEGER, `node_count` INTEGER, `edge_count` INTEGER
- `analysis_depth` VARCHAR(20) — "full"
- `created_at`, `updated_at` DATETIME
- Indexes: `(paper_card_id)`, `(charter_id)`

**`paper_review_artifacts`** — advisory review (only for fully analyzed papers)
- `id` UUID PK
- `analysis_packet_id` FK → paper_analysis_packets CASCADE
- `paper_card_id` FK → paper_cards CASCADE
- `strengths` JSONB, `weaknesses` JSONB, `open_questions` JSONB
- `critique` TEXT
- `scores` JSONB — e.g. `{novelty: 0.7, rigor: 0.8, relevance: 0.9}`
- `reading_priority` VARCHAR(20) — high, medium, low
- `created_at` DATETIME
- Index: `(paper_card_id)`

**`evidence_cards`** — extracted evidence for downstream hypothesis generation
- `id` UUID PK
- `charter_id` FK → research_charters CASCADE
- `cycle_id` FK → research_cycles CASCADE
- `paper_card_id` FK → paper_cards CASCADE
- `analysis_packet_id` FK → paper_analysis_packets nullable
- `evidence_type` VARCHAR(50) — finding, method_claim, dataset_availability, limitation, comparison
- `claim` TEXT — the core evidence statement
- `supporting_text` TEXT nullable
- `source_chunk_ids` JSONB — list of chunk UUIDs
- `source_graph_node_ids` JSONB — list of graph node UUIDs
- `confidence` FLOAT — 0..1
- `analysis_depth` VARCHAR(20) — "metadata" or "full"
- `contradiction_flags` JSONB nullable — `{contradicts: [{evidence_id, reason, model_confidence}]}`
- `redundancy_group` VARCHAR(100) nullable
- `embedding` Vector(768) nullable — for similarity pre-filtering during contradiction detection
- `metadata` JSONB nullable
- `created_at`, `updated_at` DATETIME
- Indexes: `(charter_id, evidence_type)`, `(paper_card_id)`, `(cycle_id)`
- HNSW index on `embedding`

Also:
- Add `analysis_status` column to `paper_cards` (VARCHAR(50), default "not_analyzed", values: not_analyzed, analyzing, analyzed, failed)
- Conditionally enable AGE: `CREATE EXTENSION IF NOT EXISTS age;` — wrapped in a DO block that catches exceptions so migration succeeds even if AGE is not installed

**SQLAlchemy models** — `libs/storage/models/analysis.py`
- All 9 models (IngestedDocument, AnalysisSession, PaperChunk, GraphNode, GraphEdge, CoverageDiagnostic, PaperAnalysisPacket, PaperReviewArtifact, EvidenceCard)
- Update `libs/storage/models/__init__.py`
- Add `analysis_status` to existing PaperCard model in `libs/storage/models/papers.py`

**Pydantic schemas** — `libs/schemas/analysis.py`
- IngestedDocumentRead, NormalizedSection, NormalizedFigure, NormalizedTable, NormalizedEquation, QualityAssessment
- PaperChunkRead, GraphNodeRead, GraphEdgeRead
- CoverageDiagnosticRead, CoverageDetail
- PaperAnalysisPacketRead, PaperReviewArtifactRead
- EvidenceCardRead, EvidenceCardCreate, ContradictionFlag
- QARequest/QAResponse (answer, supporting_chunks: list[ChunkRef], supporting_nodes: list[NodeRef], confidence)
- LocateRequest/LocateResponse (matches with chunk refs and graph node refs)
- AnalysisSessionRead, AnalysisSessionStartRequest, AnalysisBudget
- Add `analysis_status` to PaperCardRead in `libs/schemas/papers.py`

**State machine** — Update `ALLOWED_TRANSITIONS` in `libs/core/state_machine.py`:
```python
CycleStatus.analysis_ready: [CycleStatus.analysis_ready, CycleStatus.evidence_ready],
```

**Event types** — add to `libs/core/event_types.py`:
- `analysis.session_started` — emitted when analysis session is created (includes paper_card_id, session_id)
- `analysis.paper_ingested` — full text fetched (includes fetch_method, quality_score)
- `analysis.paper_chunked` — chunking complete (includes chunk_count by type)
- `analysis.graph_extracted` — graph built (includes node_count, edge_count by type)
- `analysis.coverage_computed` — coverage verified (includes overall_score, warning_count)
- `analysis.review_generated` — review artifact created
- `analysis.evidence_extracted` — evidence cards created (includes card_count, contradiction_count)
- `analysis.session_completed` — full pipeline done
- `analysis.session_failed` — pipeline failed (includes step, error)

These events are emitted by each operator via `emit_event_sync()` (same as discovery operators) and are visible to orchestrators via the existing SSE event stream.

---

### Step 2: Adapters

**Paper ingestion adapter** — `libs/adapters/ingestion/`
- `base.py` — `IngestionAdapter` Protocol (same `@runtime_checkable` pattern as `libs/adapters/sources/base.py`)
  ```python
  @runtime_checkable
  class IngestionAdapter(Protocol):
      name: str
      async def fetch_fulltext(self, paper_url: str, pdf_url: str | None) -> IngestionResult: ...
      async def close(self) -> None: ...
  ```
  `IngestionResult` contains: `content` (raw HTML/text), `normalized_sections`, `normalized_figures`, `normalized_tables`, `normalized_equations`, `fetch_method`, `source_url`, `quality_assessment`
- `html_fetcher.py` — ar5iv for arXiv papers, direct HTML endpoints for others. Uses httpx + BeautifulSoup. Quality validation: checks section count, heading hierarchy, figure/table extraction success. Returns quality_score (0..1) and quality_warnings. Falls back to `pdf_processor` when quality_score < configurable threshold (default 0.5)
- `pdf_processor.py` — PDF download via httpx + Docling extraction. Extracts structured sections, figures, tables, equations from the Docling document model. Always returns quality assessment for comparison

**Graph adapter** — `libs/adapters/graph/`
- `base.py` — `GraphAdapter` Protocol
  ```python
  @runtime_checkable
  class GraphAdapter(Protocol):
      async def create_graph(self, graph_name: str) -> None: ...
      async def add_node(self, graph_name: str, label: str, properties: dict) -> str: ...
      async def add_edge(self, graph_name: str, from_id: str, to_id: str, label: str, properties: dict) -> str: ...
      async def query_neighbors(self, graph_name: str, node_id: str, edge_labels: list[str] | None, max_depth: int) -> list[GraphNode]: ...
      async def query_path(self, graph_name: str, from_id: str, to_id: str) -> list[GraphPath]: ...
      async def health(self) -> bool: ...
      async def close(self) -> None: ...
  ```
- `age_adapter.py` — Apache AGE via raw SQL through psycopg. One AGE graph per paper (named `paper_{short_id}`). Cypher-over-SQL for traversal queries. `health()` checks if AGE extension is loaded
- `relational_adapter.py` — Fallback implementation using SQL joins + recursive CTEs over `graph_nodes`/`graph_edges` tables. Same Protocol, slower for deep traversal but always available. Used when `AgeGraphAdapter.health()` returns False

**Adapter selection**: `libs/adapters/graph/__init__.py` exposes `get_graph_adapter(db_url) -> GraphAdapter` which probes AGE availability at startup and caches the result. Returns `AgeGraphAdapter` if available, `RelationalGraphAdapter` otherwise. Logs which adapter is active.

**Dependencies** — add to `pyproject.toml`: `docling`, `beautifulsoup4`

---

### Step 3: Core Analysis Logic

**`libs/analysis/`** — new package mirroring `libs/discovery/`

- `ingestion.py` — orchestrates HTML-first → PDF fallback fetch. Calls `IngestionAdapter.fetch_fulltext()`, evaluates quality, retries with PDF if HTML quality is below threshold. Persists result to `ingested_documents` table. Returns the `IngestedDocument` row for downstream operators
- `chunking.py` — structure-aware chunker. Reads from `ingested_documents.normalized_*` fields (never re-fetches). Splits by section/paragraph boundaries. Preserves figure/table/equation chunks with captions and source location metadata. Assigns ordinals and section_paths. Embeds chunks via EmbeddingsRouter (same infra as corpus embeddings). Inserts `paper_chunks` rows
- `graph_extraction.py` — LLM-driven extraction using `ModelRole.paper_analysis`. Processes chunks in batches with semaphore-bounded concurrency (same pattern as `analyze_many` in `libs/discovery/operators/analyze.py`). Extracts typed nodes (concept/method/experiment/dataset/figure/table/equation) and typed relations. Writes to relational `graph_nodes`/`graph_edges` tables. Projects to AGE via `GraphAdapter` (gracefully skipped if AGE unavailable). Stores provenance: which chunks produced each node/edge, extraction model, confidence
- `coverage_check.py` — computes section/figure/table/equation coverage by comparing extracted graph nodes against mentions in `ingested_documents.normalized_*` and chunk content. Identifies unlinked chunks (chunks with no outgoing graph edges). Identifies mentioned-but-unextracted figures/tables. Produces `CoverageDiagnostic` with warnings and overall_score
- `paper_review.py` — LLM-driven review using `ModelRole.paper_review`. Reads analysis packet summary, graph summary, coverage snapshot. Generates strengths, weaknesses, open questions, scores. Advisory only — never treated as canonical evidence source
- `evidence_extraction.py` — LLM-driven evidence extraction using `ModelRole.paper_analysis`. Extracts structured evidence claims from analysis packet + graph nodes. Each EvidenceCard gets an embedding via EmbeddingsRouter. **Contradiction/redundancy detection** (canonical rule): (1) embed the new claim, (2) query `evidence_cards` in the same cycle via pgvector for cosine similarity > 0.7 — this is the sole prefilter gate, (3) for each candidate pair passing the threshold, call LLM (`ModelRole.paper_analysis`) to classify as contradictory/redundant/independent with reasoning and model_confidence, (4) store results as structured `contradiction_flags` on the evidence card. Bounded cost: LLM only called for the embedding-prefiltered set
- `graph_qa.py` — three-stage QA: (1) retrieve top-k relevant chunks via pgvector embedding similarity, (2) expand graph neighbors via `GraphAdapter.query_neighbors()` (works with either AGE or relational adapter), (3) synthesize answer via LLM with full provenance (chunk IDs, graph node IDs, section paths). Locate operations: find where a concept/figure/table appears by querying graph nodes by type+label, returning linked chunks with section_path and ordinal

---

### Step 4: Operators

**`libs/analysis/operators/`** — 6-operator chain:
```
analysis_ingest → analysis_chunk → analysis_graph_extract → analysis_coverage → analysis_review → analysis_evidence
```

- `_common.py` — shared helpers mirroring `libs/discovery/operators/_common.py`:
  - `load_analysis_session(db, session_id) -> AnalysisSession`
  - `append_step_log(session, step, status, detail)`
  - `merge_stats(session, more)`
  - `enqueue_next(db, cycle_id, next_job_type, analysis_session_id) -> UUID`
  - `mark_failed(session, step, error, detail)`
  - `mark_started_if_needed(session)`
  - Uses `analysis_session_id` from job payload (not `session_id`, to avoid confusion with discovery)

- **`ingest.py`** — `analysis_ingest_operator`:
  Load paper card → call `ingestion.fetch_and_persist()` → persist `IngestedDocument` → update session status to "ingested" → emit `analysis.paper_ingested` event (with fetch_method, quality_score, content_hash) → enqueue `analysis_chunk`

- **`chunk.py`** — `analysis_chunk_operator`:
  Load ingested document → run `chunking.chunk_document()` → embed chunks → insert `PaperChunk` rows → update session status to "chunked" → emit `analysis.paper_chunked` event (with chunk_count by type) → enqueue `analysis_graph_extract`

- **`graph_extract.py`** — `analysis_graph_extract_operator`:
  Load chunks → run `graph_extraction.extract_graph()` with LLM → insert `GraphNode`/`GraphEdge` rows → project to AGE if available → update session status to "graph_extracted" → emit `analysis.graph_extracted` event (with node_count, edge_count by type) → enqueue `analysis_coverage`

- **`coverage.py`** — `analysis_coverage_operator`:
  Load chunks + graph + ingested document → run `coverage_check.compute_coverage()` → insert `CoverageDiagnostic` → update session status to "coverage_verified" → emit `analysis.coverage_computed` event (with overall_score, warning_count) → enqueue `analysis_review`

- **`review.py`** — `analysis_review_operator`:
  Load chunks + graph + coverage → create `PaperAnalysisPacket` (via LLM summarization of graph + chunks) → create `PaperReviewArtifact` (via LLM review) → write report artifact to disk (markdown + JSON, same pattern as discovery reports) → update session status to "reviewed" → emit `analysis.review_generated` → enqueue `analysis_evidence`

- **`evidence.py`** — `analysis_evidence_operator`:
  Load analysis packet + graph → run `evidence_extraction.extract_evidence()` with LLM → embed each evidence claim → run contradiction/redundancy detection against existing cycle evidence → insert `EvidenceCard` rows → update `paper_cards.analysis_status` to "analyzed" → update session status to "completed" → emit `analysis.evidence_extracted` event (with card_count, contradiction_count, redundancy_count) → emit `analysis.session_completed` → **terminal** (no next enqueue)

**`__init__.py`** — `register()` function registering all 6 operators
**Registration in `apps/worker/executor.py`** — add `_register_analysis_operators()` following the `_register_discovery_operators()` pattern

---

### Step 5: Service Layer & Skills

**Service** — `libs/core/services/analysis_service.py`
- `start_analysis(db, paper_card_id, cycle_id, charter_id, options)` — validate paper is shortlisted/escalated, create AnalysisSession, enqueue `analysis_ingest` job, transition cycle to `analysis_ready` if not already, emit `analysis.session_started` event
- `get_analysis_session()`, `list_analysis_sessions(charter_id, cycle_id, offset, limit)`
- `get_ingested_document(analysis_session_id)` — for inspecting the persisted full-text
- `get_analysis_packet(paper_card_id)`, `get_review_artifact(paper_card_id)`
- `list_evidence_cards(charter_id, cycle_id, evidence_type, min_confidence, offset, limit)`, `get_evidence_card(evidence_id)`
- `run_qa(db, paper_card_id, question, max_chunks, expand_graph)` — delegates to `graph_qa.answer_question()`
- `run_locate(db, paper_card_id, entity_type, query)` — delegates to `graph_qa.locate_entity()`
- `get_coverage(analysis_session_id)`, `list_chunks(analysis_session_id, chunk_type, offset, limit)`

**Skills** — `skills/analysis/`
- `concept_extraction/skill.md` — guidance for concept/entity extraction: what constitutes a concept node, granularity, when to merge vs split
- `method_extraction/skill.md` — guidance for method characterization: identifying method families, parameter descriptions, baseline comparisons
- `reproducibility_checklist/skill.md` — data availability, code sharing, hyperparameter reporting, compute requirements
- `evidence_synthesis/skill.md` — integrating contradictions, aggregating redundancy, confidence calibration guidance

---

### Step 6: API & CLI

**API router** — `apps/api/routers/analysis.py`

All routes use `@require_scope("cycles.read")` for GET and `@require_scope("cycles.write")` for POST, consistent with existing discovery routes.

```
POST   /papers/{paper_card_id}/analyze          — start analysis (returns AnalysisSessionRead + job_id)
GET    /analysis                                 — list sessions (query: charter_id, cycle_id, status, offset, limit)
GET    /analysis/{session_id}                    — session detail
GET    /analysis/{session_id}/document           — ingested document (normalized full-text artifact)
GET    /analysis/{session_id}/chunks             — list chunks (query: chunk_type, offset, limit)
GET    /analysis/{session_id}/graph/nodes        — list graph nodes (query: node_type, offset, limit)
GET    /analysis/{session_id}/graph/edges        — list graph edges (query: edge_type, offset, limit)
GET    /analysis/{session_id}/coverage           — coverage diagnostic
GET    /papers/{paper_card_id}/analysis-packet   — analysis packet
GET    /papers/{paper_card_id}/review            — review artifact (404 if not yet generated)
POST   /papers/{paper_card_id}/qa               — graph-aware QA (body: QARequest, returns QAResponse)
POST   /papers/{paper_card_id}/locate            — locate entity (body: LocateRequest, returns LocateResponse)
GET    /analysis/{session_id}/report              — analysis report artifact (markdown + JSON, same pattern as discovery report endpoint)
GET    /evidence                                 — list evidence cards (query: charter_id, cycle_id, evidence_type, min_confidence, offset, limit)
GET    /evidence/{evidence_id}                   — single evidence card
```

Analysis events are emitted through the existing domain event system and visible via the existing `GET /events` SSE stream. Orchestrators can filter by `event_type` prefix `analysis.*` to watch analysis progress without polling individual resources.

Register in `apps/api/main.py`.

**CLI** — `apps/cli/commands/analysis.py`
- `analysis run --paper-id <uuid>` — start analysis
- `analysis status --paper-id <uuid>` — check analysis session status
- `analysis list --charter-id <uuid>` — list analysis sessions
- `analysis document --session-id <uuid>` — show ingested document summary
- `analysis qa --paper-id <uuid> --question "..."` — run QA
- `analysis evidence --charter-id <uuid>` — list evidence cards

Register in `apps/cli/main.py`.

---

### Step 7: Frontend

- `apps/web/src/api/analysis.ts` — API client functions for all analysis endpoints
- `apps/web/src/routes/analysis/` — session list + detail routes
- Paper detail page: add "Analyze" button for escalating shortlisted papers (only shown for triage_status "shortlisted" or "escalated")
- Components:
  - `AnalysisStatus.tsx` — status badge + step progress (subscribes to SSE for live updates)
  - `IngestedDocumentView.tsx` — display normalized sections/figures/tables with quality assessment
  - `CoverageDiagram.tsx` — visual coverage diagnostic (section/figure/table bars with missing items highlighted)
  - `GraphViewer.tsx` — simple graph visualization (nodes + edges, filterable by type)
  - `QAPanel.tsx` — question input + answer display with provenance links (clickable chunk refs)
  - `EvidenceCardList.tsx` — evidence card browser with type/confidence/contradiction filters
  - `ReviewArtifact.tsx` — display strengths/weaknesses/questions/scores

---

### Step 8: Tests

**Unit** (`tests/unit/`):
- `test_chunking.py` — structure-aware chunking from normalized sections/figures/tables
- `test_coverage_check.py` — coverage computation with known inputs, edge cases (empty sections, missing figures)
- `test_analysis_schemas.py` — Pydantic validation for all new models
- `test_graph_extraction_schema.py` — node/edge schema validation
- `test_ingestion_quality.py` — quality assessment logic (threshold-based HTML rejection, fallback triggering)
- `test_evidence_contradiction.py` — pre-filtering logic (cosine similarity gating), contradiction flag structure

**Integration** (`tests/integration/`):
- `test_analysis_operators.py` — full 6-operator chain with mocked LLM and mocked HTTP fetch. Verify each operator emits correct events and enqueues next job
- `test_graph_adapter_age.py` — AGE adapter against test Postgres (skipped if AGE unavailable via `pytest.mark.skipif`)
- `test_graph_adapter_relational.py` — relational fallback adapter against test Postgres (always runs)
- `test_analysis_api.py` — endpoint integration tests for all analysis routes
- `test_ingestion_html_fallback.py` — HTML fetch succeeds; HTML fetch returns poor quality → triggers PDF fallback; HTML unavailable → PDF fallback; both fail → session marked failed. Uses mocked httpx responses
- `test_qa_provenance.py` — QA returns answer with chunk IDs and graph node IDs that actually exist in the DB; locate returns correct section_path and ordinal

**Fixtures** (`tests/fixtures/`):
- `sample_paper.html` — well-structured ar5iv HTML with sections, figures, tables, equations
- `sample_paper_degraded.html` — poorly structured HTML (missing headings, broken tables) that should trigger PDF fallback
- `sample_paper_chunks.json` — pre-computed chunks for testing downstream operators without running chunker
- `sample_graph.json` — pre-computed graph nodes/edges for testing coverage and QA
- `sample_evidence_pairs.json` — pairs of evidence claims with expected contradiction/redundancy classifications

---

## Key Files to Modify

| File | Change |
|------|--------|
| `libs/storage/models/papers.py` | Add `analysis_status` column |
| `libs/storage/models/__init__.py` | Import new analysis models |
| `libs/schemas/papers.py` | Add `analysis_status` to PaperCardRead |
| `libs/core/state_machine.py` | Allow `analysis_ready → analysis_ready` |
| `libs/core/event_types.py` | Add `AnalysisEvents` enum |
| `apps/worker/executor.py` | Add `_register_analysis_operators()` |
| `apps/api/main.py` | Register analysis router |
| `apps/cli/main.py` | Register analysis commands |
| `docker/init-extensions.sql` | Uncomment AGE (kept conditional) |
| `pyproject.toml` | Add docling, beautifulsoup4 |

## Key Patterns to Reuse

| Pattern | Source |
|---------|--------|
| Operator handler signature | `libs/core/operators.py` (OperatorInput → OperatorResult) |
| Operator common helpers | `libs/discovery/operators/_common.py` |
| Operator registration | `libs/discovery/operators/__init__.py` |
| Adapter Protocol pattern | `libs/adapters/sources/base.py`, `libs/adapters/llm/base.py` |
| LLM structured output | `LLMAdapter.complete_structured()` via ModelRouter |
| Embedding calls | `EmbeddingsRouter` in `libs/adapters/embeddings/router.py` |
| Pydantic schema style | `libs/schemas/discovery.py` |
| SQLAlchemy model style | `libs/storage/models/papers.py` |
| API router + scope auth | `apps/api/routers/discovery.py` |
| CLI command style | `apps/cli/commands/discovery.py` |
| Skill package format | `skills/literature/problem_scoping/skill.md` |
| Report artifact writing | `libs/discovery/operators/finalize.py` (markdown + JSON to disk) |
| Event emission | `libs/core/events.py` (`emit_event_sync()`) |
| SSE event stream | `apps/api/routers/events.py` (existing, reused by analysis events) |

## Build Order

1. **Schema + Migration** (Step 1) — everything else depends on this
2. **Adapters** (Step 2) — ingestion + graph adapters needed by operators
3. **Core logic** (Step 3) — ingestion, chunking, extraction, coverage, review, evidence, QA modules
4. **Operators** (Step 4) — the 6-operator pipeline chain
5. **Service + Skills** (Step 5) — service layer wiring + skill packages
6. **API + CLI** (Step 6) — external interfaces
7. **Frontend** (Step 7) — UI
8. **Tests** (Step 8) — written alongside each step, bulk integration/e2e at end

## Verification

1. Run migration: `alembic upgrade head` — verify all 9 tables created; AGE enabled if available, migration succeeds even if not
2. Start analysis on a shortlisted paper via CLI: `synthetos analysis run --paper-id <uuid>`
3. Watch worker logs for the 6-operator chain completing; verify each emits its domain event
4. Check SSE stream: `GET /api/v1/events?event_type=analysis.*` shows all analysis events with correct payloads
5. Check ingested document: `GET /api/v1/analysis/{session_id}/document` returns normalized sections, quality assessment
6. Check chunks: `GET /api/v1/analysis/{session_id}/chunks` returns structured chunks with section_paths
7. Check graph nodes: `GET /api/v1/analysis/{session_id}/graph/nodes` returns typed nodes with provenance
8. Check coverage: `GET /api/v1/analysis/{session_id}/coverage` shows diagnostic with overall_score
9. Check analysis packet: `GET /api/v1/papers/{id}/analysis-packet` returns full analysis with graph_summary
10. Check review: `GET /api/v1/papers/{id}/review` returns advisory review with scores
11. Run QA: `POST /api/v1/papers/{id}/qa` with question — verify answer includes chunk IDs and graph node IDs that exist in DB
12. Run locate: `POST /api/v1/papers/{id}/locate` with entity query — verify section_path and ordinal in response
13. Check evidence: `GET /api/v1/evidence?charter_id=<uuid>` returns evidence cards with contradiction_flags populated
14. Test HTML fallback: analyze a paper where HTML is unavailable — verify PDF+Docling path succeeds and fetch_method = "pdf_docling"
15. Test AGE fallback: stop AGE extension — verify graph QA still works via relational adapter
16. Run `uv run pytest tests/unit/ tests/integration/` — all pass
