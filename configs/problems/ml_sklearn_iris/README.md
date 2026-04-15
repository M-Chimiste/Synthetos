# ml_sklearn_iris — CPU workstation pilot fixture

Classical tabular classification on the Iris dataset. Runs in autonomous
mode with a 10-run / 30-minute budget so the loop exercises pivoting
between at least two model families.

## Purpose

Bigger than `ml_baseline_small` — this fixture is meant to produce
real-ish directional signals and at least one `successful_line` pattern
while staying CPU-only.

## Hardware prerequisites

- CPU only, 4 cores / 4 GB RAM recommended
- No GPU required
- Dataset is fetched via `sklearn.datasets.load_iris()` (no network)

## Cost estimate

Tiny local LLM calls only (LMStudio/Ollama). Wall clock typically
10–30 minutes depending on LLM throughput.
