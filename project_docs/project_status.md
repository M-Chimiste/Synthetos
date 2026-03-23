# Project Status

**Product:** ML Laboratory Co-Scientist
**Repository:** `Synthetos`
**Last Updated:** 2026-03-23
**Overall Status:** Phase 4 complete, Phase 5 not started

---

## Phase Status

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 0 — Foundation | Complete | Repo skeleton, Postgres schemas, state machine, operator contract, model gateway, skill loader, event stream, API spine |
| Phase 1 — Literature Intake | Complete | Research charter, arXiv metadata adapter, internal corpus adapter, title+abstract triage, shortlist ranking, fulltext escalation, literature reports |
| Phase 2 — Evidence & Hypotheses | Complete | Evidence extraction, hypothesis generation/critique, protocol compilation, experiment specs |
| Phase 3 — Execution Lab MVP | Complete | Git worktree isolation, Docker container execution with GPU support, run telemetry streaming (SSE), pause/cancel/retry controls, automation policy, artifact collection, failure classification, 3 Phase 3 skills, run API endpoints |
| Phase 4 — Verification | Complete | Verification repaired to plan: same-charter history, policy-driven checks, output-contract validation, next-step recommendations, cycle verification summaries, failure-memory feedback loops, and web UI visibility |
| Phase 5 — Pilot Hardening | Not started | |

---

## What Was Done (Phase 4)

- `verification_reports` and `failure_postmortems` database tables (migration `20260323_000006`)
- `output_contract_checks` column added to `verification_reports` (migration `20260323_000007`)
- `verification_outcome` column added to `run_records` for denormalized fast queries
- `VERIFYING` cycle status added to state machine with proper transitions
- 3-operator verification pipeline: `run_verify` → `failure_postmortem` (conditional) → `verification_report`
- `run_finalize` now auto-chains into `run_verify` via `next_actions`
- Deterministic verification checks module (`libs/verification/`):
  - Artifact presence and parseability checks
  - Metric sanity checks (NaN, bounds, presence)
  - Baseline comparison against declared metrics
  - Leakage signal detection (perfect metrics, suspicious train/val gaps)
  - Split validation (intended vs actual evaluation split)
  - Output-contract validation against declared `ExperimentSpec.expected_outputs`
  - Historical comparison against prior same-charter runs plus related verification/postmortem memory
  - Outcome determination: robust / tentative / rejected / invalid
- Verification is now policy-driven:
  - baseline/history requirements can block `robust`
  - leakage and split checks can be toggled by policy
  - auto-postmortem behavior respects policy
  - rerun / replay notes are generated deterministically
- LLM-enhanced review summaries via `verifier` model role
- Structured `FailurePostmortem` generation with root cause analysis, remediation suggestions, retrieval hints, and protocol update hints
- Similar prior failure matching now spans same-charter history
- Verification summary reports via `reporter` model role
- Cycle-level verification summary report bundles are generated after verification completion
- Failure-memory guidance now feeds back into:
  - literature source retrieval context
  - hypothesis portfolio ranking penalties/rationales
  - structured next-step recommendations
- 3 Jinja2 prompt templates in `prompts/verification/v1/`
- 2 new skills: `postmortem_reflection`, `verification_summary`
- Updated `run_evaluator` skill to support `run_verify` operator
- 6 new API endpoints:
  - `GET /api/v1/cycles/{id}/verification` — aggregate verification summary
  - `GET /api/v1/cycles/{id}/verification-reports` — list verification reports
  - `GET /api/v1/verification-reports/{id}` — verification report detail
  - `GET /api/v1/cycles/{id}/postmortems` — list postmortems
  - `GET /api/v1/postmortems/{id}` — postmortem detail
  - `GET /api/v1/runs/{id}/historical-comparison` — historical comparison
- `RunDetailResponse` includes `verification_report` and `postmortem` summaries
- Verification summary responses now include:
  - next-step recommendations
  - latest cycle summary report bundle ID
- Historical comparison responses now include:
  - same-charter comparison scope metadata
  - memory references used from prior verification reports and postmortems
- Verification policy section in `configs/policies/default.yaml`
- Web UI now shows:
  - cycle-level verification counts and recommendations
  - run-level verification outcome, baseline/history context, postmortem details, and report links
  - Phase 4-aware control tower copy and API bindings
- Pydantic / TypeScript schemas updated for verification summaries, historical comparison memory refs, output-contract checks, and run verification state
- Test coverage added for:
  - output-contract validation
  - same-charter historical comparison
  - recommendation generation
  - failure-memory portfolio penalties
  - cross-cycle verification history
  - policy-driven postmortem skipping
- Full test suite passing: 156 tests

---

## What Was Done (Phase 3)

### Domain, storage, and config

- Added Phase 3 domain and API schemas for `RunSpec`, `RunRecord`, `RunTelemetryEvent`, `RunArtifactManifest`, and run control requests/responses
- Added `run_records` and `run_telemetry_events` storage models plus Alembic migration `20260322_000005_phase3_runs.py`
- Extended lineage tables so skill execution and model invocation rows can reference runs
- Added committed execution config under:
  - `configs/execution/images.yaml`
  - `configs/execution/profiles.yaml`
  - `configs/execution/settings.yaml`
- Extended policy config with execution auto-run and force-start rules
- Added `RUNNING` to the cycle state machine

### Execution backplane and harness

- Added `libs/adapters/git/` for per-run git worktrees and patch archive capture
- Added `libs/adapters/container/` for Docker command construction and container execution
- Added `libs/execution/` for:
  - execution policy evaluation
  - harness staging
  - run-spec construction
  - artifact collection and failure classification
- Added the first offline benchmark harness under `libs/execution/templates/offline_baseline/`
- Added a checked-in fixture dataset and a compact local training/evaluation script that emits:
  - `metrics.json`
  - `artifact_manifest.json`
  - checkpoint output
  - predictions output

### Run orchestration and control plane

- Added Phase 3 operators:
  - `run_prepare`
  - `run_execute`
  - `run_finalize`
  - `run_retry_repair`
- Added API endpoints for:
  - cycle run listing
  - run detail
  - run creation from experiment specs
  - run commands (`pause`, `cancel`, `retry`)
  - run telemetry SSE
- Added CLI commands for run list/show/start/pause/cancel/retry
- Extended the web UI with:
  - run queue panel
  - current run summary
  - live run telemetry panel
  - run control buttons
  - run launch actions from `ExperimentSpec` cards

### Phase 3 skills and reporting

- Added Phase 3 skills:
  - `coding.experiment_patch_author`
  - `coding.experiment_repair`
  - `verification.run_evaluator`
- Added Phase 3 prompt assets under `prompts/coding/v1/`
- Run preparation/finalization now records run-bound skill lineage
- Run reports are now associated back to the originating run for inspection through the API/UI

### Phase 3 verification status

- 118/118 tests passed at Phase 3 completion
- Real Docker-backed and live GPU smoke runs not yet executed (deferred to Phase 5 pilot)

---

## What Needs To Be Done Next (Phase 5)

- Pilot exercises on public ML benchmark tasks and internal research problems
- Improve recovery behavior and resume flows
- Improve report quality and timeline views
- Tighten policy defaults and skill validation
- Add API contract and compatibility tests
- Add dedicated frontend interaction tests for Phase 4 views (current coverage is build/type + backend/integration heavy)
- Publish first-party skill library with documentation
- Simple orchestrator client SDK
- End-to-end usage validation from external orchestrator harness
- Run a real local Docker smoke test for the offline benchmark on `cpu-small`
- Validate optional `gpu-small` behavior on a machine with GPU runtime support
