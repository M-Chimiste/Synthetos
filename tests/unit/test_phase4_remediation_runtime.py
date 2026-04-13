"""Focused Phase 4 remediation runtime tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from uuid_utils import uuid7

from apps.api.routers import remediation as remediation_router
from libs.core.operators import OperatorInput
from libs.remediation.operators import recommend as recommend_operator
from libs.remediation.operators import signal as signal_operator
from libs.storage.models.remediation import RunRecommendation


class _ScalarResult:
    def __init__(self, scalar_value: Any = None, list_value: list[Any] | None = None):
        self._scalar_value = scalar_value
        self._list_value = list_value if list_value is not None else []

    def scalar_one_or_none(self) -> Any:
        return self._scalar_value

    def scalar_one(self) -> Any:
        return self._scalar_value

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[Any]:
        return self._list_value


class _FakeFactory:
    def __init__(self, session: Any):
        self._session = session

    def __call__(self) -> _FakeFactory:
        return self

    def __enter__(self) -> Any:
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeRecommendSession:
    def __init__(
        self,
        *,
        signal_row: Any = None,
        historical_postmortem_count: int = 0,
        lineage_postmortems: list[Any] | None = None,
        existing_recommendation: Any = None,
        verification_report: Any = None,
    ):
        self.signal_row = signal_row
        self.historical_postmortem_count = historical_postmortem_count
        self.lineage_postmortems = lineage_postmortems or []
        self.existing_recommendation = existing_recommendation
        self.verification_report = verification_report
        self.added: list[Any] = []
        self.committed = False

    def execute(self, query: Any) -> _ScalarResult:
        query_text = str(query)
        if "FROM directional_signals" in query_text:
            return _ScalarResult(self.signal_row)
        if "count(*) AS count_1" in query_text and "failure_postmortems" in query_text:
            return _ScalarResult(self.historical_postmortem_count)
        if "FROM failure_postmortems" in query_text:
            return _ScalarResult(list_value=self.lineage_postmortems)
        if "FROM run_recommendations" in query_text:
            return _ScalarResult(self.existing_recommendation)
        if "FROM verification_reports" in query_text:
            return _ScalarResult(self.verification_report)
        raise AssertionError(f"Unexpected query in recommend test: {query_text}")

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.committed = True


class _FakeSignalSession:
    def __init__(self, *, existing_signal: Any = None, verification_report: Any = None):
        self.existing_signal = existing_signal
        self.verification_report = verification_report
        self.added: list[Any] = []
        self.committed = False

    def get(self, _model: Any, _key: Any) -> Any:
        return SimpleNamespace(id=_key)

    def execute(self, query: Any) -> _ScalarResult:
        query_text = str(query)
        if "FROM experiment_specs" in query_text:
            return _ScalarResult(list_value=[uuid7()])
        if "FROM run_records" in query_text:
            return _ScalarResult(list_value=[])
        if "FROM directional_signals" in query_text:
            return _ScalarResult(self.existing_signal)
        if "FROM verification_reports" in query_text:
            return _ScalarResult(self.verification_report)
        raise AssertionError(f"Unexpected query in signal test: {query_text}")

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.committed = True


class _FakeAsyncLineageDb:
    def __init__(self, runs: dict[UUID, Any], actions: list[Any] | None = None):
        self.runs = runs
        self.actions = actions or []

    async def get(self, _model: Any, key: UUID) -> Any:
        return self.runs.get(key)

    async def execute(self, query: Any) -> _ScalarResult:
        query_text = str(query)
        if "FROM run_records" in query_text:
            children = [
                run
                for run in self.runs.values()
                if run.parent_run_id is not None
            ]
            children.sort(key=lambda row: (row.created_at, row.run_number))
            return _ScalarResult(list_value=children)
        if "FROM remediation_actions" in query_text:
            return _ScalarResult(list_value=self.actions)
        raise AssertionError(f"Unexpected query in lineage test: {query_text}")


def _op_input(run: Any, *, failed: bool = False) -> OperatorInput:
    payload: dict[str, Any] = {"run_record_id": str(run.id)}
    if failed:
        payload["failed"] = True
    return OperatorInput(
        cycle_id=UUID(str(run.cycle_id)),
        charter_id=UUID(str(run.charter_id)),
        job_id=uuid7(),
        job_type="phase4-test",
        payload=payload,
    )


def test_recommendation_ignores_old_resolved_failures_from_other_lineages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = SimpleNamespace(
        id=uuid7(),
        experiment_spec_id=uuid7(),
        charter_id=uuid7(),
        cycle_id=uuid7(),
    )
    spec = SimpleNamespace(id=run.experiment_spec_id, hypothesis_card_id=uuid7())
    frontier = SimpleNamespace(
        best_metric_value=0.82,
        runs_since_improvement=0,
        total_runs=5,
        successful_runs=4,
    )
    session = _FakeRecommendSession(
        signal_row=SimpleNamespace(signal="advancing"),
        historical_postmortem_count=1,
        lineage_postmortems=[],
        verification_report=SimpleNamespace(recommendation_id=None),
    )

    monkeypatch.setattr(
        recommend_operator,
        "get_sync_session_factory",
        lambda: _FakeFactory(session),
    )
    monkeypatch.setattr(recommend_operator, "load_run_record", lambda _db, _run_id: run)
    monkeypatch.setattr(recommend_operator, "load_experiment_spec", lambda _db, _sid: spec)
    monkeypatch.setattr(recommend_operator, "load_frontier", lambda *_args, **_kwargs: frontier)
    monkeypatch.setattr(recommend_operator, "load_lineage_actions", lambda _db, _rid: [])
    monkeypatch.setattr(recommend_operator, "load_lineage_run_ids", lambda _db, _rid: [run.id])
    monkeypatch.setattr(recommend_operator, "emit_event_sync", lambda *args, **kwargs: None)

    result = recommend_operator.recommend_operator(_op_input(run))

    assert result.success is True
    assert len(session.added) == 1
    rec = session.added[0]
    assert isinstance(rec, RunRecommendation)
    assert rec.recommendation_type == "continue_current"
    assert rec.inputs_summary["historical_postmortem_count"] == 1


def test_recommendation_reuses_existing_row_for_same_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = SimpleNamespace(
        id=uuid7(),
        experiment_spec_id=uuid7(),
        charter_id=uuid7(),
        cycle_id=uuid7(),
    )
    spec = SimpleNamespace(id=run.experiment_spec_id, hypothesis_card_id=uuid7())
    frontier = SimpleNamespace(
        best_metric_value=0.76,
        runs_since_improvement=0,
        total_runs=3,
        successful_runs=3,
    )
    existing = SimpleNamespace(
        id=uuid7(),
        recommendation_type="parameter_variation",
        action="old action",
        reasoning="old reasoning",
        inputs_summary=None,
    )
    verification_report = SimpleNamespace(recommendation_id=None)
    session = _FakeRecommendSession(
        signal_row=SimpleNamespace(signal="breakthrough"),
        existing_recommendation=existing,
        verification_report=verification_report,
    )

    monkeypatch.setattr(
        recommend_operator,
        "get_sync_session_factory",
        lambda: _FakeFactory(session),
    )
    monkeypatch.setattr(recommend_operator, "load_run_record", lambda _db, _run_id: run)
    monkeypatch.setattr(recommend_operator, "load_experiment_spec", lambda _db, _sid: spec)
    monkeypatch.setattr(recommend_operator, "load_frontier", lambda *_args, **_kwargs: frontier)
    monkeypatch.setattr(recommend_operator, "load_lineage_actions", lambda _db, _rid: [])
    monkeypatch.setattr(recommend_operator, "load_lineage_run_ids", lambda _db, _rid: [run.id])
    monkeypatch.setattr(recommend_operator, "emit_event_sync", lambda *args, **kwargs: None)

    result = recommend_operator.recommend_operator(_op_input(run))

    assert result.success is True
    assert session.added == []
    assert existing.recommendation_type == "continue_current"
    assert verification_report.recommendation_id == existing.id


def test_signal_classify_reuses_existing_row_for_same_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = SimpleNamespace(
        id=uuid7(),
        experiment_spec_id=uuid7(),
        charter_id=uuid7(),
        cycle_id=uuid7(),
        metrics_output={"accuracy": 0.91},
        status="completed",
        completed_at=datetime.now(UTC),
    )
    spec = SimpleNamespace(
        id=run.experiment_spec_id,
        hypothesis_card_id=uuid7(),
        metrics=[{"name": "accuracy", "direction": "maximize"}],
        primary_metric_index=0,
    )
    existing_signal = SimpleNamespace(
        id=uuid7(),
        signal="stalled",
        primary_metric_name="accuracy",
        primary_metric_value=0.5,
        primary_metric_delta=0.0,
        primary_metric_direction="maximize",
        constraint_metrics=None,
        history_window=None,
        reasoning="old",
    )
    verification_report = SimpleNamespace(directional_signal_id=None)
    session = _FakeSignalSession(
        existing_signal=existing_signal,
        verification_report=verification_report,
    )

    monkeypatch.setattr(
        signal_operator,
        "get_sync_session_factory",
        lambda: _FakeFactory(session),
    )
    monkeypatch.setattr(signal_operator, "load_run_record", lambda _db, _rid: run)
    monkeypatch.setattr(signal_operator, "load_experiment_spec", lambda _db, _sid: spec)
    monkeypatch.setattr(
        signal_operator,
        "get_primary_metric",
        lambda _spec: {"name": "accuracy", "direction": "maximize"},
    )
    monkeypatch.setattr(
        signal_operator,
        "classify_signal",
        lambda **_kwargs: SimpleNamespace(signal="advancing", delta=0.03, reasoning="better"),
    )
    monkeypatch.setattr(
        signal_operator,
        "upsert_frontier",
        lambda *_args, **_kwargs: (
            SimpleNamespace(best_metric_value=0.91, total_runs=2, runs_since_improvement=0),
            True,
        ),
    )
    monkeypatch.setattr(signal_operator, "enqueue_next_phase4", lambda *args, **kwargs: None)
    monkeypatch.setattr(signal_operator, "emit_event_sync", lambda *args, **kwargs: None)

    result = signal_operator.signal_classify_operator(_op_input(run))

    assert result.success is True
    assert session.added == []
    assert existing_signal.signal == "advancing"
    assert existing_signal.primary_metric_value == 0.91
    assert verification_report.directional_signal_id == existing_signal.id


@pytest.mark.asyncio
@pytest.mark.parametrize("target_index", [0, 1, 2])
async def test_run_lineage_endpoint_returns_full_chain_for_any_node(
    target_index: int,
) -> None:
    root_id = UUID(str(uuid7()))
    mid_id = UUID(str(uuid7()))
    leaf_id = UUID(str(uuid7()))
    base_time = datetime.now(UTC)
    runs = {
        root_id: SimpleNamespace(
            id=root_id,
            parent_run_id=None,
            created_at=base_time,
            run_number=1,
        ),
        mid_id: SimpleNamespace(
            id=mid_id,
            parent_run_id=root_id,
            created_at=base_time + timedelta(minutes=1),
            run_number=2,
        ),
        leaf_id: SimpleNamespace(
            id=leaf_id,
            parent_run_id=mid_id,
            created_at=base_time + timedelta(minutes=2),
            run_number=3,
        ),
    }
    db = _FakeAsyncLineageDb(runs)
    target_id = [root_id, mid_id, leaf_id][target_index]

    lineage = await remediation_router.get_run_lineage(run_id=target_id, db=db)

    assert lineage.run_ids == [root_id, mid_id, leaf_id]
