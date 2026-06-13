# Project status

_Last updated: 2026-06-13T22:41:46Z_

## Current focus

Full automated-scientist stabilization for the
`diffusionblocks_e2e` pilot. The immediate goal is to keep the real
discovery -> analysis -> ideation -> protocol -> execution -> verification
chain moving under workstation conditions, with durable status visibility and
clear handoffs between phases.

## Current live run

- Pilot cycle: `019ec2f4-bfa9-7702-b6e0-c6634374045d`
- Charter: `pilot:diffusionblocks_e2e`
- Goal attached by repair: `019ec321-7959-7243-8cf5-66c6bb5add62`
- Current cycle state: `analysis_ready`
- Active job at last check: `analysis_graph_extract`
- Worker log: `.dev/logs/worker-diffusionblocks-full-019ec2f4-bfa9.log`
- Human-readable status command:

```bash
scripts/scientist-status.sh 019ec2f4-bfa9-7702-b6e0-c6634374045d
```

The run is no longer stuck at discovery. It advanced through `goal_advance`,
started analysis, ingested the target paper from ar5iv HTML, chunked 500
chunks, and is running graph extraction. One historical
`analysis_graph_extract` job is failed because it was deliberately cancelled
after it was found to be using an unavailable model alias.

## Recently shipped

### Automated scientist handoff repair (2026-06-13)

Root cause: pilot cycles were launched with `cycle.config["pilot"]`, but no
`cycle.config["goal"]["goal_id"]`. The worker's success hook only enqueues
`goal_advance` after terminal phase jobs when a goal id exists, so
`discovery_finalize` completed successfully and then the autonomous pilot had
no next job to claim.

Fixed in:

- [libs/pilot/runner.py](../libs/pilot/runner.py)
  - Pilot launch now creates a `ResearchGoal` and first `GoalAttempt`.
  - The existing pilot cycle is tagged with `cycle.config["goal"]`.
  - Fixture expectations are translated into deterministic goal criteria:
    completed run, accepted verification verdict, reference metrics, and
    required artifacts.
  - Pilot `expected` contract and seeds are preserved in the goal policy.
- [libs/core/services/goal_service.py](../libs/core/services/goal_service.py)
  - Follow-up goal attempts preserve pilot metadata and seeds in the new
    cycle config, so retry attempts keep the fixture contract.
- Regression coverage:
  - [tests/unit/test_pilot_runner.py](../tests/unit/test_pilot_runner.py)
  - [tests/unit/test_goal_service.py](../tests/unit/test_goal_service.py)
  - [tests/integration/test_phase6_pilot.py](../tests/integration/test_phase6_pilot.py)

### Live cycle repaired (2026-06-13)

The already-stalled `diffusionblocks_e2e` cycle was repaired in-place by
attaching the missing goal/attempt records and enqueueing `goal_advance`.
The worker picked it up and moved the run into analysis.

Repair result:

- `goal_advance` completed with: started analysis for the DiffusionBlocks paper.
- `analysis_ingest` completed via HTML.
- `analysis_chunk` completed with 500 embedded chunks.
- Current active work is graph extraction.

### Graph extraction model route corrected (2026-06-13)

After the handoff fix, analysis exposed a separate runtime issue:
`graph_extraction` was routed to Mnemosyne alias `lfm2-5-8b-a1b`, which failed
to load in vLLM with HTTP 503. The stuck job was cooperatively cancelled and
the goal repair path started a clean analysis session.

Fixed in:

- [configs/models.mnemosyne-e2e.yaml](../configs/models.mnemosyne-e2e.yaml)
- [configs/models.mnemosyne.yaml](../configs/models.mnemosyne.yaml)

Both configs now route `graph_extraction` through the already-working
`qwen3-6-35b-a3b-mtp-gguf` local model. The current graph-extraction job is
using Qwen; repeated 400s in the log are the known
"JSON schema unsupported, fallback to prompt schema" path, not the old vLLM
model-load failure.

### Status script (2026-06-13)

Added [scripts/scientist-status.sh](../scripts/scientist-status.sh) for a
compact human-readable status view over Docker Compose/Postgres. It reports:

- compose service state
- host worker PID/log state
- selected cycle status and pilot metadata
- job summary, active jobs, recent jobs
- run records, verification, artifacts, postmortems
- latest worker log tail

Usage:

```bash
scripts/scientist-status.sh
scripts/scientist-status.sh <cycle_id>
scripts/scientist-status.sh --watch 30 <cycle_id>
```

## Verification status

Latest targeted checks after the handoff fix:

```bash
.venv/bin/ruff check libs/pilot/runner.py libs/core/services/goal_service.py \
  tests/unit/test_pilot_runner.py tests/unit/test_goal_service.py \
  tests/integration/test_phase6_pilot.py

.venv/bin/python -m pytest tests/unit/test_pilot_runner.py \
  tests/unit/test_goal_service.py tests/integration/test_phase6_pilot.py
```

Result:

- Ruff: passed.
- Targeted pytest: 14 passed.
- `git diff --check`: passed.

Dockerized pytest was not rerun after the latest patch because the current
`synthetos:latest` runtime image is built without dev dependencies (`pytest`
is not installed). Docker Compose was used for Postgres-backed status checks
and live-cycle repair. A one-off external UV test container was rejected by
the sandbox review because it would mount the private workspace into a
third-party image.

Earlier in the fable-branch rebuild, before the pilot-goal handoff patch, the
full Dockerized backend/web suite passed.

## Known issues and risks

- The live `diffusionblocks_e2e` run is still in progress; no experiment run,
  verification report, or final pilot evaluation exists yet.
- Graph extraction over 500 chunks with the Qwen fallback path is slower than
  the intended small-model route.
- The model gateway still emits HTTP 400 for JSON-schema calls and falls back
  to prompt-schema mode. That path is expected, but noisy.
- Current Compose runtime images are not suitable as test images because they
  omit dev dependencies.
- The status script is useful but still shell/psql based; it is not a stable
  API surface.

## Next steps

1. Let the live `analysis_graph_extract` job finish or fail, then inspect the
   next handoff into evidence extraction and hypothesis generation.
2. Add a dev/test image or Compose test service with `pytest`, `ruff`, and
   `pyright` installed so future "run tests in Docker" requests are direct.
3. Reduce graph-extraction load for workstation pilots, either by narrowing
   the analysis budget for pilot fixtures or by restoring a reliable small
   graph-extraction model alias.
4. Once the pilot reaches protocol compilation, verify that required fixture
   artifacts (`metrics.json`, `model_weights.pt`, `report.md`) remain threaded
   into generated specs and verification criteria.
5. After the live pilot finishes, run `synthetos pilot evaluate
   diffusionblocks_e2e <cycle_id>` and persist the evaluation artifact.

## Historical note: Calm Console frontend

The previous status snapshot from 2026-04-22 focused on the Calm Console
frontend redesign. That pass implemented the warm-neutral dashboard shell,
shared UI tokens/components, pipeline rail, dashboard, charter list/detail,
patterns, events, and skills surfaces. Several older route groups still need a
styling pass, and browser verification remains outstanding.
