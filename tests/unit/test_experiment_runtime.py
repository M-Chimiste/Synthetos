"""Focused Phase 3 runtime and verification tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from uuid_utils import uuid7

from libs.analysis.operators import evidence as evidence_operator
from libs.core.container_images import BLACKWELL_PYTORCH_IMAGE
from libs.core.operators import OperatorInput
from libs.core.types import CycleStatus
from libs.execution.operators import setup as setup_operator
from libs.protocols.operators import compile as compile_operator
from libs.verification.operators import check as verification_check


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value


class _FakeCompileSession:
    def __init__(self, hypothesis_session, charter, cards, cycle=None):
        self.hypothesis_session = hypothesis_session
        self.charter = charter
        self.cards = cards
        self.cycle = cycle
        self.added: list[object] = []

    def get(self, model, key):
        if str(key) == str(self.hypothesis_session.id):
            return self.hypothesis_session
        if str(key) == str(self.hypothesis_session.charter_id):
            return self.charter
        if self.cycle is not None and str(key) == str(self.cycle.id):
            return self.cycle
        return None

    def execute(self, _query):
        return _FakeScalarResult(self.cards)

    def add(self, _obj):
        self.added.append(_obj)

    def commit(self):
        return None


class _FakeFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeSetupSession:
    def __init__(self, run, spec, cycle=None, goal=None):
        self.run = run
        self.spec = spec
        self.cycle = cycle
        self.goal = goal
        self.committed = False

    def get(self, model, key):
        if key == self.spec.id:
            return self.spec
        if self.cycle is not None and key == self.cycle.id:
            return self.cycle
        if self.goal is not None and str(key) == str(self.goal.id):
            return self.goal
        return None

    def flush(self):
        return None

    def commit(self):
        self.committed = True


class _FakeEvidenceSession:
    def __init__(self, analysis, packet, chunks, nodes, paper, cycle):
        self.analysis = analysis
        self.packet = packet
        self.chunks = chunks
        self.nodes = nodes
        self.paper = paper
        self.cycle = cycle
        self._execute_calls = 0
        self.committed = False

    def execute(self, _query):
        self._execute_calls += 1
        values = {
            1: self.packet,
            2: self.chunks,
            3: self.nodes,
            4: self.paper,
        }
        return _FakeScalarResult(values[self._execute_calls])

    def get(self, _model, key):
        if str(key) == str(self.cycle.id):
            return self.cycle
        return None

    def flush(self):
        return None

    def commit(self):
        self.committed = True


def test_protocol_compile_rejects_out_of_scope_card_ids(monkeypatch) -> None:
    hypothesis_session = SimpleNamespace(
        id=uuid7(),
        cycle_id=uuid7(),
        charter_id=uuid7(),
    )
    charter = SimpleNamespace(problem_statement="test problem")
    fake_session = _FakeCompileSession(hypothesis_session, charter, cards=[])

    monkeypatch.setattr(
        compile_operator,
        "get_sync_session_factory",
        lambda: _FakeFactory(fake_session),
    )

    op_input = OperatorInput(
        cycle_id=UUID(str(hypothesis_session.cycle_id)),
        charter_id=UUID(str(hypothesis_session.charter_id)),
        job_id=uuid7(),
        job_type="protocol_compile",
        payload={
            "hypothesis_session_id": str(hypothesis_session.id),
            "hypothesis_card_ids": [str(uuid7())],
        },
    )

    result = compile_operator.protocol_compile_operator(op_input)

    assert result.success is False
    assert "out of scope" in (result.error or "")


def test_analysis_evidence_marks_cycle_evidence_ready(monkeypatch) -> None:
    analysis = SimpleNamespace(
        id=uuid7(),
        cycle_id=uuid7(),
        charter_id=uuid7(),
        paper_card_id=uuid7(),
        status="reviewed",
        budget={},
        stats={},
        step_log=[],
        completed_at=None,
    )
    packet = SimpleNamespace(id=uuid7(), analysis_session_id=analysis.id)
    paper = SimpleNamespace(id=analysis.paper_card_id, analysis_status="analyzing")
    cycle = SimpleNamespace(
        id=analysis.cycle_id,
        status=CycleStatus.analysis_ready.value,
    )
    fake_session = _FakeEvidenceSession(
        analysis=analysis,
        packet=packet,
        chunks=[],
        nodes=[],
        paper=paper,
        cycle=cycle,
    )

    monkeypatch.setattr(
        evidence_operator,
        "get_sync_session_factory",
        lambda: _FakeFactory(fake_session),
    )
    monkeypatch.setattr(
        evidence_operator,
        "load_analysis_session",
        lambda _db, _session_id: analysis,
    )
    monkeypatch.setattr(evidence_operator, "emit_event_sync", lambda *a, **kw: None)

    async def fake_extract_evidence(*_args, **_kwargs):
        return [
            SimpleNamespace(contradiction_flags={}, redundancy_group=None),
            SimpleNamespace(contradiction_flags={"contradicts": True}, redundancy_group="g1"),
        ]

    import libs.analysis.evidence_extraction as evidence_extraction

    monkeypatch.setattr(evidence_extraction, "extract_evidence", fake_extract_evidence)

    result = evidence_operator.analysis_evidence_operator(
        OperatorInput(
            cycle_id=UUID(str(analysis.cycle_id)),
            charter_id=UUID(str(analysis.charter_id)),
            job_id=uuid7(),
            job_type="analysis_evidence",
            payload={"analysis_session_id": str(analysis.id)},
        )
    )

    assert result.success is True
    assert cycle.status == CycleStatus.evidence_ready.value
    assert analysis.status == "completed"
    assert analysis.stats["evidence_card_count"] == 2
    assert analysis.stats["contradiction_count"] == 1
    assert analysis.stats["redundancy_count"] == 1
    assert paper.analysis_status == "analyzed"
    assert fake_session.committed is True


def test_protocol_compile_persists_agent_authored_build_recipe(monkeypatch) -> None:
    hypothesis_session = SimpleNamespace(
        id=uuid7(),
        cycle_id=uuid7(),
        charter_id=uuid7(),
    )
    charter = SimpleNamespace(problem_statement="test problem")
    card = SimpleNamespace(
        id=uuid7(),
        title="Try a dependency",
        statement="Use numpy",
        rationale="Needs a package",
        novelty_score=0.7,
        feasibility_score=0.8,
        impact_score=0.6,
        status="candidate",
        updated_at=None,
    )
    fake_session = _FakeCompileSession(hypothesis_session, charter, cards=[card])

    monkeypatch.setattr(
        compile_operator,
        "get_sync_session_factory",
        lambda: _FakeFactory(fake_session),
    )
    monkeypatch.setattr(
        compile_operator,
        "load_skill_prompt",
        lambda *_args, **_kwargs: SimpleNamespace(prompt=None),
    )
    monkeypatch.setattr(compile_operator, "record_skill_usage", lambda *a, **kw: None)
    monkeypatch.setattr(compile_operator, "record_model_call", lambda *a, **kw: None)
    monkeypatch.setattr(compile_operator, "emit_event_sync", lambda *a, **kw: None)

    dockerfile_content = "FROM python:3.12-slim\nRUN pip install numpy\n"

    async def fake_compile_specs(*_args, **_kwargs):
        return (
            compile_operator._SpecSet(
                specs=[
                    compile_operator._CompiledSpec(
                        title="numpy spec",
                        description="Runs with numpy",
                        baseline={"description": "baseline"},
                        metrics=[{"name": "score", "direction": "maximize"}],
                        stop_conditions=[{"type": "timeout"}],
                        code_plan={
                            "entry_point": "run_experiment.py",
                            "dependencies": ["numpy"],
                            "files": {"run_experiment.py": "print('ok')"},
                        },
                        base_image="python:3.12-slim",
                        build_recipe={"dockerfile_content": dockerfile_content},
                    )
                ]
            ),
            {"provider": "test", "model": "test"},
        )

    monkeypatch.setattr(compile_operator, "_compile_specs", fake_compile_specs)

    result = compile_operator.protocol_compile_operator(
        OperatorInput(
            cycle_id=UUID(str(hypothesis_session.cycle_id)),
            charter_id=UUID(str(hypothesis_session.charter_id)),
            job_id=uuid7(),
            job_type="protocol_compile",
            payload={"hypothesis_session_id": str(hypothesis_session.id)},
        )
    )

    assert result.success is True
    specs = [
        obj
        for obj in fake_session.added
        if obj.__class__.__name__ == "ExperimentSpec"
    ]
    assert len(specs) == 1
    assert specs[0].status == "validated"
    assert specs[0].build_recipe == {"dockerfile_content": dockerfile_content}


def test_protocol_compile_strips_noop_synthetos_build_recipe(monkeypatch) -> None:
    hypothesis_session = SimpleNamespace(
        id=uuid7(),
        cycle_id=uuid7(),
        charter_id=uuid7(),
    )
    charter = SimpleNamespace(problem_statement="test problem")
    card = SimpleNamespace(
        id=uuid7(),
        title="Use preloaded torch",
        statement="Train a tiny model",
        rationale="Torch is already in synthetos",
        novelty_score=0.7,
        feasibility_score=0.8,
        impact_score=0.6,
        status="candidate",
        updated_at=None,
    )
    fake_session = _FakeCompileSession(hypothesis_session, charter, cards=[card])

    monkeypatch.setattr(
        compile_operator,
        "get_sync_session_factory",
        lambda: _FakeFactory(fake_session),
    )
    monkeypatch.setattr(
        compile_operator,
        "load_skill_prompt",
        lambda *_args, **_kwargs: SimpleNamespace(prompt=None),
    )
    monkeypatch.setattr(compile_operator, "record_skill_usage", lambda *a, **kw: None)
    monkeypatch.setattr(compile_operator, "record_model_call", lambda *a, **kw: None)
    monkeypatch.setattr(compile_operator, "emit_event_sync", lambda *a, **kw: None)

    async def fake_compile_specs(*_args, **_kwargs):
        return (
            compile_operator._SpecSet(
                specs=[
                    compile_operator._CompiledSpec(
                        title="torch spec",
                        description="Runs with preloaded torch",
                        baseline={"description": "baseline"},
                        metrics=[{"name": "score", "direction": "maximize"}],
                        stop_conditions=[{"type": "timeout"}],
                        code_plan={
                            "entry_point": "run_experiment.py",
                            "dependencies": ["torch", "numpy"],
                            "files": {"run_experiment.py": "print('ok')"},
                        },
                        base_image="synthetos:latest",
                        build_recipe={
                            "dockerfile_content": (
                                "FROM synthetos:latest\n"
                                "RUN pip install --break-system-packages torch numpy\n"
                            )
                        },
                    )
                ]
            ),
            {"provider": "test", "model": "test"},
        )

    monkeypatch.setattr(compile_operator, "_compile_specs", fake_compile_specs)

    result = compile_operator.protocol_compile_operator(
        OperatorInput(
            cycle_id=UUID(str(hypothesis_session.cycle_id)),
            charter_id=UUID(str(hypothesis_session.charter_id)),
            job_id=uuid7(),
            job_type="protocol_compile",
            payload={
                "hypothesis_session_id": str(hypothesis_session.id),
                "base_image": "synthetos:latest",
            },
        )
    )

    assert result.success is True
    specs = [
        obj
        for obj in fake_session.added
        if obj.__class__.__name__ == "ExperimentSpec"
    ]
    assert len(specs) == 1
    assert specs[0].status == "validated"
    assert specs[0].base_image == "synthetos:latest"
    assert specs[0].build_recipe is None


def test_protocol_compile_synthesizes_missing_dependency_build_recipe(
    monkeypatch,
) -> None:
    hypothesis_session = SimpleNamespace(
        id=uuid7(),
        cycle_id=uuid7(),
        charter_id=uuid7(),
    )
    charter = SimpleNamespace(problem_statement="test problem")
    card = SimpleNamespace(
        id=uuid7(),
        title="Try pandas",
        statement="Use pandas for metrics",
        rationale="Needs a package not guaranteed in the base image",
        novelty_score=0.7,
        feasibility_score=0.8,
        impact_score=0.6,
        status="candidate",
        updated_at=None,
    )
    fake_session = _FakeCompileSession(hypothesis_session, charter, cards=[card])

    monkeypatch.setattr(
        compile_operator,
        "get_sync_session_factory",
        lambda: _FakeFactory(fake_session),
    )
    monkeypatch.setattr(
        compile_operator,
        "load_skill_prompt",
        lambda *_args, **_kwargs: SimpleNamespace(prompt=None),
    )
    monkeypatch.setattr(compile_operator, "record_skill_usage", lambda *a, **kw: None)
    monkeypatch.setattr(compile_operator, "record_model_call", lambda *a, **kw: None)
    monkeypatch.setattr(compile_operator, "emit_event_sync", lambda *a, **kw: None)

    async def fake_compile_specs(*_args, **_kwargs):
        return (
            compile_operator._SpecSet(
                specs=[
                    compile_operator._CompiledSpec(
                        title="pandas spec",
                        description="Runs with pandas",
                        baseline={"description": "baseline"},
                        metrics=[{"name": "score", "direction": "maximize"}],
                        stop_conditions=[{"type": "timeout"}],
                        code_plan={
                            "entry_point": "run_experiment.py",
                            "dependencies": ["pandas>=2"],
                            "files": {"run_experiment.py": "print('ok')"},
                        },
                        build_recipe=None,
                    )
                ]
            ),
            {"provider": "test", "model": "test"},
        )

    monkeypatch.setattr(compile_operator, "_compile_specs", fake_compile_specs)

    result = compile_operator.protocol_compile_operator(
        OperatorInput(
            cycle_id=UUID(str(hypothesis_session.cycle_id)),
            charter_id=UUID(str(hypothesis_session.charter_id)),
            job_id=uuid7(),
            job_type="protocol_compile",
            payload={"hypothesis_session_id": str(hypothesis_session.id)},
        )
    )

    assert result.success is True
    specs = [
        obj
        for obj in fake_session.added
        if obj.__class__.__name__ == "ExperimentSpec"
    ]
    assert len(specs) == 1
    assert specs[0].status == "validated"
    assert specs[0].base_image == "python:3.12-slim"
    assert specs[0].build_recipe == {
        "dockerfile_content": (
            "FROM python:3.12-slim\n"
            "RUN pip install --no-cache-dir pandas>=2\n"
        )
    }


def test_protocol_compile_gpu_defaults_to_blackwell_pytorch_image() -> None:
    normalized = compile_operator._normalize_compiled_spec(
        {
            "title": "gpu tiny torch",
            "description": "train with torch",
            "baseline": {"description": "baseline"},
            "metrics": [{"name": "loss", "direction": "minimize"}],
            "stop_conditions": [{"type": "timeout"}],
            "code_plan": {
                "entry_point": "run_experiment.py",
                "dependencies": ["torch", "numpy"],
                "files": {"run_experiment.py": "print('ok')"},
            },
            "base_image": "python:3.12-slim",
            "build_recipe": None,
        },
        fallback_base_image=None,
        hardware_profile={"gpu_required": True, "gpu_count": 1},
    )

    assert normalized["base_image"] == BLACKWELL_PYTORCH_IMAGE
    assert normalized["build_recipe"] is None


def test_protocol_compile_uses_cycle_protocol_defaults(monkeypatch) -> None:
    hypothesis_session = SimpleNamespace(
        id=uuid7(),
        cycle_id=uuid7(),
        charter_id=uuid7(),
    )
    charter = SimpleNamespace(problem_statement="test problem")
    card = SimpleNamespace(
        id=uuid7(),
        title="GPU tiny torch",
        statement="Train a tiny model",
        rationale="Needs CUDA",
        novelty_score=0.7,
        feasibility_score=0.8,
        impact_score=0.6,
        status="candidate",
        updated_at=None,
    )
    cycle = SimpleNamespace(
        id=hypothesis_session.cycle_id,
        config={
            "autonomy": {
                "protocol": {
                    "base_image": BLACKWELL_PYTORCH_IMAGE,
                    "hardware_profile": {"gpu_required": True, "gpu_count": 1},
                }
            }
        },
    )
    fake_session = _FakeCompileSession(
        hypothesis_session,
        charter,
        cards=[card],
        cycle=cycle,
    )

    monkeypatch.setattr(
        compile_operator,
        "get_sync_session_factory",
        lambda: _FakeFactory(fake_session),
    )
    monkeypatch.setattr(
        compile_operator,
        "load_skill_prompt",
        lambda *_args, **_kwargs: SimpleNamespace(prompt=None),
    )
    monkeypatch.setattr(compile_operator, "record_skill_usage", lambda *a, **kw: None)
    monkeypatch.setattr(compile_operator, "record_model_call", lambda *a, **kw: None)
    monkeypatch.setattr(compile_operator, "emit_event_sync", lambda *a, **kw: None)

    async def fake_compile_specs(*_args, **_kwargs):
        return (
            compile_operator._SpecSet(
                specs=[
                    compile_operator._CompiledSpec(
                        title="gpu spec",
                        description="Runs with preloaded torch",
                        baseline={"description": "baseline"},
                        metrics=[{"name": "loss", "direction": "minimize"}],
                        stop_conditions=[{"type": "timeout"}],
                        code_plan={
                            "entry_point": "run_experiment.py",
                            "dependencies": ["torch", "numpy"],
                            "files": {"run_experiment.py": "print('ok')"},
                        },
                        build_recipe=None,
                    )
                ]
            ),
            {"provider": "test", "model": "test"},
        )

    monkeypatch.setattr(compile_operator, "_compile_specs", fake_compile_specs)

    result = compile_operator.protocol_compile_operator(
        OperatorInput(
            cycle_id=UUID(str(hypothesis_session.cycle_id)),
            charter_id=UUID(str(hypothesis_session.charter_id)),
            job_id=uuid7(),
            job_type="protocol_compile",
            payload={"hypothesis_session_id": str(hypothesis_session.id)},
        )
    )

    assert result.success is True
    specs = [
        obj
        for obj in fake_session.added
        if obj.__class__.__name__ == "ExperimentSpec"
    ]
    assert len(specs) == 1
    assert specs[0].base_image == BLACKWELL_PYTORCH_IMAGE
    assert specs[0].hardware_profile == {"gpu_required": True, "gpu_count": 1}
    assert specs[0].build_recipe is None


def test_execution_setup_requires_non_empty_commit_sha(monkeypatch, tmp_path: Path) -> None:
    run = SimpleNamespace(
        id=uuid7(),
        experiment_spec_id=uuid7(),
        run_number=1,
        charter_id=uuid7(),
        cycle_id=uuid7(),
        status="pending",
        started_at=None,
        workspace_path=None,
        env_vars=None,
        failure_class=None,
        error=None,
        completed_at=None,
    )
    spec = SimpleNamespace(
        id=run.experiment_spec_id,
        title="demo spec",
        code_plan={
            "files": {"run_experiment.py": "print('hi')"},
            "entry_point": "run_experiment.py",
        },
        base_image="python:3.12-slim",
        build_recipe=None,
        hardware_profile={},
    )
    fake_session = _FakeSetupSession(run, spec)

    monkeypatch.setattr(
        setup_operator,
        "get_sync_session_factory",
        lambda: _FakeFactory(fake_session),
    )
    monkeypatch.setattr(setup_operator, "load_run_record", lambda _db, _run_id: run)
    monkeypatch.setattr(setup_operator, "create_worktree", lambda **_kwargs: tmp_path)
    monkeypatch.setattr(setup_operator, "commit_worktree", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        setup_operator,
        "get_settings",
        lambda: SimpleNamespace(data_root=tmp_path, repo_root=tmp_path),
    )

    result = setup_operator.execution_setup_operator(
        OperatorInput(
            cycle_id=UUID(str(run.cycle_id)),
            charter_id=UUID(str(run.charter_id)),
            job_id=uuid7(),
            job_type="execution_setup",
            payload={"run_record_id": str(run.id)},
        )
    )

    assert result.success is False
    assert "empty commit sha" in (result.error or "")
    assert fake_session.committed is True


def test_execution_setup_enforces_goal_gpu_protocol_policy(monkeypatch, tmp_path: Path) -> None:
    goal_id = uuid7()
    run = SimpleNamespace(
        id=uuid7(),
        experiment_spec_id=uuid7(),
        run_number=1,
        charter_id=uuid7(),
        cycle_id=uuid7(),
        status="pending",
        started_at=None,
        workspace_path=None,
        env_vars=None,
        image_ref=None,
        command=None,
        resource_limits=None,
        failure_class=None,
        error=None,
        completed_at=None,
    )
    spec = SimpleNamespace(
        id=run.experiment_spec_id,
        title="demo spec",
        code_plan={
            "files": {"main.py": "print('hi')"},
            "entry_point": "main.py",
        },
        base_image="python:3.12-slim",
        build_recipe={"dockerfile_content": "FROM python:3.12-slim\nRUN pip install torch\n"},
        hardware_profile={},
    )
    cycle = SimpleNamespace(
        id=run.cycle_id,
        config={"goal": {"goal_id": str(goal_id)}},
    )
    goal = SimpleNamespace(
        id=goal_id,
        policy={
            "protocol": {
                "base_image": BLACKWELL_PYTORCH_IMAGE,
                "hardware_profile": {
                    "gpu_required": True,
                    "gpu_count": 1,
                    "memory_gb": 16,
                    "timeout_seconds": 900,
                },
            }
        },
    )
    fake_session = _FakeSetupSession(run, spec, cycle=cycle, goal=goal)
    built: dict[str, str] = {}

    class _FakeRunner:
        def build_image(self, *, dockerfile_content, tag, context_path):
            built["dockerfile_content"] = dockerfile_content
            built["tag"] = tag
            return tag

    monkeypatch.setattr(
        setup_operator,
        "get_sync_session_factory",
        lambda: _FakeFactory(fake_session),
    )
    monkeypatch.setattr(setup_operator, "load_run_record", lambda _db, _run_id: run)
    monkeypatch.setattr(setup_operator, "create_worktree", lambda **_kwargs: tmp_path)
    monkeypatch.setattr(setup_operator, "commit_worktree", lambda *_args, **_kwargs: "abc123")
    monkeypatch.setattr(setup_operator, "DockerRunner", _FakeRunner)
    monkeypatch.setattr(setup_operator, "emit_event_sync", lambda *a, **kw: None)
    monkeypatch.setattr(setup_operator, "enqueue_next", lambda *a, **kw: None)
    monkeypatch.setattr(
        setup_operator,
        "get_settings",
        lambda: SimpleNamespace(data_root=tmp_path, repo_root=tmp_path),
    )

    result = setup_operator.execution_setup_operator(
        OperatorInput(
            cycle_id=UUID(str(run.cycle_id)),
            charter_id=UUID(str(run.charter_id)),
            job_id=uuid7(),
            job_type="execution_setup",
            payload={"run_record_id": str(run.id)},
        )
    )

    assert result.success is True
    assert built["dockerfile_content"].startswith(
        f"FROM {BLACKWELL_PYTORCH_IMAGE}"
    )
    assert run.resource_limits["gpu"] is True
    assert run.resource_limits["gpu_count"] == 1
    assert run.resource_limits["timeout"] == 900


def test_execution_setup_inherits_cycle_compute_cap_gpu(monkeypatch, tmp_path: Path) -> None:
    run = SimpleNamespace(
        id=uuid7(),
        experiment_spec_id=uuid7(),
        run_number=1,
        charter_id=uuid7(),
        cycle_id=uuid7(),
        status="pending",
        started_at=None,
        workspace_path=None,
        env_vars=None,
        image_ref=None,
        command=None,
        resource_limits={"gpu": False, "gpu_count": 1, "memory": "48g", "timeout": 3600},
        failure_class=None,
        error=None,
        completed_at=None,
    )
    spec = SimpleNamespace(
        id=run.experiment_spec_id,
        title="demo spec",
        code_plan={
            "files": {"main.py": "print('hi')"},
            "entry_point": "main.py",
        },
        base_image="python:3.12-slim",
        build_recipe=None,
        hardware_profile={},
    )
    cycle = SimpleNamespace(
        id=run.cycle_id,
        config={
            "autonomy": {
                "compute_cap": {
                    "gpu": True,
                    "gpu_count": 1,
                    "memory_gb": 48,
                    "timeout_seconds": 1200,
                }
            }
        },
    )
    fake_session = _FakeSetupSession(run, spec, cycle=cycle)

    monkeypatch.setattr(
        setup_operator,
        "get_sync_session_factory",
        lambda: _FakeFactory(fake_session),
    )
    monkeypatch.setattr(setup_operator, "load_run_record", lambda _db, _run_id: run)
    monkeypatch.setattr(setup_operator, "create_worktree", lambda **_kwargs: tmp_path)
    monkeypatch.setattr(setup_operator, "commit_worktree", lambda *_args, **_kwargs: "abc123")
    monkeypatch.setattr(setup_operator, "emit_event_sync", lambda *a, **kw: None)
    monkeypatch.setattr(setup_operator, "enqueue_next", lambda *a, **kw: None)
    monkeypatch.setattr(
        setup_operator,
        "get_settings",
        lambda: SimpleNamespace(data_root=tmp_path, repo_root=tmp_path),
    )

    result = setup_operator.execution_setup_operator(
        OperatorInput(
            cycle_id=UUID(str(run.cycle_id)),
            charter_id=UUID(str(run.charter_id)),
            job_id=uuid7(),
            job_type="execution_setup",
            payload={"run_record_id": str(run.id)},
        )
    )

    assert result.success is True
    assert run.image_ref == BLACKWELL_PYTORCH_IMAGE
    assert run.resource_limits["gpu"] is True
    assert run.resource_limits["gpu_count"] == 1
    assert run.resource_limits["memory"] == "48g"


def test_output_contract_and_metric_sanity_are_populated() -> None:
    output_contract = verification_check._build_output_contract(
        artifact_manifest=[
            {"name": "metrics.json", "path": "metrics.json", "size_bytes": 42, "hash": "abc123"},
        ],
        expected_artifacts=[{"name": "metrics.json", "type": "json", "required": True}],
    )
    metric_sanity = verification_check._build_metric_sanity(
        run_metrics={"accuracy": 0.91, "loss": 0.2},
        spec_metrics=[
            {"name": "accuracy", "direction": "maximize", "min": 0.0, "max": 1.0},
            {"name": "loss", "direction": "minimize", "min": 0.0, "max": 1.0},
        ],
        prior_metrics={"accuracy": 0.88},
    )

    assert output_contract["checks"][0]["pass"] is True
    assert any(check["name"] == "accuracy" for check in metric_sanity["checks"])
    assert all("detail" in check for check in metric_sanity["checks"])


def test_output_contract_accepts_path_only_expected_artifacts() -> None:
    output_contract = verification_check._build_output_contract(
        artifact_manifest=[
            {"name": "model_weights.pt", "path": "model_weights.pt", "size_bytes": 42},
        ],
        expected_artifacts=[
            {
                "path": "/artifacts/model_weights.pt",
                "type": "pt",
                "required": True,
            }
        ],
    )

    assert output_contract["checks"] == [
        {
            "name": "model_weights.pt",
            "pass": True,
            "detail": "expected type pt, found path model_weights.pt",
        }
    ]


def test_verification_failure_class_prefers_invalid_artifact() -> None:
    failure_class = verification_check._classify_verification_failure(
        failed_metrics=["memory_savings_pct"],
        failed_artifacts=["model_weights.pt"],
        failed_output_checks=["model_weights.pt"],
        failed_sanity_checks=[],
    )

    assert failure_class == "invalid_artifact"


def test_verification_failure_class_metric_threshold_without_contract_failures() -> None:
    failure_class = verification_check._classify_verification_failure(
        failed_metrics=["memory_savings_pct"],
        failed_artifacts=[],
        failed_output_checks=[],
        failed_sanity_checks=[],
    )

    assert failure_class == "metric_threshold"
