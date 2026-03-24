"""Integration tests for Phase 4 verification, postmortem, and historical comparison."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.main import app, get_db
from libs.adapters.container import ContainerExecutionResult
from libs.adapters.git import WorktreeInfo
from libs.core.config import AppConfig
from libs.core.ids import generate_public_id
from libs.storage import services
from libs.storage.base import Base
from libs.storage.models import (
    ExperimentSpecModel,
    HypothesisCardModel,
    RemediationActionModel,
    ResearchCharterModel,
    ResearchCycleModel,
    RunRecordModel,
)

AUTH_HEADERS = {"Authorization": "Bearer lab-local-admin"}


class FakeGitWorktreeAdapter:
    def __init__(self, _repo_root: Path):
        pass

    def create_worktree(
        self, workspaces_root: Path, run_public_id: str,
    ) -> WorktreeInfo:
        path = workspaces_root / run_public_id
        path.mkdir(parents=True, exist_ok=True)
        return WorktreeInfo(
            workspace_path=path,
            base_commit="abc123",
            base_branch="main",
        )

    def capture_patch_archive(
        self, _workspace_path: Path, destination: Path,
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            "diff --git a/file b/file\n", encoding="utf-8",
        )
        return destination

    def remove_worktree(self, _workspace_path: Path) -> None:
        pass


class FakeDockerContainerAdapter:
    def __init__(self, poll_interval_seconds: float = 1.0):
        self.poll_interval_seconds = poll_interval_seconds

    def run(
        self, *, spec, stdout_path, stderr_path,
        telemetry_callback, status_checker, container_name,
    ):
        del status_checker, container_name
        stdout_path.write_text("epoch 1\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        artifact_root = Path(spec.artifact_output_path)
        artifact_root.mkdir(parents=True, exist_ok=True)
        metrics = {"accuracy": 0.9, "loss": 0.1}
        (artifact_root / "metrics.json").write_text(
            json.dumps(metrics), encoding="utf-8",
        )
        (artifact_root / "predictions.json").write_text(
            json.dumps([{"id": "row-1", "prediction": 1}]),
            encoding="utf-8",
        )
        checkpoint_path = artifact_root / "model_checkpoint.json"
        checkpoint_path.write_text(
            json.dumps({"checkpoint": "ok"}), encoding="utf-8",
        )
        manifest = {
            "run_public_id": "placeholder",
            "manifest_path": str(
                artifact_root / "artifact_manifest.json",
            ),
            "metrics_path": str(artifact_root / "metrics.json"),
            "checkpoint_path": str(checkpoint_path),
            "predictions_path": str(
                artifact_root / "predictions.json",
            ),
            "artifacts": [
                {
                    "name": "metrics",
                    "path": str(artifact_root / "metrics.json"),
                },
            ],
        }
        (artifact_root / "artifact_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8",
        )
        telemetry_callback(
            "log", {"line": "epoch 1"}, "stdout", "epoch 1",
        )
        return ContainerExecutionResult(
            exit_code=0,
            interrupted_status=None,
            latest_resource_snapshot={"cpu": "12%", "memory": "32MiB"},
        )


class FakeDockerFailAdapter(FakeDockerContainerAdapter):
    """Simulates a failed run."""

    def run(self, *, spec, stdout_path, stderr_path,
            telemetry_callback, status_checker, container_name):
        del status_checker, container_name
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text(
            "Traceback...\nRuntimeError: out of memory\n",
            encoding="utf-8",
        )
        artifact_root = Path(spec.artifact_output_path)
        artifact_root.mkdir(parents=True, exist_ok=True)
        return ContainerExecutionResult(
            exit_code=137,
            interrupted_status=None,
            latest_resource_snapshot={},
        )


class FakeDockerDependencyRemediationAdapter(FakeDockerContainerAdapter):
    """Fails until the remediation loop adds the required pip package."""

    def run(
        self, *, spec, stdout_path, stderr_path,
        telemetry_callback, status_checker, container_name,
    ):
        del status_checker, container_name
        pip_packages = set((spec.build_recipe or {}).get("pip_packages", []))
        if "torch==2.3.1" not in pip_packages:
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text(
                "Traceback...\nModuleNotFoundError: No module named 'torch'\n",
                encoding="utf-8",
            )
            Path(spec.artifact_output_path).mkdir(parents=True, exist_ok=True)
            return ContainerExecutionResult(
                exit_code=1,
                interrupted_status=None,
                latest_resource_snapshot={},
            )
        return super().run(
            spec=spec,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            telemetry_callback=telemetry_callback,
            status_checker=lambda: None,
            container_name="ignored",
        )


class FakeDockerTimeoutMutationAdapter(FakeDockerContainerAdapter):
    """Fails with timeout until the remediation loop extends timeout_seconds."""

    def run(
        self, *, spec, stdout_path, stderr_path,
        telemetry_callback, status_checker, container_name,
    ):
        del status_checker, container_name
        if spec.timeout_seconds < 120:
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text("Run exceeded allotted time\n", encoding="utf-8")
            Path(spec.artifact_output_path).mkdir(parents=True, exist_ok=True)
            return ContainerExecutionResult(
                exit_code=None,
                interrupted_status="timed_out",
                latest_resource_snapshot={"elapsed_seconds": spec.timeout_seconds},
            )
        return super().run(
            spec=spec,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            telemetry_callback=telemetry_callback,
            status_checker=lambda: None,
            container_name="ignored",
        )


class FakeDockerConstraintConflictAdapter(FakeDockerContainerAdapter):
    """Produces an improving primary metric with a regressing constraint metric."""

    def run(
        self, *, spec, stdout_path, stderr_path,
        telemetry_callback, status_checker, container_name,
    ):
        del status_checker, container_name
        stdout_path.write_text("epoch 1\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        artifact_root = Path(spec.artifact_output_path)
        artifact_root.mkdir(parents=True, exist_ok=True)
        metrics = {"accuracy": 0.91, "latency_ms": 145.0}
        (artifact_root / "metrics.json").write_text(
            json.dumps(metrics), encoding="utf-8",
        )
        (artifact_root / "predictions.json").write_text(
            json.dumps([{"id": "row-1", "prediction": 1}]),
            encoding="utf-8",
        )
        manifest = {
            "run_public_id": "placeholder",
            "manifest_path": str(artifact_root / "artifact_manifest.json"),
            "metrics_path": str(artifact_root / "metrics.json"),
            "predictions_path": str(artifact_root / "predictions.json"),
            "artifacts": [
                {"name": "metrics", "path": str(artifact_root / "metrics.json")},
            ],
        }
        (artifact_root / "artifact_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8",
        )
        telemetry_callback("log", {"line": "epoch 1"}, "stdout", "epoch 1")
        return ContainerExecutionResult(
            exit_code=0,
            interrupted_status=None,
            latest_resource_snapshot={"cpu": "15%", "memory": "40MiB"},
        )


@pytest.fixture()
def tmp_config(tmp_path: Path):
    execution_dir = tmp_path / "execution"
    execution_dir.mkdir()
    (execution_dir / "images.yaml").write_text(
        "approved_images:\n"
        "  offline-baseline:\n"
        "    image: python:3.12-slim\n",
        encoding="utf-8",
    )
    (execution_dir / "profiles.yaml").write_text(
        "\n".join([
            "profiles:",
            "  cpu-small:",
            "    hardware_profile: cpu-small",
            "    cpu_limit: '2'",
            "    memory_limit_mb: 1024",
            "    timeout_seconds: 60",
            "    gpu_enabled: false",
            "    network_mode: disabled",
            "    image_key: offline-baseline",
        ]),
        encoding="utf-8",
    )
    (execution_dir / "settings.yaml").write_text(
        "telemetry:\n  poll_interval_seconds: 0.01\n",
        encoding="utf-8",
    )
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        "\n".join([
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
            "verification:",
            "  require_baseline_comparison: true",
            "  auto_postmortem_on_failure: true",
        ]),
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


def _create_valid_spec(
    session,
    *,
    suffix: str = "p4",
    charter: ResearchCharterModel | None = None,
) -> tuple[str, str]:
    if charter is None:
        charter = ResearchCharterModel(
            public_id=f"charter-{suffix}",
            title="Phase 4 Test Cycle",
            problem_statement="Test verification pipeline.",
            success_criteria={"summary": "Verify runs"},
            budget_envelope={},
            source_scope={},
            stop_conditions={"summary": "Stop after verify"},
            constraints={},
        )
        session.add(charter)
        session.flush()
    cycle = ResearchCycleModel(
        public_id=f"cycle-{suffix}",
        charter_id=charter.id,
        current_status="ready",
    )
    session.add(cycle)
    session.flush()
    hypothesis = HypothesisCardModel(
        public_id=f"hyp-{suffix}",
        cycle_id=cycle.id,
        title="Test hypothesis",
        statement="Test classification baseline.",
        rationale="Needed for Phase 4 testing.",
        approach_summary="Tiny model on fixture data.",
        supporting_evidence=[],
        counter_evidence=[],
        status="approved",
        model_route_id="protocol_drafter",
        prompt_id="prompts/ideation/v1/protocol_compilation.md",
    )
    session.add(hypothesis)
    session.flush()
    spec = ExperimentSpecModel(
        public_id=f"spec-{suffix}",
        cycle_id=cycle.id,
        hypothesis_card_id=hypothesis.id,
        title="Test Spec",
        objective="Train a test model.",
        baseline_description="Rule-based baseline.",
        method_description="Tiny local training loop.",
        controls=[],
        metrics=[
            {
                "name": "accuracy",
                "baseline_value": 0.8,
                "higher_is_better": True,
            },
        ],
        datasets=[{"name": "fixture", "role": "validation"}],
        artifacts=[{"name": "metrics.json"}],
        stop_conditions=[{"type": "epochs", "value": 5}],
        expected_outputs=[{"name": "metrics.json"}],
        status="valid",
        validation_issues=[],
        rejection_reason=None,
        estimated_runtime_minutes=1,
        gpu_required=False,
        resource_requirements={},
        model_route_id="protocol_drafter",
        prompt_id="prompts/ideation/v1/protocol_compilation.md",
    )
    session.add(spec)
    session.commit()
    return cycle.public_id, spec.public_id


def _run_worker(client: TestClient) -> str:
    response = client.post(
        "/api/v1/admin/worker/run-once", headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    return response.json()["result"]


def _run_jobs_until_idle(client: TestClient, *, max_steps: int = 20) -> list[str]:
    results: list[str] = []
    for _ in range(max_steps):
        result = _run_worker(client)
        results.append(result)
        if result == "no_job":
            return results
    raise AssertionError(f"worker did not go idle after {max_steps} steps: {results}")


def _run_full_pipeline(client, test_session, docker_adapter_cls):
    """Run prepare → execute → finalize → verify → (postmortem) → report."""
    with test_session() as session:
        cycle_id, spec_id = _create_valid_spec(session)

    with patch(
        "libs.orchestration.operators.GitWorktreeAdapter",
        FakeGitWorktreeAdapter,
    ), patch(
        "libs.orchestration.operators.DockerContainerAdapter",
        docker_adapter_cls,
    ):
        response = client.post(
            f"/api/v1/experiment-specs/{spec_id}/runs",
            json={"execution_profile": "cpu-small"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200
        run_id = response.json()["run"]["public_id"]

        # run_prepare, run_execute, run_finalize
        for _ in range(3):
            assert _run_worker(client) == "job_succeeded"

        # run_verify
        assert _run_worker(client) == "job_succeeded"

        # failure_postmortem or verification_report (or both)
        result = _run_worker(client)
        assert result == "job_succeeded"

        # Possibly one more (verification_report after postmortem)
        _run_worker(client)

    return cycle_id, run_id


def _seed_prior_run(
    session,
    *,
    cycle_id: int,
    spec_id: int,
    metrics_summary: dict[str, float],
) -> RunRecordModel:
    created_at = datetime.now(UTC) - timedelta(hours=1)
    run = RunRecordModel(
        public_id=generate_public_id("run"),
        cycle_id=cycle_id,
        experiment_spec_id=spec_id,
        status="succeeded",
        execution_profile="cpu-small",
        workspace_path="/tmp/prior-run",
        artifact_root="/tmp/prior-artifacts",
        image="python:3.12-slim",
        build_recipe={},
        command=["python", "train.py"],
        env_vars={},
        mounts=[],
        hardware_profile="cpu-small",
        timeout_seconds=60,
        memory_limit_mb=1024,
        network_mode="disabled",
        bound_skill_keys=[],
        prompt_lineage=[],
        model_lineage=[],
        latest_resource_snapshot={},
        metrics_summary=metrics_summary,
        artifact_manifest={},
        verification_outcome="tentative",
        attempt_count=1,
        started_at=created_at,
        completed_at=created_at,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(run)
    session.commit()
    return run


def test_successful_run_verification(
    client: TestClient, test_session,
):
    cycle_id, run_id = _run_full_pipeline(
        client, test_session, FakeDockerContainerAdapter,
    )

    # Check run detail includes verification
    detail = client.get(
        f"/api/v1/runs/{run_id}", headers=AUTH_HEADERS,
    ).json()
    assert detail["run"]["status"] == "succeeded"
    assert detail["run"]["verification_outcome"] is not None
    assert detail["verification_report"] is not None
    assert detail["verification_report"]["outcome"] in (
        "robust", "tentative",
    )

    # Check verification summary endpoint
    summary = client.get(
        f"/api/v1/cycles/{cycle_id}/verification",
        headers=AUTH_HEADERS,
    ).json()
    assert summary["total_runs"] >= 1
    assert summary["robust_count"] + summary["tentative_count"] >= 1
    assert summary["next_step_recommendations"]
    assert summary["latest_cycle_summary_report_public_id"] is not None

    # Check verification reports list endpoint
    reports = client.get(
        f"/api/v1/cycles/{cycle_id}/verification-reports",
        headers=AUTH_HEADERS,
    ).json()
    assert reports["total"] >= 1
    vr_id = reports["items"][0]["public_id"]

    # Check verification report detail
    detail_resp = client.get(
        f"/api/v1/verification-reports/{vr_id}",
        headers=AUTH_HEADERS,
    ).json()
    assert detail_resp["outcome"] in ("robust", "tentative")
    assert detail_resp["reviewer_summary"]
    assert detail_resp["output_contract_checks"]
    assert detail_resp["rerun_note"]

    # Check historical comparison endpoint
    hist = client.get(
        f"/api/v1/runs/{run_id}/historical-comparison",
        headers=AUTH_HEADERS,
    ).json()
    assert hist["run_public_id"] == run_id
    assert hist["comparison_scope"] == "same_charter"

    cycle_summary_report = client.get(
        f"/api/v1/reports/{summary['latest_cycle_summary_report_public_id']}",
        headers=AUTH_HEADERS,
    ).json()
    assert "Cycle Verification Summary" in cycle_summary_report["title"]
    assert "quality_metadata" in cycle_summary_report
    assert isinstance(cycle_summary_report["quality_metadata"], dict)


def test_failed_run_generates_postmortem(
    client: TestClient, test_session,
):
    cycle_id, run_id = _run_full_pipeline(
        client, test_session, FakeDockerFailAdapter,
    )

    detail = client.get(
        f"/api/v1/runs/{run_id}", headers=AUTH_HEADERS,
    ).json()
    assert detail["run"]["status"] == "failed"
    assert detail["run"]["verification_outcome"] == "invalid"
    assert detail["postmortem"] is not None

    # Check postmortems list
    postmortems = client.get(
        f"/api/v1/cycles/{cycle_id}/postmortems",
        headers=AUTH_HEADERS,
    ).json()
    assert postmortems["total"] >= 1
    pm_id = postmortems["items"][0]["public_id"]

    # Check postmortem detail
    pm_detail = client.get(
        f"/api/v1/postmortems/{pm_id}", headers=AUTH_HEADERS,
    ).json()
    assert pm_detail["failure_class"]
    assert pm_detail["root_cause_summary"]

    # Summary should show the postmortem count
    summary = client.get(
        f"/api/v1/cycles/{cycle_id}/verification",
        headers=AUTH_HEADERS,
    ).json()
    assert summary["postmortem_count"] >= 1
    assert summary["invalid_count"] >= 1


def test_dependency_failure_is_auto_remediated_and_exposed_on_run_detail(
    client: TestClient, test_session,
):
    with test_session() as session:
        _, spec_id = _create_valid_spec(session, suffix="depfix")

    gateway = MagicMock()
    gateway.call_structured.return_value = {
        "diagnosis": "Missing torch dependency",
        "fix_type": "dependency_add",
        "fix_description": "Add torch to the run build recipe",
        "dependency_adds": ["torch==2.3.1"],
    }
    gateway.resolve_route.return_value = MagicMock(id="local-debugger")

    with patch(
        "libs.orchestration.operators.GitWorktreeAdapter",
        FakeGitWorktreeAdapter,
    ), patch(
        "libs.orchestration.operators.DockerContainerAdapter",
        FakeDockerDependencyRemediationAdapter,
    ), patch(
        "libs.orchestration.operators.ModelGateway.from_config",
        return_value=gateway,
    ):
        response = client.post(
            f"/api/v1/experiment-specs/{spec_id}/runs",
            json={"execution_profile": "cpu-small"},
            headers=AUTH_HEADERS,
        )
        run_id = response.json()["run"]["public_id"]
        results = _run_jobs_until_idle(client)

    assert "no_job" in results
    detail = client.get(f"/api/v1/runs/{run_id}", headers=AUTH_HEADERS).json()
    assert detail["run"]["status"] == "succeeded"
    assert detail["verification_report"] is not None
    assert detail["postmortem"] is None
    assert len(detail["remediation_actions"]) == 1
    assert detail["remediation_actions"][0]["fix_type"] == "dependency_add"
    assert detail["remediation_actions"][0]["fix_payload"]["dependency_adds"] == ["torch==2.3.1"]
    assert detail["run"]["run_spec"]["build_recipe"]["pip_packages"] == ["torch==2.3.1"]


def test_runtime_mutation_retry_updates_run_spec(
    client: TestClient, test_session,
):
    with test_session() as session:
        _, spec_id = _create_valid_spec(session, suffix="timeoutfix")

    gateway = MagicMock()
    gateway.call_structured.return_value = {
        "diagnosis": "The execution budget is too small for this run",
        "fix_type": "env_change",
        "fix_description": "Extend timeout for the retry",
        "run_mutations": {"timeout_seconds": 300},
    }
    gateway.resolve_route.return_value = MagicMock(id="local-debugger")

    with patch(
        "libs.orchestration.operators.GitWorktreeAdapter",
        FakeGitWorktreeAdapter,
    ), patch(
        "libs.orchestration.operators.DockerContainerAdapter",
        FakeDockerTimeoutMutationAdapter,
    ), patch(
        "libs.orchestration.operators.ModelGateway.from_config",
        return_value=gateway,
    ):
        response = client.post(
            f"/api/v1/experiment-specs/{spec_id}/runs",
            json={"execution_profile": "cpu-small"},
            headers=AUTH_HEADERS,
        )
        run_id = response.json()["run"]["public_id"]
        results = _run_jobs_until_idle(client)

    assert "no_job" in results
    detail = client.get(f"/api/v1/runs/{run_id}", headers=AUTH_HEADERS).json()
    assert detail["run"]["status"] == "succeeded"
    assert detail["run"]["run_spec"]["timeout_seconds"] == 300
    assert len(detail["remediation_actions"]) == 1
    assert (
        detail["remediation_actions"][0]["fix_payload"]["run_mutations_applied"]["timeout_seconds"]
        == 300
    )


def test_run_detail_returns_ordered_remediation_lineage(
    client: TestClient, test_session,
):
    with test_session() as session:
        cycle_id, spec_id = _create_valid_spec(session, suffix="lineage")
        response = client.post(
            f"/api/v1/experiment-specs/{spec_id}/runs",
            json={"execution_profile": "cpu-small"},
            headers=AUTH_HEADERS,
        )
        run_id = response.json()["run"]["public_id"]
        run = services.get_run_by_public_id(session, run_id)
        session.add_all([
            RemediationActionModel(
                public_id="remed-two",
                cycle_id=run.cycle_id,
                run_record_id=run.id,
                attempt_number=2,
                failure_classification="runtime_exception",
                prompt_mode="full_debug",
                prompt_id="prompts/remediation/v1/full_debug.md",
                model_route_id="local-debugger",
                diagnosis="second",
                fix_type="code_patch",
                fix_description="second fix",
                fix_payload={"order": 2},
                prior_attempts_summary=[],
                outcome="applied",
            ),
            RemediationActionModel(
                public_id="remed-one",
                cycle_id=run.cycle_id,
                run_record_id=run.id,
                attempt_number=1,
                failure_classification="dependency_failure",
                prompt_mode="focused",
                prompt_id="prompts/remediation/v1/focused_fix.md",
                model_route_id="local-debugger",
                diagnosis="first",
                fix_type="dependency_add",
                fix_description="first fix",
                fix_payload={"order": 1},
                prior_attempts_summary=[],
                outcome="applied",
            ),
        ])
        session.commit()

    detail = client.get(f"/api/v1/runs/{run_id}", headers=AUTH_HEADERS).json()
    assert [item["attempt_number"] for item in detail["remediation_actions"]] == [1, 2]
    assert [item["fix_payload"]["order"] for item in detail["remediation_actions"]] == [1, 2]


def test_verification_chain_from_finalize(
    client: TestClient, test_session,
):
    """Verify that run_finalize chains into run_verify automatically."""
    with test_session() as session:
        _, spec_id = _create_valid_spec(session)

    with patch(
        "libs.orchestration.operators.GitWorktreeAdapter",
        FakeGitWorktreeAdapter,
    ), patch(
        "libs.orchestration.operators.DockerContainerAdapter",
        FakeDockerContainerAdapter,
    ):
        client.post(
            f"/api/v1/experiment-specs/{spec_id}/runs",
            json={"execution_profile": "cpu-small"},
            headers=AUTH_HEADERS,
        )

        # run_prepare
        assert _run_worker(client) == "job_succeeded"
        # run_execute
        assert _run_worker(client) == "job_succeeded"
        # run_finalize — should enqueue run_verify
        assert _run_worker(client) == "job_succeeded"

        # Check that run_verify job was enqueued
        jobs = client.get(
            "/api/v1/jobs", headers=AUTH_HEADERS,
        ).json()["items"]
        verify_jobs = [
            j for j in jobs if j["operator_name"] == "run_verify"
        ]
        assert len(verify_jobs) >= 1


def test_same_charter_history_cross_cycle(
    client: TestClient, test_session,
):
    with test_session() as session:
        charter = ResearchCharterModel(
            public_id="charter-shared",
            title="Shared Charter",
            problem_statement="Cross-cycle verification test.",
            success_criteria={"summary": "Verify runs across cycles"},
            budget_envelope={},
            source_scope={},
            stop_conditions={"summary": "Stop after verify"},
            constraints={},
        )
        session.add(charter)
        session.flush()
        _, spec_one = _create_valid_spec(session, suffix="p4a", charter=charter)
        _, spec_two = _create_valid_spec(session, suffix="p4b", charter=charter)

    with patch(
        "libs.orchestration.operators.GitWorktreeAdapter",
        FakeGitWorktreeAdapter,
    ), patch(
        "libs.orchestration.operators.DockerContainerAdapter",
        FakeDockerContainerAdapter,
    ):
        run_ids: list[str] = []
        for spec_id in (spec_one, spec_two):
            response = client.post(
                f"/api/v1/experiment-specs/{spec_id}/runs",
                json={"execution_profile": "cpu-small"},
                headers=AUTH_HEADERS,
            )
            run_ids.append(response.json()["run"]["public_id"])
            for _ in range(6):
                _run_worker(client)

    hist = client.get(
        f"/api/v1/runs/{run_ids[-1]}/historical-comparison",
        headers=AUTH_HEADERS,
    ).json()
    assert hist["total_prior_runs"] >= 1
    assert hist["comparison_scope"] == "same_charter"
    assert hist["memory_references"]


def test_self_critic_critical_short_circuits_verification(
    client: TestClient, test_session, tmp_config: AppConfig,
):
    tmp_config.policy_config_path.write_text(
        "\n".join([
            "allowed_command_scopes:",
            "  create_cycle:",
            "    - cycles.write",
            "approval_rules:",
            "  network_enabled_run: human_only",
            "execution:",
            "  auto_run_profiles:",
            "    - cpu-small",
            "verification:",
            "  self_critic_enabled: true",
            "  auto_postmortem_on_failure: false",
        ]),
        encoding="utf-8",
    )
    with test_session() as session:
        _, spec_id = _create_valid_spec(session, suffix="criticblock")

    gateway = MagicMock()
    gateway.call_structured.side_effect = [
        {
            "passed": False,
            "flags": [{"issue": "Perfect accuracy suggests leakage", "severity": "critical"}],
            "rationale": "The reported score is suspiciously perfect.",
        },
        {
            "root_cause_summary": "The self-critic found a blocking issue.",
            "contributing_factors": [],
            "remediation_suggestions": [],
            "retrieval_hints": [],
            "protocol_update_hints": [],
        },
    ]
    gateway.resolve_route.return_value = MagicMock(id="local-verifier")

    with patch(
        "libs.orchestration.operators.GitWorktreeAdapter",
        FakeGitWorktreeAdapter,
    ), patch(
        "libs.orchestration.operators.DockerContainerAdapter",
        FakeDockerContainerAdapter,
    ), patch(
        "libs.orchestration.operators.ModelGateway.from_config",
        return_value=gateway,
    ):
        response = client.post(
            f"/api/v1/experiment-specs/{spec_id}/runs",
            json={"execution_profile": "cpu-small"},
            headers=AUTH_HEADERS,
        )
        run_id = response.json()["run"]["public_id"]
        _run_jobs_until_idle(client)

    detail = client.get(f"/api/v1/runs/{run_id}", headers=AUTH_HEADERS).json()
    assert detail["run"]["verification_outcome"] == "invalid"
    assert detail["postmortem"] is None
    report_id = detail["verification_report"]["public_id"]
    report = client.get(
        f"/api/v1/verification-reports/{report_id}",
        headers=AUTH_HEADERS,
    ).json()
    assert report["self_critic_result"]["blocking"] is True
    assert report["self_critic_result"]["flags"][0]["severity"] == "critical"
    assert "self-critic" in report["reviewer_summary"].lower()
    assert gateway.call_structured.call_count == 1


def test_metric_conflict_resolution_updates_outcome_and_timeline(
    client: TestClient, test_session, tmp_config: AppConfig,
):
    tmp_config.policy_config_path.write_text(
        "\n".join([
            "allowed_command_scopes:",
            "  create_cycle:",
            "    - cycles.write",
            "approval_rules:",
            "  network_enabled_run: human_only",
            "execution:",
            "  auto_run_profiles:",
            "    - cpu-small",
            "verification:",
            "  auto_postmortem_on_failure: false",
            "  self_critic_enabled: true",
            "  default_significance_threshold: 0.01",
            "  default_stall_window: 3",
        ]),
        encoding="utf-8",
    )
    with test_session() as session:
        charter = ResearchCharterModel(
            public_id="charter-tradeoff",
            title="Tradeoff Charter",
            problem_statement="Improve accuracy without blowing the latency budget.",
            success_criteria={
                "primary_metric": "accuracy",
                "primary_higher_is_better": True,
                "constraint_metrics": [
                    {
                        "name": "latency_ms",
                        "higher_is_better": False,
                        "upper_bound": 120.0,
                    },
                ],
            },
            budget_envelope={},
            source_scope={},
            stop_conditions={"summary": "Stop after verification"},
            constraints={},
        )
        session.add(charter)
        session.flush()
        cycle_id, spec_id = _create_valid_spec(session, suffix="tradeoff", charter=charter)
        spec = session.query(ExperimentSpecModel).filter_by(public_id=spec_id).one()
        cycle = session.query(ResearchCycleModel).filter_by(public_id=cycle_id).one()
        assert spec is not None
        assert cycle is not None
        spec.metrics = [
            {"name": "accuracy", "baseline_value": 0.8, "higher_is_better": True},
            {"name": "latency_ms", "baseline_value": 100.0, "higher_is_better": False},
        ]
        session.flush()
        _seed_prior_run(
            session,
            cycle_id=cycle.id,
            spec_id=spec.id,
            metrics_summary={"accuracy": 0.84, "latency_ms": 98.0},
        )

    gateway = MagicMock()
    gateway.call_structured.side_effect = [
        {"passed": True, "flags": [], "rationale": "Metrics look plausible."},
        {
            "resolution": "reject_tradeoff",
            "rationale": "Latency regression breaks the declared constraint budget.",
            "recommendation": "Reduce model size or batch size before promoting this run.",
        },
        {
            "outcome_rationale": "Accuracy improved, but the latency tradeoff is unacceptable.",
            "reviewer_summary": "Accuracy improved, but verification rejected the run on latency.",
        },
    ]
    gateway.resolve_route.return_value = MagicMock(id="local-verifier")

    with patch(
        "libs.orchestration.operators.GitWorktreeAdapter",
        FakeGitWorktreeAdapter,
    ), patch(
        "libs.orchestration.operators.DockerContainerAdapter",
        FakeDockerConstraintConflictAdapter,
    ), patch(
        "libs.orchestration.operators.ModelGateway.from_config",
        return_value=gateway,
    ):
        response = client.post(
            f"/api/v1/experiment-specs/{spec_id}/runs",
            json={"execution_profile": "cpu-small"},
            headers=AUTH_HEADERS,
        )
        run_id = response.json()["run"]["public_id"]
        _run_jobs_until_idle(client)

    run_detail = client.get(f"/api/v1/runs/{run_id}", headers=AUTH_HEADERS).json()
    assert run_detail["run"]["verification_outcome"] == "rejected"
    assert run_detail["frontier_snapshot"]["metric_name"] == "accuracy"

    report_id = run_detail["verification_report"]["public_id"]
    report = client.get(
        f"/api/v1/verification-reports/{report_id}",
        headers=AUTH_HEADERS,
    ).json()
    assert report["directional_signal"] in ("advancing", "breakthrough")
    assert report["directional_signal_detail"]["threshold_warning"]
    tradeoff = report["directional_signal_detail"]["reconciliation"]["tradeoff_resolution"]
    assert tradeoff["resolution"] == "reject_tradeoff"
    assert tradeoff["resolved_by"] == "verifier_llm"

    summary = client.get(
        f"/api/v1/cycles/{cycle_id}/verification",
        headers=AUTH_HEADERS,
    ).json()
    recommendation_types = {
        item["recommendation_type"] for item in summary["next_step_recommendations"]
    }
    assert "tradeoff_pivot" in recommendation_types

    timeline = client.get(
        f"/api/v1/cycles/{cycle_id}/timeline",
        headers=AUTH_HEADERS,
    ).json()
    run_verified_entries = [
        item for item in timeline["items"] if item["event_type"] == "run_verified"
    ]
    assert run_verified_entries
    assert run_verified_entries[-1]["frontier_snapshot"]["metric_name"] == "accuracy"


def test_failed_run_can_skip_postmortem_when_policy_disabled(
    client: TestClient, test_session, tmp_config: AppConfig,
):
    tmp_config.policy_config_path.write_text(
        "\n".join([
            "allowed_command_scopes:",
            "  create_cycle:",
            "    - cycles.write",
            "approval_rules:",
            "  network_enabled_run: human_only",
            "execution:",
            "  auto_run_profiles:",
            "    - cpu-small",
            "verification:",
            "  require_baseline_comparison: true",
            "  auto_postmortem_on_failure: false",
        ]),
        encoding="utf-8",
    )
    cycle_id, run_id = _run_full_pipeline(
        client, test_session, FakeDockerFailAdapter,
    )

    detail = client.get(
        f"/api/v1/runs/{run_id}", headers=AUTH_HEADERS,
    ).json()
    assert detail["run"]["verification_outcome"] == "invalid"
    assert detail["postmortem"] is None

    summary = client.get(
        f"/api/v1/cycles/{cycle_id}/verification",
        headers=AUTH_HEADERS,
    ).json()
    recommendation_types = {
        item["recommendation_type"] for item in summary["next_step_recommendations"]
    }
    assert "retry_run" in recommendation_types
