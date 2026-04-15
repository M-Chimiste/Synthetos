"""Focused Phase 3 runtime and verification tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from uuid_utils import uuid7

from libs.core.operators import OperatorInput
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
    def __init__(self, hypothesis_session, charter, cards):
        self.hypothesis_session = hypothesis_session
        self.charter = charter
        self.cards = cards

    def get(self, model, key):
        if str(key) == str(self.hypothesis_session.id):
            return self.hypothesis_session
        if str(key) == str(self.hypothesis_session.charter_id):
            return self.charter
        return None

    def execute(self, _query):
        return _FakeScalarResult(self.cards)

    def add(self, _obj):
        return None

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
    def __init__(self, run, spec):
        self.run = run
        self.spec = spec
        self.committed = False

    def get(self, model, key):
        if key == self.spec.id:
            return self.spec
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
