# Project Status

**Product:** ML Laboratory Co-Scientist
**Repository:** `Synthetos`
**Last Updated:** 2026-03-23
**Overall Status:** Phase 5.1 complete, Phase 5.2 not started

---

## Phase Status

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 0 — Foundation | Complete | Repo skeleton, Postgres schemas, state machine, operator contract, model gateway, skill loader, event stream, API spine |
| Phase 1 — Literature Intake | Complete | Research charter, arXiv metadata adapter, internal corpus adapter, title+abstract triage, shortlist ranking, fulltext escalation, literature reports |
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
- Full API coverage: cycles, runs, reports, skills, verification, timeline, literature, evidence, hypotheses, health
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
- End-to-end usage validation from external orchestrator harness
- Run a real local Docker smoke test for the offline benchmark on `cpu-small`
- Validate optional `gpu-small` behavior on a machine with GPU runtime support
