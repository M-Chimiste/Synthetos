"""Integration tests for Phase 3 run execution and live control."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.api.main import app, get_db
from libs.adapters.container import ContainerExecutionResult
from libs.adapters.git import WorktreeInfo
from libs.core.config import AppConfig
from libs.storage import services
from libs.storage.base import Base
from libs.storage.models import (
    ExperimentSpecModel,
    HypothesisCardModel,
    JobModel,
    ResearchCharterModel,
    ResearchCycleModel,
    SkillExecutionRecordModel,
)

AUTH_HEADERS = {"Authorization": "Bearer lab-local-admin"}


class FakeGitWorktreeAdapter:
    def __init__(self, _repo_root: Path):
        pass

    def create_worktree(self, workspaces_root: Path, run_public_id: str) -> WorktreeInfo:
        path = workspaces_root / run_public_id
        path.mkdir(parents=True, exist_ok=True)
        return WorktreeInfo(workspace_path=path, base_commit="abc123", base_branch="main")

    def capture_patch_archive(self, _workspace_path: Path, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("diff --git a/file b/file\n", encoding="utf-8")
        return destination


class FakeDockerContainerAdapter:
    def __init__(self, poll_interval_seconds: float = 1.0):
        self.poll_interval_seconds = poll_interval_seconds

    def run(
        self,
        *,
        spec,
        stdout_path,
        stderr_path,
        telemetry_callback,
        status_checker,
        container_name,
    ):
        del status_checker, container_name
        stdout_path.write_text("epoch 1\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        artifact_root = Path(spec.artifact_output_path)
        artifact_root.mkdir(parents=True, exist_ok=True)
        metrics = {"accuracy": 1.0, "loss": 0.01}
        (artifact_root / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
        (artifact_root / "predictions.json").write_text(
            json.dumps([{"id": "row-1", "prediction": 1}]),
            encoding="utf-8",
        )
        checkpoint_path = artifact_root / "model_checkpoint.json"
        checkpoint_path.write_text(json.dumps({"checkpoint": "ok"}), encoding="utf-8")
        manifest = {
            "run_public_id": "placeholder",
            "manifest_path": str(artifact_root / "artifact_manifest.json"),
            "metrics_path": str(artifact_root / "metrics.json"),
            "checkpoint_path": str(checkpoint_path),
            "predictions_path": str(artifact_root / "predictions.json"),
            "artifacts": [{"name": "metrics", "path": str(artifact_root / "metrics.json")}],
        }
        (artifact_root / "artifact_manifest.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
        telemetry_callback("log", {"line": "epoch 1"}, "stdout", "epoch 1")
        telemetry_callback("resource", {"cpu": "12%", "memory": "32MiB"}, None, None)
        return ContainerExecutionResult(
            exit_code=0,
            interrupted_status=None,
            latest_resource_snapshot={"cpu": "12%", "memory": "32MiB"},
        )


@pytest.fixture()
def tmp_config(tmp_path: Path):
    execution_dir = tmp_path / "execution"
    execution_dir.mkdir()
    (execution_dir / "images.yaml").write_text(
        "approved_images:\n  offline-baseline:\n    image: python:3.12-slim\n",
        encoding="utf-8",
    )
    (execution_dir / "profiles.yaml").write_text(
        "\n".join(
            [
                "profiles:",
                "  cpu-small:",
                "    hardware_profile: cpu-small",
                "    cpu_limit: '2'",
                "    memory_limit_mb: 1024",
                "    timeout_seconds: 60",
                "    gpu_enabled: false",
                "    network_mode: disabled",
                "    image_key: offline-baseline",
                "  restricted-net:",
                "    hardware_profile: cpu-small",
                "    cpu_limit: '2'",
                "    memory_limit_mb: 1024",
                "    timeout_seconds: 60",
                "    gpu_enabled: false",
                "    network_mode: enabled",
                "    image_key: offline-baseline",
            ]
        ),
        encoding="utf-8",
    )
    (execution_dir / "settings.yaml").write_text(
        "telemetry:\n  poll_interval_seconds: 0.01\n",
        encoding="utf-8",
    )
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        "\n".join(
            [
                "allowed_command_scopes:",
                "  create_cycle:",
                "    - cycles.write",
                "approval_rules:",
                "  network_enabled_run: human_only",
                "execution:",
                "  auto_run_profiles:",
                "    - cpu-small",
                "  deny_without_force_start:",
                "    network_mode:",
                "      - enabled",
                "    image_keys:",
                "      - custom",
            ]
        ),
        encoding="utf-8",
    )
    cfg = AppConfig(
        env="test",
        db_url=f"sqlite:///{tmp_path / 'test.db'}",
        data_root=tmp_path / "data",
        model_config_path=Path("configs/models/routes.yaml"),
        policy_config_path=policy_path,
        execution_images_path=execution_dir / "images.yaml",
        execution_profiles_path=execution_dir / "profiles.yaml",
        execution_settings_path=execution_dir / "settings.yaml",
        skill_paths=[Path("skills")],
        auto_init_db=False,
    )
    cfg.ensure_data_dirs()
    return cfg


@pytest.fixture()
def test_session(tmp_config: AppConfig):
    engine = create_engine(tmp_config.db_url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return factory


@pytest.fixture()
def client(tmp_config: AppConfig, test_session):
    def override_db():
        session = test_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    with patch("libs.core.config.get_config", return_value=tmp_config):
        with patch("apps.api.main.get_config", return_value=tmp_config):
            with test_session() as session:
                services.seed_dev_client_and_token(session, tmp_config)
                services.sync_skill_catalog(session, tmp_config)
            yield TestClient(app, raise_server_exceptions=True)
    app.dependency_overrides.clear()


def _create_valid_spec(session) -> tuple[str, str]:
    charter = ResearchCharterModel(
        public_id="charter-test",
        title="Phase 3 Test Cycle",
        problem_statement="Train an offline benchmark baseline.",
        success_criteria={"summary": "Produce a run record"},
        budget_envelope={},
        source_scope={},
        stop_conditions={"summary": "Stop after run"},
        constraints={},
    )
    session.add(charter)
    session.flush()
    cycle = ResearchCycleModel(
        public_id="cycle-test",
        charter_id=charter.id,
        current_status="ready",
    )
    session.add(cycle)
    session.flush()
    hypothesis = HypothesisCardModel(
        public_id="hyp-test",
        cycle_id=cycle.id,
        title="Offline baseline",
        statement="A compact local classifier can produce a deterministic baseline.",
        rationale="Needed for Phase 3 execution.",
        approach_summary="Train a tiny model on fixture data.",
        supporting_evidence=[],
        counter_evidence=[],
        status="approved",
        model_route_id="protocol_drafter",
        prompt_id="prompts/ideation/v1/protocol_compilation.md",
    )
    session.add(hypothesis)
    session.flush()
    spec = ExperimentSpecModel(
        public_id="spec-test",
        cycle_id=cycle.id,
        hypothesis_card_id=hypothesis.id,
        title="Offline Baseline Spec",
        objective="Train a compact offline baseline.",
        baseline_description="Rule-based baseline.",
        method_description="Tiny local training loop.",
        controls=[],
        metrics=[{"name": "accuracy"}],
        datasets=[{"name": "fixture"}],
        artifacts=[{"name": "metrics.json"}],
        stop_conditions=[{"type": "epochs", "value": 25}],
        expected_outputs=[{"name": "metrics.json"}],
        status="valid",
        validation_issues=[],
        rejection_reason=None,
        estimated_runtime_minutes=5,
        gpu_required=False,
        resource_requirements={},
        model_route_id="protocol_drafter",
        prompt_id="prompts/ideation/v1/protocol_compilation.md",
    )
    session.add(spec)
    session.commit()
    return cycle.public_id, spec.public_id


def _run_worker(client: TestClient) -> str:
    response = client.post("/api/v1/admin/worker/run-once", headers=AUTH_HEADERS)
    assert response.status_code == 200
    return response.json()["result"]


def test_create_run_policy_blocked(client: TestClient, test_session) -> None:
    with test_session() as session:
        _cycle_id, spec_id = _create_valid_spec(session)

    response = client.post(
        f"/api/v1/experiment-specs/{spec_id}/runs",
        json={"execution_profile": "restricted-net"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["status"] == "policy_blocked"
    assert payload["run"]["failure_classification"] == "policy_rejection"

    jobs = client.get("/api/v1/jobs", headers=AUTH_HEADERS).json()["items"]
    assert not any(job["operator_name"] == "run_prepare" for job in jobs)


def test_full_phase3_run_pipeline_with_mocked_adapters(client: TestClient, test_session) -> None:
    with test_session() as session:
        cycle_id, spec_id = _create_valid_spec(session)

    with patch(
        "libs.orchestration.operators.GitWorktreeAdapter",
        FakeGitWorktreeAdapter,
    ):
        with patch(
            "libs.orchestration.operators.DockerContainerAdapter",
            FakeDockerContainerAdapter,
        ):
            response = client.post(
                f"/api/v1/experiment-specs/{spec_id}/runs",
                json={"execution_profile": "cpu-small"},
                headers=AUTH_HEADERS,
            )
            assert response.status_code == 200
            run_id = response.json()["run"]["public_id"]

            assert _run_worker(client) == "job_succeeded"
            assert _run_worker(client) == "job_succeeded"
            assert _run_worker(client) == "job_succeeded"

    detail = client.get(f"/api/v1/runs/{run_id}", headers=AUTH_HEADERS).json()
    assert detail["run"]["status"] == "succeeded"
    assert detail["run"]["metrics_summary"]["accuracy"] == 1.0
    assert len(detail["telemetry_events"]) >= 2
    assert any(event["event_type"] == "resource" for event in detail["telemetry_events"])
    assert any(report["title"].startswith("Run Summary") for report in detail["reports"])

    cycle_runs = client.get(f"/api/v1/cycles/{cycle_id}/runs", headers=AUTH_HEADERS).json()
    assert cycle_runs["total"] == 1
    assert cycle_runs["items"][0]["public_id"] == run_id

    with test_session() as session:
        cycle = session.scalar(
            select(ResearchCycleModel).where(ResearchCycleModel.public_id == cycle_id)
        )
        assert cycle is not None
        run_jobs = session.scalars(
            select(JobModel).where(
                JobModel.cycle_id == cycle.id,
                JobModel.operator_name.like("run_%"),
            )
        ).all()
        assert {job.operator_name for job in run_jobs} >= {
            "run_prepare",
            "run_execute",
            "run_finalize",
        }
        skill_records = session.scalars(
            select(SkillExecutionRecordModel).where(SkillExecutionRecordModel.cycle_id == cycle.id)
        ).all()
        assert any(record.operator_name == "run_prepare" for record in skill_records)
        assert any(record.operator_name == "run_finalize" for record in skill_records)
