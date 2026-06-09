"""Goal service tests."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from uuid_utils import uuid7

from libs.core.services import goal_service
from libs.schemas.goals import GoalCreate, GoalCriterion, GoalPolicy
from libs.storage.models.discovery import DiscoverySession, ProblemProfile
from libs.storage.models.goals import GoalAttempt, ResearchGoal
from libs.storage.models.jobs import Job
from libs.storage.models.research import ResearchCharter, ResearchCycle


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value


class _FakeSession:
    def __init__(self, *, charter=None, goal=None, attempt=None):
        self.charter = charter
        self.goal = goal
        self.attempt = attempt
        self.added = []
        self.flushed = 0
        self.execute_values = []

    def get(self, model, key):
        if model is ResearchCharter and self.charter and str(key) == str(self.charter.id):
            return self.charter
        if model is ResearchGoal and self.goal and str(key) == str(self.goal.id):
            return self.goal
        return None

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flushed += 1

    def execute(self, _stmt):
        if self.execute_values:
            return _ScalarResult(self.execute_values.pop(0))
        if self.attempt is not None:
            return _ScalarResult(self.attempt)
        return _ScalarResult(0)


def _goal_create(charter_id):
    return GoalCreate(
        charter_id=UUID(str(charter_id)),
        title="Train a small model",
        goal_statement="Produce a completed training run with metrics.",
        success_criteria=[
            GoalCriterion(
                name="completed run",
                check_type="completed_run_exists",
            )
        ],
        policy=GoalPolicy(max_attempt_cycles=2),
    )


def test_create_goal_creates_first_cycle_attempt_and_discovery_job(monkeypatch) -> None:
    charter = ResearchCharter(id=uuid7(), title="c", description="", problem_statement="")
    session = _FakeSession(charter=charter)
    monkeypatch.setattr(goal_service, "emit_event_sync", lambda *args, **kwargs: None)

    goal = goal_service.create_goal_sync(session, _goal_create(charter.id))

    assert goal.status == "running"
    assert any(isinstance(obj, ResearchGoal) for obj in session.added)
    assert any(isinstance(obj, ResearchCycle) for obj in session.added)
    assert any(isinstance(obj, GoalAttempt) for obj in session.added)
    assert any(isinstance(obj, ProblemProfile) for obj in session.added)
    assert any(isinstance(obj, DiscoverySession) for obj in session.added)
    assert any(isinstance(obj, Job) and obj.job_type == "discovery_intake" for obj in session.added)


def test_evaluate_goal_attempt_marks_satisfied(monkeypatch) -> None:
    goal = ResearchGoal(
        id=uuid7(),
        charter_id=uuid7(),
        title="g",
        goal_statement="statement",
        success_criteria=[],
        policy={},
        status="running",
    )
    attempt = GoalAttempt(
        id=uuid7(),
        goal_id=goal.id,
        charter_id=goal.charter_id,
        cycle_id=uuid7(),
        attempt_number=1,
        status="running",
    )
    session = _FakeSession(goal=goal, attempt=attempt)
    reported_statuses = []
    monkeypatch.setattr(
        goal_service,
        "evaluate_criteria",
        lambda *_args, **_kwargs: {"passed": True, "summary": "ok", "criteria": []},
    )

    def fake_write_report(_session, report_goal):
        reported_statuses.append(report_goal.status)
        return {"markdown": "/tmp/report.md", "json": "/tmp/report.json"}

    monkeypatch.setattr(
        goal_service,
        "write_goal_report",
        fake_write_report,
    )
    monkeypatch.setattr(goal_service, "emit_event_sync", lambda *args, **kwargs: None)

    _goal, _attempt, result = goal_service.evaluate_goal_attempt_sync(
        session,
        goal_id=goal.id,
        cycle_id=attempt.cycle_id,
        cycle_report_paths=["/tmp/cycle.md", "/tmp/cycle.json"],
    )

    assert result["next_action"] == "satisfied"
    assert goal.status == "satisfied"
    assert attempt.status == "satisfied"
    assert reported_statuses == ["satisfied"]


def test_goal_criteria_accept_saved_param_aliases() -> None:
    cycle_id = uuid7()
    run = SimpleNamespace(
        status="completed",
        metrics_output={"train_loss": 0.42},
        artifact_manifest=[
            {"name": "model_weights.pt", "path": "model_weights.pt"},
        ],
    )
    session = _FakeSession()
    session.execute_values = [1]

    metric = goal_service._evaluate_one(
        session,
        {
            "name": "train loss",
            "check_type": "metric_present",
            "params": {"metric_name": "train_loss"},
        },
        [run],
        [cycle_id],
        cycle_id,
        {},
    )
    artifact = goal_service._evaluate_one(
        session,
        {
            "name": "weights",
            "check_type": "artifact_exists",
            "params": {"artifact_name": "model_weights.pt"},
        },
        [run],
        [cycle_id],
        cycle_id,
        {},
    )
    verification = goal_service._evaluate_one(
        session,
        {
            "name": "verification",
            "check_type": "verification_passed",
            "params": {"accepted_verdicts": ["passed", "inconclusive"]},
        },
        [run],
        [cycle_id],
        cycle_id,
        {},
    )

    assert metric["passed"] is True
    assert artifact["passed"] is True
    assert verification["passed"] is True


def test_evaluate_goal_attempt_starts_next_attempt_when_budget_remains(monkeypatch) -> None:
    goal = ResearchGoal(
        id=uuid7(),
        charter_id=uuid7(),
        title="g",
        goal_statement="statement",
        success_criteria=[],
        policy={"max_attempt_cycles": 3},
        status="running",
    )
    attempt = GoalAttempt(
        id=uuid7(),
        goal_id=goal.id,
        charter_id=goal.charter_id,
        cycle_id=uuid7(),
        attempt_number=1,
        status="running",
    )
    session = _FakeSession(goal=goal, attempt=attempt)
    started = []
    monkeypatch.setattr(
        goal_service,
        "evaluate_criteria",
        lambda *_args, **_kwargs: {"passed": False, "summary": "not yet", "criteria": []},
    )
    monkeypatch.setattr(goal_service, "_budget_exhausted", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        goal_service,
        "start_goal_attempt_sync",
        lambda *args, **kwargs: started.append(kwargs),
    )
    monkeypatch.setattr(
        goal_service,
        "write_goal_report",
        lambda *_args, **_kwargs: {"markdown": "/tmp/report.md", "json": "/tmp/report.json"},
    )
    monkeypatch.setattr(goal_service, "emit_event_sync", lambda *args, **kwargs: None)

    _goal, _attempt, result = goal_service.evaluate_goal_attempt_sync(
        session,
        goal_id=goal.id,
        cycle_id=attempt.cycle_id,
    )

    assert result["next_action"] == "next_attempt_started"
    assert attempt.status == "failed"
    assert started


def test_evaluate_goal_attempt_marks_exhausted(monkeypatch) -> None:
    goal = ResearchGoal(
        id=uuid7(),
        charter_id=uuid7(),
        title="g",
        goal_statement="statement",
        success_criteria=[],
        policy={"max_attempt_cycles": 1},
        status="running",
    )
    attempt = GoalAttempt(
        id=uuid7(),
        goal_id=goal.id,
        charter_id=goal.charter_id,
        cycle_id=uuid7(),
        attempt_number=1,
        status="running",
    )
    session = _FakeSession(goal=goal, attempt=attempt)
    monkeypatch.setattr(
        goal_service,
        "evaluate_criteria",
        lambda *_args, **_kwargs: {"passed": False, "summary": "no", "criteria": []},
    )
    monkeypatch.setattr(goal_service, "_budget_exhausted", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        goal_service,
        "write_goal_report",
        lambda *_args, **_kwargs: {"markdown": "/tmp/report.md", "json": "/tmp/report.json"},
    )
    monkeypatch.setattr(goal_service, "emit_event_sync", lambda *args, **kwargs: None)

    _goal, _attempt, result = goal_service.evaluate_goal_attempt_sync(
        session,
        goal_id=goal.id,
        cycle_id=attempt.cycle_id,
    )

    assert result["next_action"] == "exhausted"
    assert goal.status == "exhausted"
