"""Unit tests for Phase A auto-remediation system."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.core.config import AppConfig
from libs.core.ids import generate_public_id
from libs.core.policy import SYSTEM_ACTOR, RemediationPolicyConfig, load_remediation_policy
from libs.execution.debug import (
    RemediationResponse,
    build_remediation_prompt,
    call_debugger,
    determine_prompt_mode,
)
from libs.execution.remediation import (
    apply_code_patch,
    apply_dependency_adds,
    apply_env_changes,
    apply_run_mutations,
    apply_spec_mutations,
    build_prior_attempts_summary,
    prepare_run_for_retry,
    read_code_from_workspace,
    read_log_tail,
)
from libs.storage.base import Base
from libs.storage.models import (
    ExperimentSpecModel,
    HypothesisCardModel,
    JobModel,
    RemediationActionModel,
    ResearchCharterModel,
    ResearchCycleModel,
    RunRecordModel,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _default_policy() -> RemediationPolicyConfig:
    return RemediationPolicyConfig()


def _build_config(tmp_path: Path) -> AppConfig:
    execution_dir = tmp_path / "execution"
    execution_dir.mkdir(exist_ok=True)
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
            "  gpu-small:",
            "    hardware_profile: gpu-small",
            "    cpu_limit: '4'",
            "    memory_limit_mb: 4096",
            "    timeout_seconds: 300",
            "    gpu_enabled: true",
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
            "    - gpu-small",
            "  deny_without_force_start:",
            "    network_mode:",
            "      - enabled",
            "    image_keys:",
            "      - custom",
            "verification:",
            "  auto_postmortem_on_failure: true",
            "remediation:",
            "  enabled: true",
            "  max_attempts_per_run: 3",
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


def _build_run_fixture(
    session: Session,
    tmp_path: Path,
    *,
    failure_classification: str = "runtime_exception",
) -> tuple[ResearchCycleModel, RunRecordModel, JobModel]:
    charter = ResearchCharterModel(
        public_id=generate_public_id("ch"),
        title="Test Charter",
        problem_statement="Test problem",
    )
    session.add(charter)
    session.flush()

    cycle = ResearchCycleModel(
        public_id=generate_public_id("cy"),
        charter_id=charter.id,
        current_status="verifying",
    )
    session.add(cycle)
    session.flush()

    hyp = HypothesisCardModel(
        public_id=generate_public_id("hyp"),
        cycle_id=cycle.id,
        title="Hypothesis",
        statement="S",
        rationale="R",
        approach_summary="A",
        status="active",
        model_route_id="test",
        prompt_id="test",
    )
    session.add(hyp)
    session.flush()

    spec = ExperimentSpecModel(
        public_id=generate_public_id("spec"),
        cycle_id=cycle.id,
        hypothesis_card_id=hyp.id,
        title="Spec",
        objective="Obj",
        baseline_description="Base",
        method_description="Method",
        metrics=[{"name": "accuracy", "higher_is_better": True}],
        expected_outputs=[{"name": "metrics.json", "path": "/artifacts/metrics.json"}],
        stop_conditions=[{"type": "epochs", "value": 1}],
        status="valid",
        estimated_runtime_minutes=1,
        gpu_required=False,
        resource_requirements={"memory_mb": 1024},
        model_route_id="test",
        prompt_id="test",
    )
    session.add(spec)
    session.flush()

    workspace = tmp_path / "workspace"
    code_dir = workspace / "generated_runs"
    code_dir.mkdir(parents=True)
    run = RunRecordModel(
        public_id=generate_public_id("run"),
        cycle_id=cycle.id,
        experiment_spec_id=spec.id,
        status="failed",
        execution_profile="cpu-small",
        image="python:3.12-slim",
        command=["python", "train.py"],
        hardware_profile="cpu-small",
        timeout_seconds=60,
        memory_limit_mb=1024,
        workspace_path=str(workspace),
        artifact_root=str(tmp_path / "artifacts"),
        stdout_path=str(tmp_path / "stdout.log"),
        stderr_path=str(tmp_path / "stderr.log"),
        failure_classification=failure_classification,
        last_error="boom",
        latest_resource_snapshot={"memory": "1GiB"},
    )
    session.add(run)
    session.flush()

    run_dir = workspace / "generated_runs" / run.public_id
    run_dir.mkdir(parents=True)
    (run_dir / "train.py").write_text("print('hello')\n", encoding="utf-8")
    Path(run.stderr_path).write_text("RuntimeError: boom\n", encoding="utf-8")
    Path(run.stdout_path).write_text("", encoding="utf-8")

    job = JobModel(
        public_id=generate_public_id("job"),
        cycle_id=cycle.id,
        operator_name="auto_remediate",
        status="pending",
        payload={"run_public_id": run.public_id},
        attempts=0,
        max_attempts=3,
    )
    session.add(job)
    session.commit()
    return cycle, run, job


# ---------------------------------------------------------------------------
# Test: determine_prompt_mode
# ---------------------------------------------------------------------------


class TestDeterminePromptMode:
    def test_focused_for_known_failure_first_attempt(self) -> None:
        policy = _default_policy()
        assert determine_prompt_mode("dependency_failure", 1, policy) == "focused"
        assert determine_prompt_mode("runtime_exception", 1, policy) == "focused"
        assert determine_prompt_mode("metric_parse_failure", 1, policy) == "focused"
        assert determine_prompt_mode("invalid_artifact_output", 1, policy) == "focused"

    def test_escalation_after_threshold(self) -> None:
        policy = _default_policy()  # escalate_to_full_debug_after=1
        assert determine_prompt_mode("dependency_failure", 1, policy) == "focused"
        assert determine_prompt_mode("dependency_failure", 2, policy) == "full_debug"

    def test_full_debug_classes_always_full(self) -> None:
        policy = _default_policy()
        assert determine_prompt_mode("timeout", 1, policy) == "full_debug"
        assert determine_prompt_mode("oom_or_resource_limit", 1, policy) == "full_debug"

    def test_unknown_class_defaults_to_full_debug(self) -> None:
        policy = _default_policy()
        assert determine_prompt_mode("some_new_failure", 1, policy) == "full_debug"


# ---------------------------------------------------------------------------
# Test: Remediation primitives
# ---------------------------------------------------------------------------


class TestRemediationPrimitives:
    def test_apply_code_patch_writes_file(self, tmp_path: Path) -> None:
        run_id = "run_test123"
        code_dir = tmp_path / "generated_runs" / run_id
        code_dir.mkdir(parents=True)
        (code_dir / "train.py").write_text("original code", encoding="utf-8")

        result = apply_code_patch(tmp_path, run_id, "patched code")

        assert result == code_dir / "train.py"
        assert result.read_text(encoding="utf-8") == "patched code"

    def test_apply_code_patch_creates_if_missing(self, tmp_path: Path) -> None:
        run_id = "run_new"
        result = apply_code_patch(tmp_path, run_id, "new code")
        assert result.exists()
        assert result.read_text(encoding="utf-8") == "new code"

    def test_apply_dependency_adds_merges(self) -> None:
        run = MagicMock()
        run.build_recipe = {"pip_packages": ["numpy==1.24"]}
        run.public_id = "run_x"

        apply_dependency_adds(run, ["torch==2.3.1"])

        assert "torch==2.3.1" in run.build_recipe["pip_packages"]
        assert "numpy==1.24" in run.build_recipe["pip_packages"]

    def test_apply_dependency_adds_noop_empty(self) -> None:
        run = MagicMock()
        run.build_recipe = {"pip_packages": ["numpy"]}
        apply_dependency_adds(run, [])
        # build_recipe should not have been reassigned
        assert run.build_recipe == {"pip_packages": ["numpy"]}

    def test_apply_env_changes_merges(self) -> None:
        run = MagicMock()
        run.env_vars = {"EXISTING": "1"}
        run.public_id = "run_x"

        apply_env_changes(run, {"NEW_VAR": "hello"})

        assert run.env_vars == {"EXISTING": "1", "NEW_VAR": "hello"}

    def test_apply_spec_mutations_whitelist(self) -> None:
        spec = MagicMock()
        spec.resource_requirements = {}

        applied = apply_spec_mutations(spec, {"resource_requirements": {"memory_mb": 4096}})
        assert spec.resource_requirements == {"memory_mb": 4096}
        assert applied == {"resource_requirements": {"memory_mb": 4096}}

    def test_apply_spec_mutations_blocks_non_whitelisted(self) -> None:
        spec = MagicMock()
        spec.title = "Original"

        applied = apply_spec_mutations(spec, {"title": "Hacked"})
        # title should NOT have been changed because it's not in whitelist
        assert spec.title == "Original"
        assert applied == {}

    def test_apply_run_mutations_updates_profile_and_runtime_fields(self, tmp_path: Path) -> None:
        config = _build_config(tmp_path)
        run = MagicMock()
        run.public_id = "run_x"
        run.execution_profile = "cpu-small"
        run.image = "python:3.12-slim"
        run.hardware_profile = "cpu-small"
        run.timeout_seconds = 60
        run.memory_limit_mb = 1024
        run.cpu_limit = "2"
        run.gpu_enabled = False
        run.network_mode = "disabled"

        applied = apply_run_mutations(
            config,
            run,
            {
                "execution_profile": "gpu-small",
                "timeout_seconds": 900,
                "memory_limit_mb": 8192,
            },
        )

        assert run.execution_profile == "gpu-small"
        assert run.gpu_enabled is True
        assert run.timeout_seconds == 900
        assert run.memory_limit_mb == 8192
        assert applied["execution_profile"] == "gpu-small"
        assert applied["gpu_enabled"] is True

    def test_apply_run_mutations_rejects_unknown_or_blocked_profile(self, tmp_path: Path) -> None:
        config = _build_config(tmp_path)
        run = MagicMock()
        run.public_id = "run_x"
        run.execution_profile = "cpu-small"
        run.image = "python:3.12-slim"
        run.hardware_profile = "cpu-small"
        run.timeout_seconds = 60
        run.memory_limit_mb = 1024
        run.cpu_limit = "2"
        run.gpu_enabled = False
        run.network_mode = "disabled"

        unknown = apply_run_mutations(config, run, {"execution_profile": "missing"})
        blocked = apply_run_mutations(config, run, {"execution_profile": "restricted-net"})

        assert unknown == {}
        assert blocked == {}
        assert run.execution_profile == "cpu-small"

    def test_prepare_run_for_retry(self) -> None:
        run = MagicMock()
        run.status = "failed"
        run.remediation_count = 1
        run.is_remediated_run = False
        run.attempt_count = 2
        run.prompt_lineage = [{"prompt_id": "p1"}]
        run.model_lineage = [{"mode": "original"}]

        response = RemediationResponse(
            diagnosis="test",
            fix_type="code_patch",
            fix_description="fix",
        )
        prepare_run_for_retry(run, response, "prompts/remediation/v1/focused_fix.md")

        assert run.status == "ready_to_execute"
        assert run.last_error is None
        assert run.remediation_count == 2
        assert run.is_remediated_run is True
        assert run.attempt_count == 3
        assert len(run.prompt_lineage) == 2
        assert run.prompt_lineage[-1]["mode"] == "auto_remediation"

    def test_prepare_run_for_retry_can_skip_attempt_increment(self) -> None:
        run = MagicMock()
        run.status = "failed"
        run.remediation_count = 0
        run.is_remediated_run = False
        run.attempt_count = 2
        run.prompt_lineage = []
        run.model_lineage = []

        response = RemediationResponse(
            diagnosis="test",
            fix_type="spec_mutation",
            fix_description="fix",
        )
        prepare_run_for_retry(
            run,
            response,
            "prompts/remediation/v1/focused_fix.md",
            increment_attempt_count=False,
        )

        assert run.remediation_count == 1
        assert run.attempt_count == 2

    def test_read_code_from_workspace(self, tmp_path: Path) -> None:
        run_id = "run_abc"
        code_dir = tmp_path / "generated_runs" / run_id
        code_dir.mkdir(parents=True)
        (code_dir / "train.py").write_text("x" * 100, encoding="utf-8")

        result = read_code_from_workspace(str(tmp_path), run_id, 50)
        assert len(result) == 50

    def test_read_log_tail(self, tmp_path: Path) -> None:
        log_file = tmp_path / "stderr.log"
        log_file.write_text("A" * 500, encoding="utf-8")

        result = read_log_tail(str(log_file), 100)
        assert len(result) == 100
        assert result == "A" * 100

    def test_read_log_tail_missing_file(self) -> None:
        assert read_log_tail("/nonexistent/path", 100) == ""

    def test_read_log_tail_none_path(self) -> None:
        assert read_log_tail(None, 100) == ""


# ---------------------------------------------------------------------------
# Test: build_remediation_prompt
# ---------------------------------------------------------------------------


class TestBuildRemediationPrompt:
    def test_focused_prompt_renders(self) -> None:
        policy = _default_policy()
        rendered, prompt_id = build_remediation_prompt(
            mode="focused",
            charter_problem="Classify images",
            experiment_title="CNN Baseline",
            experiment_objective="Train CNN",
            method_description="Standard CNN",
            expected_outputs=[],
            metrics=[],
            failure_classification="dependency_failure",
            exit_code=1,
            last_error="ModuleNotFoundError: No module named 'torch'",
            stderr_excerpt="ModuleNotFoundError: No module named 'torch'",
            stdout_excerpt="",
            generated_code="import torch",
            artifact_manifest={},
            resource_snapshot={},
            verification_summary=None,
            prior_attempts=[],
            attempt_number=1,
            run_status="failed",
            attempt_count=1,
            policy=policy,
        )
        assert "dependency_failure" in rendered
        assert "torch" in rendered
        assert prompt_id == "prompts/remediation/v1/focused_fix.md"

    def test_full_debug_prompt_renders(self) -> None:
        policy = _default_policy()
        rendered, prompt_id = build_remediation_prompt(
            mode="full_debug",
            charter_problem="Test problem",
            experiment_title="Test",
            experiment_objective="Test",
            method_description="Test",
            expected_outputs=[{"name": "metrics.json"}],
            metrics=[{"name": "accuracy", "higher_is_better": True}],
            failure_classification="timeout",
            exit_code=None,
            last_error="timeout",
            stderr_excerpt="",
            stdout_excerpt="",
            generated_code="pass",
            artifact_manifest={},
            resource_snapshot={},
            verification_summary="Verification rejected",
            prior_attempts=[],
            attempt_number=1,
            run_status="failed",
            attempt_count=1,
            policy=policy,
        )
        assert "expert ML debugger" in rendered
        assert prompt_id == "prompts/remediation/v1/full_debug.md"


# ---------------------------------------------------------------------------
# Test: call_debugger
# ---------------------------------------------------------------------------


class TestCallDebugger:
    def test_parses_valid_response(self) -> None:
        gateway = MagicMock()
        gateway.call_structured.return_value = {
            "diagnosis": "Missing torch",
            "fix_type": "dependency_add",
            "fix_description": "Add torch",
            "dependency_adds": ["torch==2.3.1"],
        }

        result = call_debugger(gateway, "prompt text")

        assert isinstance(result, RemediationResponse)
        assert result.fix_type == "dependency_add"
        assert result.dependency_adds == ["torch==2.3.1"]
        gateway.call_structured.assert_called_once()


# ---------------------------------------------------------------------------
# Test: RemediationPolicyConfig
# ---------------------------------------------------------------------------


class TestRemediationPolicy:
    def test_load_from_yaml_section(self) -> None:
        raw = {
            "remediation": {
                "enabled": False,
                "max_attempts_per_run": 5,
            }
        }
        policy = load_remediation_policy(raw)
        assert policy.enabled is False
        assert policy.max_attempts_per_run == 5

    def test_defaults_when_section_missing(self) -> None:
        policy = load_remediation_policy({})
        assert policy.enabled is True
        assert policy.max_attempts_per_run == 3


# ---------------------------------------------------------------------------
# Test: build_prior_attempts_summary
# ---------------------------------------------------------------------------


class TestBuildPriorAttemptsSummary:
    def test_loads_remediation_actions(self, tmp_path: Path) -> None:
        session = _build_session(tmp_path)
        charter = ResearchCharterModel(
            public_id=generate_public_id("ch"),
            title="Test",
            problem_statement="Test",
        )
        session.add(charter)
        session.flush()

        cycle = ResearchCycleModel(
            public_id=generate_public_id("cy"),
            charter_id=charter.id,
            current_status="running",
        )
        session.add(cycle)
        session.flush()

        hyp = HypothesisCardModel(
            public_id=generate_public_id("hyp"),
            cycle_id=cycle.id,
            title="H1",
            statement="S",
            rationale="R",
            approach_summary="A",
            status="active",
            model_route_id="test",
            prompt_id="test",
        )
        session.add(hyp)
        session.flush()

        spec = ExperimentSpecModel(
            public_id=generate_public_id("spec"),
            cycle_id=cycle.id,
            hypothesis_card_id=hyp.id,
            title="Spec",
            objective="Obj",
            baseline_description="Base",
            method_description="Method",
            status="valid",
            model_route_id="test",
            prompt_id="test",
        )
        session.add(spec)
        session.flush()

        run = RunRecordModel(
            public_id=generate_public_id("run"),
            cycle_id=cycle.id,
            experiment_spec_id=spec.id,
            status="failed",
            execution_profile="cpu-small",
            image="test",
            command=["python", "train.py"],
            hardware_profile="cpu-small",
            timeout_seconds=300,
            memory_limit_mb=1024,
            workspace_path="/tmp/ws",
            artifact_root="/tmp/artifacts",
        )
        session.add(run)
        session.flush()

        action = RemediationActionModel(
            public_id=generate_public_id("remed"),
            cycle_id=cycle.id,
            run_record_id=run.id,
            attempt_number=1,
            failure_classification="dependency_failure",
            prompt_mode="focused",
            prompt_id="prompts/remediation/v1/focused_fix.md",
            model_route_id="local-debugger",
            diagnosis="Missing torch",
            fix_type="dependency_add",
            fix_description="Added torch",
            outcome="applied",
        )
        session.add(action)
        session.commit()

        summary = build_prior_attempts_summary(session, run.id)
        assert len(summary) == 1
        assert summary[0]["diagnosis"] == "Missing torch"
        assert summary[0]["attempt_number"] == 1


# ---------------------------------------------------------------------------
# Test: Pipeline integration
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    def test_auto_remediate_in_registry(self) -> None:
        from libs.orchestration.operators import OPERATOR_REGISTRY

        assert "auto_remediate" in OPERATOR_REGISTRY

    def test_auto_remediate_in_pipeline(self) -> None:
        from libs.orchestration.worker import OPERATOR_PIPELINES

        pipeline = OPERATOR_PIPELINES["verification"]
        assert "auto_remediate" in pipeline
        assert pipeline.index("auto_remediate") < pipeline.index("failure_postmortem")
        assert pipeline.index("run_verify") < pipeline.index("auto_remediate")

    def test_auto_remediate_routes_to_run_prepare_when_spec_mutations_applied(
        self, tmp_path: Path
    ) -> None:
        from libs.orchestration.operators import auto_remediate_operator

        session = _build_session(tmp_path)
        config = _build_config(tmp_path)
        cycle, run, job = _build_run_fixture(session, tmp_path)

        gateway = MagicMock()
        gateway.call_structured.return_value = {
            "diagnosis": "Need to update run config",
            "fix_type": "spec_mutation",
            "fix_description": "Increase GPU requirement in spec",
            "spec_mutations": {"gpu_required": True},
        }
        gateway.resolve_route.return_value = MagicMock(id="local-debugger")

        with patch(
            "libs.orchestration.operators.ModelGateway.from_config",
            return_value=gateway,
        ):
            result = auto_remediate_operator(session, config, SYSTEM_ACTOR, cycle, job)

        session.refresh(run)
        assert result.next_actions[0].action == "run_prepare"
        assert run.remediation_count == 1
        assert run.attempt_count == 0
        spec = session.get(ExperimentSpecModel, run.experiment_spec_id)
        assert spec.gpu_required is True

    def test_auto_remediate_routes_to_run_execute_when_only_run_mutations_applied(
        self, tmp_path: Path
    ) -> None:
        from libs.orchestration.operators import auto_remediate_operator

        session = _build_session(tmp_path)
        config = _build_config(tmp_path)
        cycle, run, job = _build_run_fixture(session, tmp_path)

        gateway = MagicMock()
        gateway.call_structured.return_value = {
            "diagnosis": "Needs more time",
            "fix_type": "env_change",
            "fix_description": "Extend timeout",
            "run_mutations": {"timeout_seconds": 900},
        }
        gateway.resolve_route.return_value = MagicMock(id="local-debugger")

        with patch(
            "libs.orchestration.operators.ModelGateway.from_config",
            return_value=gateway,
        ):
            result = auto_remediate_operator(session, config, SYSTEM_ACTOR, cycle, job)

        session.refresh(run)
        assert result.next_actions[0].action == "run_execute"
        assert run.timeout_seconds == 900
        assert run.remediation_count == 1
        assert run.attempt_count == 1


# ---------------------------------------------------------------------------
# Test: Failure memory semantics
# ---------------------------------------------------------------------------


class TestFailureMemorySemantics:
    def _build_cycle_with_runs(
        self, session: Session, *, remediated: bool
    ) -> tuple[ResearchCycleModel, RunRecordModel]:
        from libs.storage.models import FailurePostmortemModel

        charter = ResearchCharterModel(
            public_id=generate_public_id("ch"),
            title="Test Charter",
            problem_statement="Test",
        )
        session.add(charter)
        session.flush()

        cycle = ResearchCycleModel(
            public_id=generate_public_id("cy"),
            charter_id=charter.id,
            current_status="running",
        )
        session.add(cycle)
        session.flush()

        hyp = HypothesisCardModel(
            public_id=generate_public_id("hyp"),
            cycle_id=cycle.id,
            title="Test Hypothesis",
            statement="S",
            rationale="R",
            approach_summary="A",
            status="active",
            model_route_id="test",
            prompt_id="test",
        )
        session.add(hyp)
        session.flush()

        spec = ExperimentSpecModel(
            public_id=generate_public_id("spec"),
            cycle_id=cycle.id,
            hypothesis_card_id=hyp.id,
            title="Test Hypothesis",
            objective="Obj",
            baseline_description="Base",
            method_description="Method",
            status="valid",
            model_route_id="test",
            prompt_id="test",
        )
        session.add(spec)
        session.flush()

        run = RunRecordModel(
            public_id=generate_public_id("run"),
            cycle_id=cycle.id,
            experiment_spec_id=spec.id,
            status="failed",
            execution_profile="cpu-small",
            image="test",
            command=["python", "train.py"],
            hardware_profile="cpu-small",
            timeout_seconds=300,
            memory_limit_mb=1024,
            workspace_path="/tmp/ws",
            artifact_root="/tmp/artifacts",
            is_remediated_run=remediated,
        )
        session.add(run)
        session.flush()

        # Create postmortems to trigger the penalty
        for i in range(3):
            pm = FailurePostmortemModel(
                public_id=generate_public_id("pm"),
                cycle_id=cycle.id,
                run_record_id=run.id,
                failure_class="runtime_exception",
                failure_stage="execution",
                root_cause_summary=f"Failure {i}",
                model_route_id="test",
                prompt_id="test",
            )
            session.add(pm)
        session.commit()

        return cycle, run

    def test_remediated_runs_still_contribute_when_postmortem_exists(self, tmp_path: Path) -> None:
        from libs.verification.failure_memory import get_hypothesis_failure_caution

        session = _build_session(tmp_path)
        cycle, run = self._build_cycle_with_runs(session, remediated=True)

        result = get_hypothesis_failure_caution(
            session,
            charter_id=cycle.charter_id,
            hypothesis_title="Test Hypothesis",
        )
        assert result is not None
        assert result["repeat_count"] == 3

    def test_non_remediated_runs_still_penalized(self, tmp_path: Path) -> None:
        from libs.verification.failure_memory import get_hypothesis_failure_caution

        session = _build_session(tmp_path)
        cycle, run = self._build_cycle_with_runs(session, remediated=False)

        result = get_hypothesis_failure_caution(
            session,
            charter_id=cycle.charter_id,
            hypothesis_title="Test Hypothesis",
        )
        # Non-remediated runs should trigger penalty (3 postmortems)
        assert result is not None
        assert result["repeat_count"] == 3
