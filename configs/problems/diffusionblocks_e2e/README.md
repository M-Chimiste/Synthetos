# diffusionblocks_e2e

Workstation E2E pilot for the AI co-scientist loop. The fixture asks Synthetos
to derive a small executable experiment from arXiv:2506.14202v3, run it under
autonomous budget control, verify the outputs, and publish a completion report.

The run is intentionally bounded: one GPU, four total runs, short per-run
timeouts, and no large model downloads. The co-scientist should produce the
experiment code and artifacts inside the run workspace, using a tiny Qwen-style
causal LM proxy for `Qwen/Qwen3.5-2B` and a cached or streamed text source such
as `tatsu-lab/alpaca` when available, with a deterministic fallback corpus.

Required run artifacts are `metrics.json`, `model_weights.pt`, and `report.md`.
The report should make clear which results are measured in the smoke test and
which claims remain speculative.
