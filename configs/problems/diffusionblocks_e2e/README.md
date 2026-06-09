# diffusionblocks_e2e

Workstation E2E pilot for the AI co-scientist loop. The fixture asks Synthetos
to derive a small executable experiment from arXiv:2506.14202v3, run it under
autonomous budget control, verify the outputs, and publish a completion report.

The run is intentionally bounded: one GPU, four total runs, short per-run
timeouts, and no large model downloads. Its purpose is to test orchestration
quality, GPU execution, artifact capture, verification, and narrative reporting
before spending time on a larger reproduction.
