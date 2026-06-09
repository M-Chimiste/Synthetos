"""Goal integration tests for loop reporting."""

from __future__ import annotations

from uuid_utils import uuid7

from libs.autonomy.operators import loop_report


class _Session:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_loop_report_enqueues_goal_evaluation(monkeypatch) -> None:
    session = _Session()
    calls = []

    def fake_create_job(db, **kwargs):
        calls.append((db, kwargs))

    monkeypatch.setattr(loop_report, "create_job", fake_create_job)

    loop_report._enqueue_goal_evaluation_job(
        factory=lambda: session,
        charter_id=uuid7(),
        cycle_id=uuid7(),
        goal_id=str(uuid7()),
        artifacts=["/tmp/report.md", "/tmp/report.json"],
    )

    assert session.committed is True
    assert calls[0][1]["job_type"] == "goal_evaluate"
    assert calls[0][1]["payload"]["artifacts"] == ["/tmp/report.md", "/tmp/report.json"]
