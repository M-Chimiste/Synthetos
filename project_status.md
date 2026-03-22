# Project Status

**Product:** ML Laboratory Co-Scientist
**Last Updated:** 2026-03-22

---

## Phase Status

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 0 — Foundation | Complete | Repo skeleton, Postgres schemas, state machine, operator contract, model gateway, skill loader, event stream, API spine |
| Phase 1 — Literature Intake | Complete | Research charter, arXiv metadata adapter, internal corpus adapter, title+abstract triage, shortlist ranking, fulltext escalation, literature reports |
| Phase 2 — Evidence & Hypotheses | Complete | Evidence extraction, hypothesis generation/critique, protocol compilation, experiment specs |
| Phase 3 — Execution Lab MVP | Complete | Git worktree isolation, Docker container execution with GPU support, run telemetry streaming (SSE), pause/cancel/retry controls, automation policy, artifact collection, failure classification, 3 Phase 3 skills, run API endpoints |
| Phase 4 — Verification | Not started | |
| Phase 5 — Pilot Hardening | Not started | |

---

## What Was Done (Phase 3)

- `run_records` and `run_telemetry_events` database tables (migration `20260322_000005`)
- 4-operator pipeline: `run_prepare` → `run_execute` → `run_finalize` → `run_retry_repair`
- `DockerContainerAdapter` with network isolation, resource limits, GPU passthrough, timeout enforcement
- `GitWorktreeAdapter` with per-run worktree creation, patch archives, and cleanup
- Execution policy evaluation from `configs/policies/default.yaml`
- Execution profiles and approved images in `configs/execution/`
- SSE telemetry streaming with Last-Event-ID checkpoint
- Run control API: create, list, get, command (pause/cancel/retry), telemetry stream
- Artifact collection and failure classification (OOM, dependency, runtime exception, timeout, etc.)
- 3 skills: `experiment_patch_author`, `experiment_repair`, `run_evaluator`
- Skill lineage tracking in run records
- Integration and unit tests for the full pipeline

## What Needs To Be Done Next (Phase 4)

- Verification subsystem: deterministic checks for every experiment run
- Baseline comparison and historical comparison against prior internal work
- Structured `FailurePostmortem` generation from failed/rejected runs
- Verification reports and cycle summary reports
- Postmortem and verification-summary skills
- API endpoints for verification reports and postmortems
