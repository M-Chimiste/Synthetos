# ml_vision_tiny — GPU workstation pilot fixture

Small convnet on a 5-class subset of a public image benchmark. GPU is
required because the loop expects realistic wall-clock pressure to exercise
directional-signal classification and remediation priors.

## Purpose

The most realistic pilot shipped with Phase 6. It produces both
`signal_trajectory` and `successful_line` patterns after consolidation
and should exercise at least one mechanical-failure remediation path
(OOM / dependency) on the typical laptop GPU.

## Hardware prerequisites

- Nvidia or Apple Silicon GPU with >= 8 GB VRAM
- 8 CPU cores / 16 GB RAM recommended
- Public image benchmark subset cached under `data/datasets/` (see
  `scripts/prepare_vision_tiny.sh` — TODO)

## Cost estimate

Small local or hosted LLM calls for planning/protocol/evaluation roles;
GPU time for 2–6 short training runs. Wall clock typically 30–120
minutes on a laptop.

## NOT CI-safe

This fixture is intentionally excluded from CI — run it manually on a
researcher workstation.
