from __future__ import annotations

import json
from pathlib import Path


def collect_artifact_manifest(artifact_root: Path) -> dict[str, object]:
    manifest_path = artifact_root / "artifact_manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    metrics_path = artifact_root / "metrics.json"
    checkpoint_path = artifact_root / "model_checkpoint.json"
    predictions_path = artifact_root / "predictions.json"
    artifacts: list[dict[str, object]] = []
    for path in [metrics_path, checkpoint_path, predictions_path]:
        if path.exists():
            artifacts.append({"path": str(path), "name": path.name})
    return {
        "manifest_path": str(manifest_path),
        "metrics_path": str(metrics_path) if metrics_path.exists() else None,
        "checkpoint_path": str(checkpoint_path) if checkpoint_path.exists() else None,
        "predictions_path": str(predictions_path) if predictions_path.exists() else None,
        "artifacts": artifacts,
    }


def classify_failure(
    *,
    exit_code: int | None,
    interrupted_status: str | None,
    artifact_manifest: dict[str, object],
    stderr_path: Path,
) -> str | None:
    if interrupted_status == "cancelled":
        return "runtime_exception"
    if interrupted_status == "paused":
        return None
    if exit_code in (137, 143):
        return "oom_or_resource_limit"
    if exit_code not in (0, None):
        return "runtime_exception"
    metrics_path = artifact_manifest.get("metrics_path")
    if metrics_path and not Path(str(metrics_path)).exists():
        return "metric_parse_failure"
    manifest_path = Path(str(artifact_manifest.get("manifest_path", "")))
    if manifest_path and not manifest_path.exists():
        return "invalid_artifact_output"
    if stderr_path.exists() and "No module named" in stderr_path.read_text(encoding="utf-8"):
        return "dependency_failure"
    return None
