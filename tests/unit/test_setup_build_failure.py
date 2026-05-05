"""Image build failures are now routed into the same verification →
auto-remediation loop that handles run-time failures, instead of
silently bailing.

This test pins the contract:
  - DockerRunner.build_image raising BuildImageError MUST set
    run.failure_class="build", capture the build log in run.error and
    in <worktree>/build.log, emit run_failed, and enqueue
    verification_check.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from uuid_utils import uuid7

from libs.adapters.container.docker_runner import BuildImageError
from libs.core.operators import OperatorInput
from libs.execution.operators import setup as setup_operator


class _FakeSetupSession:
    def __init__(self, run, spec):
        self.run = run
        self.spec = spec
        self.committed = False
        self.added: list[object] = []

    def get(self, _model, key):
        if key == self.spec.id:
            return self.spec
        return None

    def flush(self):
        return None

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True


class _FakeFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc, tb):
        return False


def test_build_failure_routes_to_verification_check(
    monkeypatch, tmp_path: Path
) -> None:
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
        image_ref=None,
        command=None,
        resource_limits=None,
    )
    spec = SimpleNamespace(
        id=run.experiment_spec_id,
        title="broken-build spec",
        code_plan={
            "files": {"run_experiment.py": "print('hi')"},
            "entry_point": "run_experiment.py",
        },
        base_image="python:3.12-slim",
        # Force the build branch.
        build_recipe={"dockerfile_content": "FROM nonexistent-image:latest\n"},
        hardware_profile={},
    )
    fake_session = _FakeSetupSession(run, spec)

    monkeypatch.setattr(
        setup_operator,
        "get_sync_session_factory",
        lambda: _FakeFactory(fake_session),
    )
    monkeypatch.setattr(setup_operator, "load_run_record", lambda _db, _run_id: run)
    monkeypatch.setattr(
        setup_operator, "create_worktree", lambda **_kwargs: tmp_path
    )
    monkeypatch.setattr(
        setup_operator, "commit_worktree", lambda *_args, **_kwargs: "abc123"
    )
    monkeypatch.setattr(
        setup_operator,
        "get_settings",
        lambda: SimpleNamespace(data_root=tmp_path, repo_root=tmp_path),
    )

    # Make build_image raise with a synthetic log so we can verify the
    # tail makes it into run.error and the full log lands on disk.
    fake_log = "\n".join([f"step {i}: do something" for i in range(40)])

    class _FakeRunner:
        def build_image(self, **_kwargs):
            raise BuildImageError(
                tag="synthetos-exp-fake",
                log_text=fake_log,
                cause="manifest unknown",
            )

    monkeypatch.setattr(setup_operator, "DockerRunner", _FakeRunner)

    # Capture enqueue_next calls instead of touching a real DB.
    enqueue_calls: list[dict[str, object]] = []

    def fake_enqueue_next(_db, *, cycle_id, next_job_type, run_record_id, **kwargs):
        enqueue_calls.append(
            {
                "cycle_id": cycle_id,
                "next_job_type": next_job_type,
                "run_record_id": run_record_id,
                **kwargs,
            }
        )

    monkeypatch.setattr(setup_operator, "enqueue_next", fake_enqueue_next)

    # Don't actually emit events to a session.
    emit_calls: list[dict[str, object]] = []

    def fake_emit(_db, **kwargs):
        emit_calls.append(kwargs)

    monkeypatch.setattr(setup_operator, "emit_event_sync", fake_emit)

    result = setup_operator.execution_setup_operator(
        OperatorInput(
            cycle_id=UUID(str(run.cycle_id)),
            charter_id=UUID(str(run.charter_id)),
            job_id=uuid7(),
            job_type="execution_setup",
            payload={"run_record_id": str(run.id)},
        )
    )

    # The operator returns success=True (it successfully *handled* the
    # failure by routing it onward).
    assert result.success is True
    assert "verification_check" in (result.summary or "")

    # Run record reflects the build failure.
    assert run.status == "failed"
    assert run.failure_class == "build"
    assert run.error is not None
    assert "manifest unknown" in run.error
    # Tail of the log is in run.error (the last line should appear).
    assert "step 39" in run.error

    # Full log lives in the worktree.
    build_log_path = tmp_path / "build.log"
    assert build_log_path.exists()
    assert build_log_path.read_text() == fake_log

    # verification_check was enqueued, not execution_run.
    assert len(enqueue_calls) == 1
    call = enqueue_calls[0]
    assert call["next_job_type"] == "verification_check"
    assert call["run_record_id"] == run.id

    # A run_failed event was emitted with failure_class=build.
    assert any(
        e.get("payload", {}).get("failure_class") == "build" for e in emit_calls
    )

    assert fake_session.committed is True


def test_remediation_override_swaps_base_image(
    monkeypatch, tmp_path: Path
) -> None:
    """When auto_remediate proposes a new base_image (the second-attempt
    'base_image_swap' strategy), execution_setup must use it instead of
    spec.base_image. We verify this by asserting which image_ref ends up
    on the run record after a successful (no build_recipe) setup."""

    run = SimpleNamespace(
        id=uuid7(),
        experiment_spec_id=uuid7(),
        run_number=2,
        charter_id=uuid7(),
        cycle_id=uuid7(),
        status="pending",
        started_at=None,
        workspace_path=None,
        env_vars=None,
        failure_class=None,
        error=None,
        completed_at=None,
        image_ref=None,
        command=None,
        resource_limits=None,
    )
    spec = SimpleNamespace(
        id=run.experiment_spec_id,
        title="spec with bad base",
        code_plan={
            "files": {"run_experiment.py": "print('ok')"},
            "entry_point": "run_experiment.py",
        },
        base_image="this-image-was-broken:latest",
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
    monkeypatch.setattr(
        setup_operator, "create_worktree", lambda **_kwargs: tmp_path
    )
    monkeypatch.setattr(
        setup_operator, "commit_worktree", lambda *_args, **_kwargs: "deadbeef"
    )
    monkeypatch.setattr(
        setup_operator,
        "get_settings",
        lambda: SimpleNamespace(data_root=tmp_path, repo_root=tmp_path),
    )
    monkeypatch.setattr(setup_operator, "enqueue_next", lambda *a, **kw: None)
    monkeypatch.setattr(setup_operator, "emit_event_sync", lambda *a, **kw: None)

    result = setup_operator.execution_setup_operator(
        OperatorInput(
            cycle_id=UUID(str(run.cycle_id)),
            charter_id=UUID(str(run.charter_id)),
            job_id=uuid7(),
            job_type="execution_setup",
            payload={
                "run_record_id": str(run.id),
                "remediation_overrides": {
                    "base_image": "python:3.12-slim",
                },
            },
        )
    )

    assert result.success is True
    assert run.image_ref == "python:3.12-slim"
    # Spec was untouched; only the override took effect for this run.
    assert spec.base_image == "this-image-was-broken:latest"
