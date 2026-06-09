"""Goal advancement and status-ledger tests."""

from __future__ import annotations

from types import SimpleNamespace

from uuid_utils import uuid7

from libs.core.services import goal_service
from libs.core.types import CycleStatus
from libs.storage.models.experiment import HypothesisCard, HypothesisSession
from libs.storage.models.goals import GoalAttempt, ResearchGoal
from libs.storage.models.jobs import Job
from libs.storage.models.papers import PaperCard
from libs.storage.models.research import ResearchCycle


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


class _AdvanceSession:
    def __init__(self, *, goal, cycle, attempt, execute_values):
        self.goal = goal
        self.cycle = cycle
        self.attempt = attempt
        self.execute_values = list(execute_values)
        self.added = []
        self.flushed = 0

    def get(self, model, key):
        if model is ResearchGoal and str(key) == str(self.goal.id):
            return self.goal
        if model is ResearchCycle and str(key) == str(self.cycle.id):
            return self.cycle
        if model is PaperCard:
            for value in self.execute_values:
                if isinstance(value, PaperCard) and str(value.id) == str(key):
                    return value
        return None

    def execute(self, _stmt):
        if self.execute_values:
            return _ScalarResult(self.execute_values.pop(0))
        return _ScalarResult(None)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flushed += 1


def _goal(tmp_path):
    goal = ResearchGoal(
        id=uuid7(),
        charter_id=uuid7(),
        title="g",
        goal_statement="train",
        success_criteria=[],
        policy={},
        status="running",
    )
    settings = SimpleNamespace(data_root=tmp_path)
    return goal, settings


def _cycle(goal, status):
    return ResearchCycle(
        id=uuid7(),
        charter_id=goal.charter_id,
        status=status,
        config={"goal": {"goal_id": str(goal.id), "attempt_number": 1}},
    )


def _attempt(goal, cycle):
    return GoalAttempt(
        id=uuid7(),
        goal_id=goal.id,
        charter_id=goal.charter_id,
        cycle_id=cycle.id,
        attempt_number=1,
        status="running",
    )


def test_status_ledger_writes_json_markdown_and_attempt_summary(tmp_path, monkeypatch):
    goal, settings = _goal(tmp_path)
    cycle = _cycle(goal, CycleStatus.evidence_ready)
    attempt = _attempt(goal, cycle)
    session = _AdvanceSession(goal=goal, cycle=cycle, attempt=attempt, execute_values=[])
    monkeypatch.setattr(goal_service, "get_settings", lambda: settings)
    monkeypatch.setattr(goal_service, "emit_event_sync", lambda *args, **kwargs: None)

    entry = goal_service.append_goal_ledger_entry(
        session,
        goal,
        attempt,
        kind="repair",
        stage="analysis",
        summary="reduced chunk budget",
        outcome="retry_started",
        fingerprint="abc123",
        cycle_id=cycle.id,
    )

    paths = goal_service.goal_status_paths(goal.id)
    assert entry["summary"] == "reduced chunk budget"
    assert (tmp_path / "reports" / "goals" / str(goal.id) / "status.json").exists()
    status_md = tmp_path / "reports" / "goals" / str(goal.id) / "status.md"
    assert "reduced chunk budget" in status_md.read_text()
    assert attempt.evaluation["status_ledger"]["json_path"] == paths["json"]
    assert attempt.evaluation["status_ledger"]["latest"]["summary"] == "reduced chunk budget"


def test_goal_advance_starts_hypothesis_from_evidence_ready(tmp_path, monkeypatch):
    goal, settings = _goal(tmp_path)
    cycle = _cycle(goal, CycleStatus.evidence_ready)
    attempt = _attempt(goal, cycle)
    session = _AdvanceSession(
        goal=goal,
        cycle=cycle,
        attempt=attempt,
        execute_values=[attempt, None],
    )
    monkeypatch.setattr(goal_service, "get_settings", lambda: settings)
    monkeypatch.setattr(goal_service, "emit_event_sync", lambda *args, **kwargs: None)

    result = goal_service.advance_goal_cycle_sync(
        session,
        goal_id=goal.id,
        cycle_id=cycle.id,
        trigger="analysis_evidence_completed",
    )

    assert result["next_action"] == "hypothesis_started"
    assert any(isinstance(obj, HypothesisSession) for obj in session.added)
    assert any(
        isinstance(obj, Job) and obj.job_type == "hypothesis_generate"
        for obj in session.added
    )


def test_goal_advance_compiles_top_ranked_hypothesis(tmp_path, monkeypatch):
    goal, settings = _goal(tmp_path)
    cycle = _cycle(goal, CycleStatus.portfolio_ready)
    attempt = _attempt(goal, cycle)
    hs = HypothesisSession(
        id=uuid7(),
        cycle_id=cycle.id,
        charter_id=goal.charter_id,
        status="completed",
    )
    card = HypothesisCard(
        id=uuid7(),
        hypothesis_session_id=hs.id,
        charter_id=goal.charter_id,
        cycle_id=cycle.id,
        title="top",
        statement="s",
        rationale="r",
        supporting_evidence_ids=[],
        status="candidate",
        rank=1,
    )
    session = _AdvanceSession(
        goal=goal,
        cycle=cycle,
        attempt=attempt,
        execute_values=[attempt, hs, card, None],
    )
    monkeypatch.setattr(goal_service, "get_settings", lambda: settings)
    monkeypatch.setattr(goal_service, "emit_event_sync", lambda *args, **kwargs: None)

    result = goal_service.advance_goal_cycle_sync(
        session,
        goal_id=goal.id,
        cycle_id=cycle.id,
        trigger="hypothesis_rank_completed",
    )

    assert result["next_action"] == "protocol_compile_started"
    job = next(obj for obj in session.added if isinstance(obj, Job))
    assert job.job_type == "protocol_compile"
    assert job.payload["from_loop"] is True
    assert job.payload["hypothesis_card_ids"] == [str(card.id)]


def test_retry_fingerprint_is_stable_and_changes_with_patch():
    first = goal_service.retry_fingerprint(
        stage="analysis",
        selected_paper_id="paper",
        config_patch={"max_chunks": 80},
        error_class="timeout",
        proposed_action="retry_stage",
    )
    second = goal_service.retry_fingerprint(
        stage="analysis",
        selected_paper_id="paper",
        config_patch={"max_chunks": 80},
        error_class="timeout",
        proposed_action="retry_stage",
    )
    changed = goal_service.retry_fingerprint(
        stage="analysis",
        selected_paper_id="paper",
        config_patch={"max_chunks": 120},
        error_class="timeout",
        proposed_action="retry_stage",
    )

    assert first == second
    assert first != changed


def test_retry_started_fingerprint_blocks_duplicate_repair(tmp_path, monkeypatch):
    goal, settings = _goal(tmp_path)
    cycle = _cycle(goal, CycleStatus.evidence_ready)
    attempt = _attempt(goal, cycle)
    session = _AdvanceSession(goal=goal, cycle=cycle, attempt=attempt, execute_values=[])
    monkeypatch.setattr(goal_service, "get_settings", lambda: settings)
    monkeypatch.setattr(goal_service, "emit_event_sync", lambda *args, **kwargs: None)

    goal_service.append_goal_ledger_entry(
        session,
        goal,
        attempt,
        kind="repair",
        stage="analysis",
        summary="retry analysis",
        outcome="retry_started",
        fingerprint="same-plan",
        cycle_id=cycle.id,
    )

    assert goal_service._ledger_has_failed_fingerprint(goal.id, "same-plan") is True
