# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ML Laboratory Co-Scientist** — a local-first, single-user system for running end-to-end ML research loops. The system helps researchers define problems, triage literature, generate experiment ideas, execute code locally, verify results, and prepare submissions (Kaggle focus for MVP).

The project is currently in **design/pre-implementation phase**. No source code exists yet — the repository contains planning documents in `project_docs/`.

## Key Design Documents

- `project_docs/co-scientist_prd.md` — Product requirements, MVP scope, success metrics
- `project_docs/co-scientist_system_patterns.md` — Architecture baseline, system patterns, tech stack decisions
- `project_docs/phased_implementation_plan.md` — 6-phase delivery roadmap (Phase 0-5)
- `project_docs/m-chimiste-arxiv-harvester-example.txt` — Reference example for arXiv metadata harvesting

## Architecture (Three Core Loops)

1. **Explore** — Problem intake → metadata-first literature screening → evidence synthesis → ranked hypothesis portfolio
2. **Experiment** — Hypothesis → ExperimentSpec → code generation → containerized local execution
3. **Verify** — Result verification → historical comparison → failure memory → human-readable report

### Critical Architectural Decisions

- **Operator-over-shared-state**, not agent-to-agent messaging. Typed operators read/write a shared `ResearchState` — no hidden prompt history as memory.
- **State machine orchestration** with explicit transitions and append-only audit trail (not freeform conversational workflow).
- **Metadata-first literature triage**: title+abstract screening before full text. For arXiv, prefer HTML over PDF.
- **Task-scoped context assembly**: operators receive only relevant evidence/data, not entire project state.
- **Portfolio search**: maintain ranked hypothesis portfolio, not greedy single-path.
- **Hexagonal architecture**: all external systems (arXiv, models, datasets, git, containers) behind adapter interfaces.
- **Containerized execution**: generated code runs in GPU-capable Docker containers with resource limits, not on the host.

### Planned Tech Stack (MVP)

- Python (primary), FastAPI for API/control plane
- PostgreSQL + pgvector for state, vector search, and job queue
- Local filesystem for artifact storage
- Git worktrees for experiment isolation
- Docker with GPU passthrough for sandboxed execution
- Local web dashboard + CLI for UI

### Core Data Model Entities

`ResearchCharter`, `ResearchState`, `PaperCard`, `EvidenceCard`, `HypothesisCard`, `ExperimentSpec`, `RunRecord`, `VerificationReport`, `FailurePostmortem`, `ReportBundle`, `ApprovalEvent`

## Environment

- Credentials in `.env` (gitignored) — includes Kaggle API keys
- Sensitive files gitignored: `config/creds.json`, `client_secret.json`, `.env*`
- Large directories gitignored: `models/`, `data/`, `database/`, `temp_data/`
