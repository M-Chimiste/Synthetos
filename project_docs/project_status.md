# Project Status

**Product:** ML Laboratory Co-Scientist
**Repository:** `Synthetos`
**Last Updated:** 2026-03-24
**Overall Status:** Phase B (Directional Signal) complete, Phase 5.2 in progress

---

## Phase Status

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 0 — Foundation | Complete | Repo skeleton, Postgres schemas, state machine, operator contract, model gateway, skill loader, event stream, API spine |
| Phase 1 — Literature Intake | Complete | Research charter, internal corpus adapter, title+abstract triage, shortlist ranking, fulltext escalation, literature reports, plus canonical arXiv warehouse + hybrid semantic search |
| Phase 2 — Evidence & Hypotheses | Complete | Evidence extraction, hypothesis generation/critique, protocol compilation, experiment specs |
| Phase 3 — Execution Lab MVP | Complete | Git worktree isolation, Docker container execution with GPU support, run telemetry streaming (SSE), pause/cancel/retry controls, automation policy, artifact collection, failure classification, 3 Phase 3 skills, run API endpoints |
| Phase 4 — Verification | Complete | Same-charter history, policy-driven checks, output-contract validation, next-step recommendations, cycle verification summaries, failure-memory feedback loops, web UI visibility |
| Phase 5.1 — Hardening | Complete | Policy/skill validation, recovery/resume flows, report quality/timeline, API contract tests, frontend tests, skill library, orchestrator SDK |
| Phase 5.2 — Pilot Exercises | Not started | |

---

## What Was Done (Phase 5.1)

### WI-3: Policy defaults & skill validation
- `SkillManifest.validate_against_registry()` with semver, phase, operator, and ID validation
- `ValidationIssue` model with severity/code/message/field
- `libs/skills/dependencies.py` for `requires`/`conflicts_with` checking
- Hook export validation against known hook names
- Strict mode for `load_all_skills()` — raises on error-severity issues
- Policy defaults tightened: `max_retry_attempts: 3`, `max_concurrent_runs: 2`, `lease_timeout_minutes: 5`, `skills.validation_mode: strict`
- `PolicyConfig` typed model with `from_raw()` and `validate_policy()`
- Max retry enforcement in `apply_run_command()` retry branch
- 32 new tests

### WI-1: Recovery & resume flows
- `RESUMING` state added to cycle state machine with transitions from PAUSED/FAILED
- Checkpoint columns on `research_cycles`: `last_completed_operator`, `last_completed_job_id`, `resume_payload` (migration `20260323_000008`)
- Per-operator checkpoint recording in worker after each successful job
- `next_operator_after()` pipeline logic for resume from checkpoint
- `resume` command added to `apply_run_command()` with checkpoint-aware next-operator selection
- `RunCommandRequest` updated to accept `"resume"` command
- `reclaim_expired_leases()` now marks active cycles as FAILED on lease expiry
- `claim_next_job()` accepts configurable `lease_minutes` parameter
- `TRANSIENT_FAILURES` set defined in `libs/execution/`
- `OPERATOR_PIPELINES` maps for explore/ideation/execution/verification sequences
- 25 new tests

### WI-2: Report quality & timeline views
- Real Jinja2 templates for `cycle_summary`, `run_summary`, `evidence_summary` in `prompts/reporting/v1/`
- `libs/reporting/scoring.py`: structural quality scoring (section checklist, word count, table/metric detection)
- `quality_metadata` column on `report_bundles` (migration `20260323_000009`)
- `create_report()` now auto-scores and stores quality metadata
- `GET /api/v1/cycles/{id}/timeline` endpoint with categorized event entries
- `TimelineEntry` and `TimelineResponse` schemas
- `get_cycle_timeline()` service function with event categorization
- `Timeline.tsx` component with category icons, colors, filtering
- `ReportViewer.tsx` component with quality badge and section checklist
- TypeScript types updated for timeline and quality metadata
- API client updated with `getTimeline()` and `"resume"` command support
- 11 new tests

### WI-4: API contract & compatibility tests
- OpenAPI schema snapshot test with baseline diffing (detects removed endpoints, dropped required fields)
- Endpoint roundtrip tests for cycles, skills, reports, timeline, health
- `tests/helpers/schema_validators.py` with `validate_response()` and `validate_list_response()`
- Backward compatibility test (additive changes safe, removals caught)
- `pytest-cov` added to dev dependencies
- OpenAPI baseline committed at `tests/fixtures/openapi_baseline.json`
- 9 new tests

### WI-5: Frontend interaction tests
- vitest + @testing-library/react + jsdom set up for web app
- Phase 4 test fixtures for timeline entries and report details
- `Timeline.test.tsx`: rendering, filtering, empty state, timestamps (6 tests)
- `ReportViewer.test.tsx`: title, quality badge, markdown rendering, section checklist, missing metadata (6 tests)
- 12 new frontend tests

### WI-6: Skill library & documentation
- 2 example skills: `custom_metric_checker` (with hooks.py) and `data_profiler`
- `scripts/generate_skill_catalog.py`: generates `docs/skills/catalog.md` + per-skill detail pages
- `docs/skills/authoring-guide.md`: manifest schema, hook contract, validation rules, testing guide
- `tests/helpers/skill_test_utils.py`: `load_and_validate_skill()`, `assert_skill_binds_to()`
- Integration tests: strict load of all 15 skills, dependency validation, phase coverage, example validation
- 4 new tests

### WI-7: Orchestrator client SDK
- `libs/sdk/` package with sync `SynthetoClient` and async `AsyncSynthetoClient`
- Core non-streaming API coverage: cycles, runs, reports, skills, verification, timeline, literature, evidence, hypotheses, health
- Admin endpoints and SSE streaming endpoints are not wrapped by the SDK in Phase 5.1
- Error mapping: `SynthetoAPIError`, `SynthetoAuthError`, `SynthetoNotFoundError`, `SynthetoValidationError`
- `docs/sdk/quickstart.md` and `docs/sdk/examples/run_full_cycle.py`
- SDK e2e integration test: create cycle, list, get timeline, health — all via SDK against TestClient
- 22 new tests

### Test summary
- Backend: 259 tests passing (up from 156)
- Frontend: 12 tests passing (new)
- Ruff: clean
- All first-party skills (15) pass strict validation

---

## What Was Done (Current Session)

### Phase B — Directional Signal Evaluation
- New `DirectionalSignal` enum (advancing/stalled/regressing/noisy/breakthrough) — separate from `VerificationOutcome`, answering "is this hypothesis making progress?" vs "is this run valid?"
- `libs/verification/trend.py`: pure-function trend analysis module
  - `compute_metric_series()` — builds time-ordered metric series from prior runs + current
  - `classify_direction()` — classifies trend using relative deltas, stall detection, noise detection, breakthrough detection
  - `compute_frontier()` — tracks running best value and runs since last improvement
  - `reconcile_signals()` — multi-metric reconciliation, detects conflicts between primary and constraint metrics
- `libs/verification/self_critic.py`: fast LLM pre-check before full verification
  - Uses `critic` model route with low max_tokens (256)
  - Catches: random-chance metrics, perfect scores, unconverged training, missing metrics
  - Fail-open on LLM failure (returns passed=True)
- `SuccessCriteria` and `ConstraintMetric` Pydantic models for typed access to charter `success_criteria` JSON
- `MetricFrontierModel` table (migration `20260324_000013`) — one row per (hypothesis, metric) pair tracking best value and stall count
- New columns on `VerificationReportModel`: `directional_signal`, `directional_signal_detail`, `self_critic_result`
- New columns on `ReportBundleModel`: `run_record_id`, `hypothesis_card_id` for experiment writeup linkage
- `upsert_metric_frontier()` service function with proper upsert semantics
- `run_verify_operator` integration: self-critic → trend analysis → frontier update → outcome determination
- Signal-aware recommendations: `intensify_approach`, `stall_alert`, `regression_warning`, `noise_alert`, `breakthrough_flag`
- Per-experiment writeup generated in `verification_report_operator` as `ReportBundle(report_type="experiment_writeup")`
- Added missing `verifier` model route to `configs/models/routes.yaml`
- Prompt updates: `verification_review.md` now includes directional signal and self-critic context
- New prompts: `self_critic_precheck.md`, `metric_conflict_resolution.md`
- Policy defaults: `self_critic_enabled`, `default_significance_threshold`, `default_stall_window`
- 40 new tests across `test_trend.py` (22), `test_self_critic.py` (5), `test_frontier.py` (5), `test_verification_checks.py` (5 new signal recommendation tests), plus `MetricFrontier` Pydantic + model tests

### Phase A remediation correction pass (Codex)
- Fixed failure classification precedence so dependency/import errors now resolve to `dependency_failure` before generic `runtime_exception`
- Extended `RemediationResponse` with `run_mutations` and applied validated run-level retry changes for:
  - `execution_profile`
  - `timeout_seconds`
  - `memory_limit_mb`
  - `cpu_limit`
  - `gpu_enabled`
- `auto_remediate_operator` now routes retries to:
  - `run_prepare` when `spec_mutations` require harness restaging
  - `run_execute` when the existing workspace can be retried directly
- `build_run_spec()` now preserves remediation-added `build_recipe` entries across re-prepare, and staged `run_config.json` now includes `stop_conditions` and `estimated_runtime_minutes`
- Docker execution now honors `build_recipe.pip_packages` by bootstrapping Python dependency installs before the experiment command runs
- Failure-memory helpers no longer suppress postmortems based on `RunRecordModel.is_remediated_run`; unsuccessful remediation chains still contribute to caution/ranking
- `RunDetailResponse` now exposes ordered `remediation_actions` lineage, and frontend TypeScript run-detail types were updated to match
- Worker state handling for remediation retries was fixed so `run_execute` transitions correctly from queued/ready flows and from already-running retry loops
- OpenAPI baseline refreshed to include the additive run-detail remediation lineage field
- Added/updated 57 targeted backend tests covering:
  - dependency classification precedence
  - Docker dependency bootstrap
  - run/spec mutation application
  - retry routing (`run_prepare` vs `run_execute`)
  - remediation lineage ordering in run detail
  - end-to-end dependency and timeout remediation flows
- Targeted Phase A verification passed:
  - `uv run pytest tests/unit/test_execution_runtime.py tests/unit/test_remediation.py tests/integration/test_phase4_api.py tests/integration/test_api_contract.py -q`
  - `uv run ruff check libs apps tests`

### Semantic arXiv warehouse + hybrid search (Codex)
- Added canonical `arxiv_papers` warehouse table and `arxiv_sync_runs` tracking table (migration `20260323_000010`)
- Added Postgres pgvector/HNSW and full-text search index creation through Alembic for semantic paper search
- Added local embedding adapter using Sentence Transformers with `Alibaba-NLP/gte-modernbert-base`
- Added dedicated embedding config at `configs/models/embeddings.yaml` and related env/config plumbing
- Added warehouse service for:
  - one-time Kaggle snapshot bootstrap
  - incremental OAI-PMH delta sync
  - deduplicated upsert by `arxiv_id`
  - re-embedding only when title/abstract content changes
  - hybrid lexical + vector search
- Added global paper search API endpoint: `GET /api/v1/papers/search`
- Added CLI commands:
  - `synthetos papers search`
  - `synthetos papers sync-arxiv`
- Updated literature intake so the arXiv branch now:
  - ensures warehouse freshness
  - runs warehouse-backed hybrid search
  - imports hits into cycle `paper_cards`
  - preserves the existing LLM screening / shortlist / escalation flow
- Updated bootstrap to run Alembic cleanly for Postgres-backed semantic search setup

### Warehouse hardening (6 gaps addressed)
1. **Retry logic**: Added tenacity `@retry` to OAI-PMH `_do_request()` (3 attempts, exponential backoff 3-30s, respects arXiv rate limit). Safe wrapper `_request()` catches `RetryError` and returns `None`.
2. **Multi-category queries**: Extracted `_harvest_category()` method. Multi-category queries harvest each category separately and deduplicate by `external_id`.
3. **Date validation**: Changed `/papers/search` params from `str | None` to `datetime | None` — FastAPI auto-returns 422 on invalid dates instead of 500.
4. **Embedding warmup**: Added `warmup()` and `is_available()` to `EmbeddingAdapter` ABC. `SentenceTransformerEmbeddingAdapter` logs warnings when downloading model. Added `synthetos embeddings warmup` CLI command.
5. **Background sync**: New `arxiv_warehouse_sync` cycle-independent operator + `CYCLE_INDEPENDENT_OPERATORS` set in worker. CLI `papers sync-arxiv --background` enqueues a job instead of blocking.
6. **Postgres integration tests**: 5 tests in `test_arxiv_warehouse_pg.py` covering FTS, vector cosine, hybrid search, category jsonb filter, and date range filter. Auto-skip when testcontainers/Docker unavailable.

### Phase 5.1 gap closure
- Fixed run resume to use run-scoped checkpoints instead of cycle-scoped checkpoints
- Added run checkpoint columns on `run_records` via migration `20260323_000011`
- Updated worker resume snapshots and checkpoint writes to preserve cycle auditability while using run checkpoints for run recovery
- Fixed `GET /api/v1/reports/{report_id}` to return the stored `quality_metadata` field already declared by the API schema and frontend types
- Corrected SDK/status docs to describe the current SDK surface as core non-streaming coverage, excluding admin and SSE endpoints
- Added regression coverage for run-scoped resume behavior and report detail quality metadata

### Phase A — Auto-Remediation Layer
- New `auto_remediate_operator` in verification pipeline: LLM-assisted failure diagnosis and fix before postmortem
- Two-mode prompt system: focused prompts for known failure classes (dependency, runtime, metric parse, artifact output), full debug prompts for unknown failures and escalation after focused fix fails
- `RemediationActionModel` table (migration `20260324_000012`): append-only log of every remediation attempt with full lineage (diagnosis, fix type, fix payload, prior attempts)
- New columns on `RunRecordModel`: `remediation_count` (attempt budget tracking), `is_remediated_run` (observability flag for remediated retry history)
- `RemediationPolicyConfig` in `libs/core/policy.py`: configurable max attempts, failure class routing, stderr/code truncation limits
- `libs/execution/debug.py`: LLM prompt rendering, debugger call, `RemediationResponse` parsing, and `run_mutations`
- `libs/execution/remediation.py`: fix primitives (code patching, dependency adds, env changes, run mutations, spec mutations), run retry preparation, prior attempts summary
- Prompt templates: `prompts/remediation/v1/focused_fix.md` and `prompts/remediation/v1/full_debug.md` (Jinja2, failure-class-specific instructions)
- `debugger` model route added to `configs/models/routes.yaml`
- `remediation` policy section added to `configs/policies/default.yaml`
- Pipeline integration: `run_verify_operator` now routes to `auto_remediate` when remediation is enabled and budget remains, falling through to `failure_postmortem` when exhausted or on LLM call failure
- Remediation loop via operator chaining: `auto_remediate → (run_prepare or run_execute) → run_finalize → run_verify → [auto_remediate or failure_postmortem]`
- Belt-and-suspenders budget check in both `run_verify_operator` and `auto_remediate_operator`
- Failure memory now treats successful remediation as an implicit exclusion by the absence of postmortems; failed remediation chains still count
- `RemediationAction` Pydantic schema added to `libs/schemas/domain.py`, and run detail now exposes remediation lineage through the API
- 57 targeted Phase A correction tests passing across unit and integration coverage

### Test summary
- Backend: 347 tests passing (up from 259 after Phase B additions)
- Ruff: clean
- Postgres integration tests: ready to run when Docker is available

---

## What Was Done (Phase 4)

- 3-operator verification pipeline, policy-driven checks, output-contract validation
- Historical comparison, failure-memory feedback, next-step recommendations
- 6 new API endpoints, verification/postmortem UI, prompt templates, skills
- Full details in prior session notes

---

## What Was Done (Phase 3)

- Git worktree isolation, Docker container execution, run telemetry SSE
- Pause/cancel/retry controls, automation policy, artifact collection, failure classification
- Full details in prior session notes

---

## What Needs To Be Done Next (Phase 5.2)

- Pilot exercises on public ML benchmark tasks and internal research problems
- Run `uv sync` in a network-enabled environment so the new `sentence-transformers` / `kaggle` dependencies are locked and installed consistently
- Execute the first real Postgres-backed full Kaggle bootstrap and incremental OAI sync against a local database
- Pull `pgvector/pgvector:pg16` Docker image and run Postgres integration tests (`uv run pytest tests/integration/test_arxiv_warehouse_pg.py -v -m integration`)
- End-to-end usage validation from external orchestrator harness
- Run a real local Docker smoke test for the offline benchmark on `cpu-small`
- Validate optional `gpu-small` behavior on a machine with GPU runtime support
- Run the full backend/frontend test suite after the Phase A remediation correction pass for an updated project-wide count
