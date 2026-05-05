"""Focused build remediation must create concrete retry overrides."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from uuid_utils import uuid7

from libs.core.operators import OperatorInput
from libs.remediation.operators import remediate as remediate_operator
from libs.storage.models.experiment import RunRecord
from libs.storage.models.remediation import RemediationAction


class _FakeRemediationSession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.committed = False

    def get(self, _model: Any, _key: Any) -> Any:
        return SimpleNamespace(config=None)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.committed = True


class _FakeFactory:
    def __init__(self, session: _FakeRemediationSession) -> None:
        self._session = session

    def __call__(self) -> _FakeFactory:
        return self

    def __enter__(self) -> _FakeRemediationSession:
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _op_input(run: Any) -> OperatorInput:
    return OperatorInput(
        cycle_id=UUID(str(run.cycle_id)),
        charter_id=UUID(str(run.charter_id)),
        job_id=uuid7(),
        job_type="auto_remediate",
        payload={"run_record_id": str(run.id)},
    )


def _build_run_and_spec(tmp_path: Path) -> tuple[Any, Any]:
    run_id = uuid7()
    spec_id = uuid7()
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "build.log").write_text("docker build failed loudly", encoding="utf-8")
    run = SimpleNamespace(
        id=run_id,
        experiment_spec_id=spec_id,
        parent_run_id=None,
        charter_id=uuid7(),
        cycle_id=uuid7(),
        run_number=1,
        status="failed",
        workspace_path=str(worktree),
        resource_limits=None,
        failure_class="build",
        error="image build failed: manifest unknown",
        stdout_path=None,
        stderr_path=None,
        artifact_manifest=None,
    )
    spec = SimpleNamespace(
        id=spec_id,
        title="broken build",
        description="spec with broken dockerfile",
        code_plan={"files": {"run_experiment.py": "print('hi')"}},
        build_recipe={"dockerfile_content": "FROM broken:latest\nRUN nope\n"},
        base_image="broken:latest",
        expected_artifacts=[],
    )
    return run, spec


def _install_common_patches(
    monkeypatch: pytest.MonkeyPatch,
    *,
    session: _FakeRemediationSession,
    run: Any,
    spec: Any,
    prior_actions: list[Any] | None = None,
) -> list[dict[str, Any]]:
    monkeypatch.setattr(
        remediate_operator,
        "get_sync_session_factory",
        lambda: _FakeFactory(session),
    )
    monkeypatch.setattr(remediate_operator, "load_run_record", lambda _db, _run_id: run)
    monkeypatch.setattr(
        remediate_operator,
        "load_experiment_spec",
        lambda _db, _spec_id: spec,
    )
    monkeypatch.setattr(remediate_operator, "count_lineage_attempts", lambda _db, _rid: 0)
    monkeypatch.setattr(
        remediate_operator,
        "load_lineage_actions",
        lambda _db, _rid: prior_actions or [],
    )
    monkeypatch.setattr(remediate_operator, "embed_text", lambda _text: [0.0])
    monkeypatch.setattr(remediate_operator, "inject_patterns", lambda *args, **kwargs: [])
    monkeypatch.setattr(remediate_operator, "emit_event_sync", lambda *args, **kwargs: None)

    enqueue_calls: list[dict[str, Any]] = []

    def fake_enqueue_next_phase4(
        _db,
        *,
        cycle_id,
        next_job_type,
        run_record_id,
        extra_payload=None,
    ) -> None:
        enqueue_calls.append(
            {
                "cycle_id": cycle_id,
                "next_job_type": next_job_type,
                "run_record_id": run_record_id,
                "extra_payload": extra_payload,
            }
        )

    monkeypatch.setattr(remediate_operator, "enqueue_next_phase4", fake_enqueue_next_phase4)
    return enqueue_calls


def test_dockerfile_fix_enqueues_retry_with_replacement_dockerfile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run, spec = _build_run_and_spec(tmp_path)
    session = _FakeRemediationSession()
    enqueue_calls = _install_common_patches(
        monkeypatch,
        session=session,
        run=run,
        spec=spec,
    )

    async def fake_build_llm(**kwargs):
        assert kwargs["strategy"] == "dockerfile_fix"
        assert "docker build failed loudly" in kwargs["build_log"]
        return SimpleNamespace(
            dockerfile_content="FROM python:3.12-slim\nRUN pip install numpy\n",
            base_image=None,
        )

    monkeypatch.setattr(remediate_operator, "_build_remediation_llm", fake_build_llm)

    result = remediate_operator.auto_remediate_operator(_op_input(run))

    assert result.success is True
    assert any(isinstance(obj, RunRecord) for obj in session.added)
    action = next(obj for obj in session.added if isinstance(obj, RemediationAction))
    assert action.outcome == "retry_created"
    assert action.action_detail == {
        "build_recipe": {
            "dockerfile_content": "FROM python:3.12-slim\nRUN pip install numpy"
        }
    }
    assert enqueue_calls[0]["next_job_type"] == "execution_setup"
    assert enqueue_calls[0]["extra_payload"] == {
        "remediation_overrides": action.action_detail
    }


def test_base_image_swap_enqueues_retry_with_base_image_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run, spec = _build_run_and_spec(tmp_path)
    session = _FakeRemediationSession()
    prior_actions = [
        SimpleNamespace(
            strategy="dockerfile_fix",
            failure_class="build",
            outcome="retry_created",
        )
    ]
    enqueue_calls = _install_common_patches(
        monkeypatch,
        session=session,
        run=run,
        spec=spec,
        prior_actions=prior_actions,
    )

    async def fake_build_llm(**kwargs):
        assert kwargs["strategy"] == "base_image_swap"
        return SimpleNamespace(dockerfile_content=None, base_image="python:3.12-slim")

    monkeypatch.setattr(remediate_operator, "_build_remediation_llm", fake_build_llm)

    result = remediate_operator.auto_remediate_operator(_op_input(run))

    assert result.success is True
    action = next(obj for obj in session.added if isinstance(obj, RemediationAction))
    assert action.outcome == "retry_created"
    assert action.action_detail == {"base_image": "python:3.12-slim"}
    assert enqueue_calls[0]["next_job_type"] == "execution_setup"
    assert enqueue_calls[0]["extra_payload"] == {
        "remediation_overrides": {"base_image": "python:3.12-slim"}
    }


def test_build_remediation_without_required_override_routes_to_postmortem(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run, spec = _build_run_and_spec(tmp_path)
    session = _FakeRemediationSession()
    enqueue_calls = _install_common_patches(
        monkeypatch,
        session=session,
        run=run,
        spec=spec,
    )

    async def fake_build_llm(**_kwargs):
        return SimpleNamespace(dockerfile_content=None, base_image=None)

    monkeypatch.setattr(remediate_operator, "_build_remediation_llm", fake_build_llm)

    result = remediate_operator.auto_remediate_operator(_op_input(run))

    assert result.success is True
    assert not any(isinstance(obj, RunRecord) for obj in session.added)
    action = next(obj for obj in session.added if isinstance(obj, RemediationAction))
    assert action.outcome == "skipped"
    assert action.retry_run_id is None
    assert enqueue_calls == [
        {
            "cycle_id": run.cycle_id,
            "next_job_type": "verification_postmortem",
            "run_record_id": run.id,
            "extra_payload": None,
        }
    ]
