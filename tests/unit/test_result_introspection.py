"""Result introspection tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from uuid_utils import uuid7

from libs.core.services import result_introspection
from libs.core.services.result_introspection import (
    ResultIntrospectionError,
    artifact_id_for_path,
    normalize_run_artifacts,
    resolve_run_artifact_path,
)
from libs.storage.models.experiment import RunRecord


class _ArtifactSession:
    def __init__(self, run):
        self.run = run

    def get(self, model, key):
        if model is RunRecord and str(key) == str(self.run.id):
            return self.run
        return None


def test_normalize_run_artifacts_exposes_model_download_url() -> None:
    run = SimpleNamespace(
        id=uuid7(),
        artifact_manifest=[
            {
                "name": "model_weights.pt",
                "path": "model_weights.pt",
                "size_bytes": 12,
                "hash": "abc",
            }
        ],
    )

    artifacts = normalize_run_artifacts(run)

    assert artifacts[0].artifact_type == "model"
    assert artifacts[0].download_url.endswith(
        f"/runs/{run.id}/artifacts/{artifact_id_for_path('model_weights.pt')}"
    )


def test_resolve_run_artifact_path_serves_only_manifest_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    run_id = uuid7()
    artifact_dir = tmp_path / "artifacts" / str(run_id)
    artifact_dir.mkdir(parents=True)
    model_path = artifact_dir / "model_weights.pt"
    model_path.write_bytes(b"weights")
    run = SimpleNamespace(
        id=run_id,
        artifact_manifest=[
            {"name": "model_weights.pt", "path": "model_weights.pt", "size_bytes": 7}
        ],
    )
    monkeypatch.setattr(
        result_introspection,
        "get_settings",
        lambda: SimpleNamespace(data_root=tmp_path),
    )

    resolved, artifact = resolve_run_artifact_path(
        _ArtifactSession(run),
        run_id,
        artifact_id_for_path("model_weights.pt"),
    )

    assert resolved == model_path.resolve()
    assert artifact.name == "model_weights.pt"


def test_resolve_run_artifact_path_rejects_traversal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    run_id = uuid7()
    run = SimpleNamespace(
        id=run_id,
        artifact_manifest=[{"name": "secret.txt", "path": "../secret.txt"}],
    )
    monkeypatch.setattr(
        result_introspection,
        "get_settings",
        lambda: SimpleNamespace(data_root=tmp_path),
    )

    with pytest.raises(ResultIntrospectionError, match="unsafe artifact path"):
        resolve_run_artifact_path(
            _ArtifactSession(run),
            run_id,
            artifact_id_for_path("../secret.txt"),
        )
