"""Focused Phase 5 autonomy runtime tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from uuid_utils import uuid7

from apps.api.routers import autonomy as autonomy_router
from libs.autonomy import context_summary as context_summary_module
from libs.autonomy.operators import loop_decide as loop_decide_module
from libs.autonomy.operators import loop_report as loop_report_module
from libs.core.operators import OperatorInput
from libs.core.services import result_introspection as result_introspection_module
from libs.core.services.autonomy_service import read_report_file
from libs.protocols.operators import compile as compile_module
from libs.remediation.operators import recommend as recommend_module
from libs.storage.models.autonomy import LoopDecision


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


class _SequentialFactory:
    def __init__(self, sessions: list[Any]):
        self._sessions = sessions
        self._index = 0

    def __call__(self) -> _SequentialFactory:
        return self

    def __enter__(self) -> Any:
        session = self._sessions[self._index]
        self._index += 1
        return session

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _LoopDecideSession:
    def __init__(self, *, recommendation: Any, run: Any, spec: Any, cycle: Any, gate_decision: Any):
        self.recommendation = recommendation
        self.run = run
        self.spec = spec
        self.cycle = cycle
        self.gate_decision = gate_decision
        self.added: list[Any] = []
        self.committed = False

    def get(self, model: Any, key: Any) -> Any:
        name = getattr(model, "__name__", "")
        if name == "ResearchCycle":
            return self.cycle
        if name == "HypothesisCard":
            return SimpleNamespace(id=key, status="compiled", updated_at=None)
        return None

    def execute(self, query: Any) -> _ScalarResult:
        query_text = str(query)
        if "FROM run_recommendations" in query_text:
            return _ScalarResult(self.recommendation)
        if "FROM run_records" in query_text:
            return _ScalarResult(self.run)
        if "FROM experiment_specs" in query_text:
            return _ScalarResult(self.spec)
        if "count(*) AS count_1" in query_text and "loop_decisions" in query_text:
            return _ScalarResult(1)
        if "FROM loop_decisions" in query_text and "decision =" in query_text:
            return _ScalarResult(self.gate_decision)
        if "FROM directional_signals" in query_text:
            return _ScalarResult(None)
        if "FROM metric_frontiers" in query_text:
            return _ScalarResult(None)
        if "FROM canonical_patterns" in query_text:
            # Phase 6 pattern injection: no patterns in unit-test fixture.
            return _ScalarResult(list_value=[])
        raise AssertionError(f"Unexpected query in loop_decide test: {query_text}")

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.committed = True


class _CompileSessionOne:
    def __init__(self, *, hs: Any, charter: Any, card: Any):
        self.hs = hs
        self.charter = charter
        self.card = card
        self.added: list[Any] = []

    def get(self, model: Any, key: Any) -> Any:
        name = getattr(model, "__name__", "")
        if name == "HypothesisSession":
            return self.hs
        if name == "ResearchCharter":
            return self.charter
        return None

    def execute(self, query: Any) -> _ScalarResult:
        query_text = str(query)
        if "FROM hypothesis_cards" in query_text:
            return _ScalarResult(list_value=[self.card])
        raise AssertionError(f"Unexpected query in protocol compile phase 1: {query_text}")

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        return None


class _CompileSessionTwo:
    def __init__(self, *, spec: Any, cycle: Any, budget: Any):
        self.spec = spec
        self.cycle = cycle
        self.budget = budget
        self.added: list[Any] = []
        self.committed = False

    def get(self, model: Any, key: Any) -> Any:
        name = getattr(model, "__name__", "")
        if name == "ExperimentSpec":
            return self.spec
        if name == "ResearchCycle":
            return self.cycle
        return None

    def execute(self, query: Any) -> _ScalarResult:
        query_text = str(query)
        if "coalesce(max(run_records.run_number)" in query_text:
            return _ScalarResult(0)
        if "count(*) AS count_1" in query_text and "loop_decisions" in query_text:
            return _ScalarResult(0)
        raise AssertionError(f"Unexpected query in protocol compile phase 2: {query_text}")

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.committed = True


class _LoopReportSession:
    def __init__(
        self,
        *,
        decisions: list[Any],
        budget: Any,
        cards: list[Any],
        frontiers: list[Any],
        recommendation: Any,
    ):
        self.decisions = decisions
        self.budget = budget
        self.cards = cards
        self.frontiers = frontiers
        self.recommendation = recommendation
        self.committed = False
        self.cycle_id = decisions[0].cycle_id if decisions else uuid7()
        self.charter_id = decisions[0].charter_id if decisions else uuid7()

    def get(self, model: Any, key: Any) -> Any:
        name = getattr(model, "__name__", "")
        if name == "ResearchCycle":
            return SimpleNamespace(
                id=key,
                charter_id=self.charter_id,
                config={},
            )
        return None

    def execute(self, query: Any) -> _ScalarResult:
        query_text = str(query)
        if "FROM loop_decisions" in query_text:
            return _ScalarResult(list_value=self.decisions)
        if "FROM autonomy_budgets" in query_text:
            return _ScalarResult(self.budget)
        if "FROM hypothesis_cards" in query_text:
            return _ScalarResult(list_value=self.cards)
        if "FROM metric_frontiers" in query_text:
            return _ScalarResult(list_value=self.frontiers)
        if "count(*) AS count_1" in query_text and "remediation_actions" in query_text:
            return _ScalarResult(1)
        if "FROM remediation_actions" in query_text:
            return _ScalarResult(list_value=[])
        if "FROM run_recommendations" in query_text:
            return _ScalarResult(self.recommendation)
        if "FROM run_records" in query_text:
            return _ScalarResult(list_value=[])
        if "FROM goal_attempts" in query_text:
            return _ScalarResult(None)
        raise AssertionError(f"Unexpected query in loop_report test: {query_text}")

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        return None


class _EnqueueSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    def rollback(self) -> None:
        self.rolled_back = True

    def commit(self) -> None:
        self.committed = True


class _ContextSummarySession:
    def execute(self, query: Any) -> _ScalarResult:
        query_text = str(query)
        if "FROM hypothesis_cards" in query_text:
            cards = [
                SimpleNamespace(
                    id=uuid7(),
                    title="Card A",
                    status="active",
                )
            ]
            return _ScalarResult(list_value=cards)
        if "FROM metric_frontiers" in query_text and "hypothesis_card_id =" in query_text:
            return _ScalarResult(
                SimpleNamespace(
                    best_metric_value=0.82,
                    total_runs=3,
                    successful_runs=2,
                    runs_since_improvement=1,
                )
            )
        if "FROM metric_frontiers" in query_text:
            return _ScalarResult(
                list_value=[
                    SimpleNamespace(
                        hypothesis_card_id=uuid7(),
                        best_metric_value=0.82,
                        total_runs=3,
                        successful_runs=2,
                        runs_since_improvement=1,
                    )
                ]
            )
        if "FROM run_records" in query_text:
            return _ScalarResult(list_value=[("dependency", 1)])
        if "count(*) AS count_1" in query_text and "remediation_actions" in query_text:
            return _ScalarResult(1)
        if "FROM loop_decisions" in query_text:
            return _ScalarResult(
                list_value=[SimpleNamespace(decision="vary_parameters", iteration_number=1)]
            )
        raise AssertionError(f"Unexpected query in context summary test: {query_text}")


class _AsyncStopDb:
    def __init__(self, *, cycle: Any, budget: Any, last_decision: Any):
        self.cycle = cycle
        self.budget = budget
        self.last_decision = last_decision
        self.added: list[Any] = []

    async def get(self, model: Any, key: UUID) -> Any:
        return self.cycle

    async def execute(self, query: Any) -> _ScalarResult:
        query_text = str(query)
        if query_text.startswith("UPDATE jobs"):
            return _ScalarResult(None)
        if "FROM autonomy_budgets" in query_text:
            return _ScalarResult(self.budget)
        if "FROM loop_decisions" in query_text:
            return _ScalarResult(self.last_decision)
        if "FROM run_recommendations" in query_text:
            return _ScalarResult(None)
        raise AssertionError(f"Unexpected query in stop route test: {query_text}")

    def add(self, obj: Any) -> None:
        self.added.append(obj)


def _op_input(
    *,
    run_id: UUID,
    cycle_id: UUID,
    charter_id: UUID,
    payload: dict[str, Any],
) -> OperatorInput:
    return OperatorInput(
        cycle_id=cycle_id,
        charter_id=charter_id,
        job_id=uuid7(),
        job_type="phase5-test",
        payload=payload,
    )


def test_loop_decide_resume_does_not_increment_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = uuid7()
    cycle_id = uuid7()
    charter_id = uuid7()
    recommendation = SimpleNamespace(
        id=uuid7(),
        recommendation_type="halt",
        action="halt",
        reasoning="Stop here.",
    )
    run = SimpleNamespace(
        id=run_id,
        experiment_spec_id=uuid7(),
        cycle_id=cycle_id,
        charter_id=charter_id,
    )
    spec = SimpleNamespace(
        id=run.experiment_spec_id,
        hypothesis_card_id=uuid7(),
        hardware_profile=None,
    )
    cycle = SimpleNamespace(config={"autonomy": {"mode": "autonomous"}}, id=cycle_id)
    gate_decision = SimpleNamespace(
        iteration_number=2,
        context_summary_path="/tmp/summary.json",
    )
    budget = SimpleNamespace(
        total_runs=3,
        wall_clock_elapsed_s=90.0,
        runs_per_hypothesis={str(spec.hypothesis_card_id): 1},
    )
    session = _LoopDecideSession(
        recommendation=recommendation,
        run=run,
        spec=spec,
        cycle=cycle,
        gate_decision=gate_decision,
    )
    increment_calls: list[UUID] = []
    queued_jobs: list[tuple[str, dict[str, Any] | None]] = []

    monkeypatch.setattr(
        loop_decide_module,
        "get_sync_session_factory",
        lambda: _SequentialFactory([session]),
    )
    monkeypatch.setattr(loop_decide_module, "load_or_create_budget", lambda _db, _cid: budget)
    monkeypatch.setattr(
        loop_decide_module,
        "increment_budget",
        lambda _db, _budget, card_id: increment_calls.append(card_id),
    )
    monkeypatch.setattr(loop_decide_module, "emit_event_sync", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        loop_decide_module,
        "update_hypothesis_status",
        lambda *_args, **_kwargs: "compiled",
    )
    monkeypatch.setattr(
        loop_decide_module,
        "create_job",
        lambda _db, *, cycle_id, job_type, payload=None, priority=0: queued_jobs.append(
            (job_type, payload)
        ),
    )

    result = loop_decide_module.loop_decide_operator(
        _op_input(
            run_id=run_id,
            cycle_id=cycle_id,
            charter_id=charter_id,
            payload={"run_record_id": str(run_id), "recommendation_id": str(recommendation.id)},
        )
    )

    assert result.success is True
    assert increment_calls == []
    assert queued_jobs == [("loop_report", {"cycle_id": str(cycle_id)})]


def test_protocol_compile_from_loop_pauses_on_network_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cycle_id = uuid7()
    charter_id = uuid7()
    session_id = uuid7()
    card_id = uuid7()
    hs = SimpleNamespace(id=session_id, cycle_id=cycle_id, charter_id=charter_id)
    charter = SimpleNamespace(problem_statement="Find a better configuration.")
    card = SimpleNamespace(
        id=card_id,
        hypothesis_session_id=session_id,
        cycle_id=cycle_id,
        charter_id=charter_id,
        title="Hypothesis A",
        statement="Try a new optimizer.",
        rationale="The baseline stalls.",
        novelty_score=0.8,
        feasibility_score=0.8,
        impact_score=0.8,
        rank=1,
        status="candidate",
        updated_at=None,
    )
    session_one = _CompileSessionOne(hs=hs, charter=charter, card=card)
    budget = SimpleNamespace(
        total_runs=2,
        wall_clock_elapsed_s=120.0,
        runs_per_hypothesis={str(card_id): 2},
    )
    cycle = SimpleNamespace(
        config={
            "autonomy": {
                "mode": "autonomous",
                "checkpoint_gates": {"before_network_execution": True},
            }
        }
    )
    session_two = _CompileSessionTwo(spec=None, cycle=cycle, budget=budget)

    async def _fake_compile_specs(*_args, **_kwargs):
        spec = compile_module._SpecSet(
            specs=[
                compile_module._CompiledSpec(
                    title="Networked Variation",
                    description="This run needs a download step.",
                    baseline={"name": "baseline"},
                    metrics=[{"name": "accuracy", "direction": "maximize"}],
                    code_plan={
                        "entry_point": "run_experiment.py",
                        "files": {
                            "run_experiment.py": (
                                "import requests\n"
                                "requests.get('https://example.com/model.bin')\n"
                            )
                        },
                    },
                )
            ]
        )
        return spec, {"provider": "test", "model": "fake"}

    class _CompileFactory:
        def __init__(self) -> None:
            self._index = 0

        def __call__(self) -> _CompileFactory:
            return self

        def __enter__(self) -> Any:
            if self._index == 0:
                self._index += 1
                return session_one
            if session_two.spec is None:
                session_two.spec = next(
                    obj for obj in session_one.added if hasattr(obj, "code_plan")
                )
            self._index += 1
            return session_two

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    monkeypatch.setattr(compile_module, "get_sync_session_factory", lambda: _CompileFactory())
    monkeypatch.setattr(compile_module, "_compile_specs", _fake_compile_specs)
    monkeypatch.setattr(
        compile_module,
        "validate_spec",
        lambda _spec: SimpleNamespace(valid=True, errors=[]),
    )
    monkeypatch.setattr(
        compile_module,
        "load_skill_prompt",
        lambda *_args, **_kwargs: SimpleNamespace(prompt=None),
    )
    monkeypatch.setattr(compile_module, "record_skill_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(compile_module, "record_model_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(compile_module, "emit_event_sync", lambda *args, **kwargs: None)
    monkeypatch.setattr(compile_module, "load_or_create_budget", lambda _db, _cid: budget)

    result = compile_module.protocol_compile_operator(
        _op_input(
            run_id=uuid7(),
            cycle_id=cycle_id,
            charter_id=charter_id,
            payload={
                "hypothesis_session_id": str(session_id),
                "hypothesis_card_ids": [str(card_id)],
                "from_loop": True,
                "loop_context": {
                    "run_record_id": str(uuid7()),
                    "recommendation_id": str(uuid7()),
                    "hypothesis_card_id": str(card_id),
                    "current_hardware_profile": {"gpu_count": 1},
                },
            },
        )
    )

    assert result.success is True
    assert result.state_patch == {"cycle_status": "loop_deciding"}
    paused_jobs = [
        obj
        for obj in session_two.added
        if getattr(obj, "job_type", None) == "loop_decide"
    ]
    assert len(paused_jobs) == 1
    assert paused_jobs[0].status == "paused"
    assert paused_jobs[0].payload["prepared_run_record_id"]
    gate_decisions = [obj for obj in session_two.added if isinstance(obj, LoopDecision)]
    assert len(gate_decisions) == 1
    assert gate_decisions[0].gate_triggered == "before_network_execution"


@pytest.mark.asyncio
async def test_stop_loop_persists_manual_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    cycle_id = uuid7()
    charter_id = uuid7()
    last_decision = SimpleNamespace(
        run_record_id=uuid7(),
        recommendation_id=uuid7(),
        iteration_number=4,
        hypothesis_card_id=uuid7(),
        context_summary_path="/tmp/summary.json",
    )
    cycle = SimpleNamespace(
        id=cycle_id,
        charter_id=charter_id,
        status="loop_deciding",
        updated_at=None,
    )
    budget = SimpleNamespace(total_runs=4, wall_clock_elapsed_s=180.0, runs_per_hypothesis={})
    db = _AsyncStopDb(cycle=cycle, budget=budget, last_decision=last_decision)

    async def _emit_event(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(autonomy_router, "emit_event", _emit_event)

    result = await autonomy_router.stop_loop(cycle_id, db=db)

    assert result["status"] == "stopped"
    decisions = [obj for obj in db.added if isinstance(obj, LoopDecision)]
    assert len(decisions) == 1
    assert decisions[0].decision == "stop_manual"
    assert decisions[0].reasoning == "Manual stop requested."


def test_context_summary_populates_key_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def _fake_summary(_summary: Any) -> tuple[str, dict[str, Any]]:
        return (
            "The loop explored one viable hypothesis and should avoid duplicate "
            "parameter sweeps.",
            {
                "provider": "test",
                "model": "fake",
            },
        )

    monkeypatch.setattr(context_summary_module, "_summarize_with_model", _fake_summary)
    monkeypatch.setattr(
        context_summary_module,
        "record_model_call",
        lambda *_args, **_kwargs: calls.append({"recorded": True}),
    )

    summary = context_summary_module.generate_summary(
        _ContextSummarySession(),
        cycle_id=uuid7(),
        charter_id=uuid7(),
        iteration_number=5,
    )

    assert summary.key_findings
    assert calls == [{"recorded": True}]


def test_loop_report_writes_sections_and_canonical_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cycle_id = uuid7()
    charter_id = uuid7()
    recommendation_id = uuid7()
    decision = SimpleNamespace(
        id=uuid7(),
        cycle_id=cycle_id,
        charter_id=charter_id,
        run_record_id=uuid7(),
        recommendation_id=recommendation_id,
        iteration_number=1,
        decision="stop_exhausted",
        gate_triggered=None,
        next_action=None,
        context_summary_path=None,
        reasoning="No remaining viable hypotheses.",
        hypothesis_card_id=None,
        next_hypothesis_card_id=None,
    )
    budget = SimpleNamespace(total_runs=3, wall_clock_elapsed_s=240.0, runs_per_hypothesis={})
    card = SimpleNamespace(id=uuid7(), title="Hypothesis A", status="stalled")
    frontier = SimpleNamespace(
        hypothesis_card_id=card.id,
        best_metric_value=0.81,
        total_runs=3,
        successful_runs=2,
        runs_since_improvement=2,
        primary_metric_name="accuracy",
        primary_metric_direction="maximize",
    )
    recommendation = SimpleNamespace(
        id=recommendation_id,
        recommendation_type="hypothesis_pivot",
        action="Generate a fresh hypothesis session.",
        reasoning="All current lines are exhausted.",
    )
    session = _LoopReportSession(
        decisions=[decision],
        budget=budget,
        cards=[card],
        frontiers=[frontier],
        recommendation=recommendation,
    )
    enqueue_session = _EnqueueSession()
    events: list[str] = []

    monkeypatch.setattr(
        loop_report_module,
        "get_sync_session_factory",
        lambda: _SequentialFactory([session, enqueue_session]),
    )
    monkeypatch.setattr(
        loop_report_module,
        "get_settings",
        lambda: SimpleNamespace(data_root=tmp_path),
    )
    monkeypatch.setattr(
        result_introspection_module,
        "get_settings",
        lambda: SimpleNamespace(data_root=tmp_path),
    )
    monkeypatch.setattr(
        loop_report_module,
        "generate_executive_summary",
        lambda *_args, **_kwargs: "Executive summary for the autonomy loop.",
    )
    monkeypatch.setattr(
        loop_report_module,
        "emit_event_sync",
        lambda _db, *, event_type, **_kwargs: events.append(event_type),
    )
    monkeypatch.setattr(
        loop_report_module,
        "create_job",
        lambda *_args, **_kwargs: None,
    )

    result = loop_report_module.loop_report_operator(
        _op_input(
            run_id=uuid7(),
            cycle_id=cycle_id,
            charter_id=charter_id,
            payload={"cycle_id": str(cycle_id)},
        )
    )

    assert result.success is True
    assert "completion_report_generated" in events[0]
    report_path = tmp_path / "reports" / "cycles" / str(cycle_id) / "completion" / "report.md"
    assert report_path.exists()
    markdown = report_path.read_text(encoding="utf-8")
    assert "## Executive Summary" in markdown
    assert "## Frontier Progression" in markdown
    assert "## Recommendations" in markdown
    introspection_path = (
        tmp_path / "reports" / "cycles" / str(cycle_id) / "introspection" / "report.md"
    )
    assert introspection_path.exists()
    introspection = introspection_path.read_text(encoding="utf-8")
    assert "## What Was Attempted" in introspection
    assert "## Interpretation" in introspection


def test_loop_report_still_closes_cycle_when_consolidation_enqueue_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cycle_id = uuid7()
    charter_id = uuid7()
    recommendation_id = uuid7()
    decision = SimpleNamespace(
        id=uuid7(),
        cycle_id=cycle_id,
        charter_id=charter_id,
        run_record_id=uuid7(),
        recommendation_id=recommendation_id,
        iteration_number=1,
        decision="stop_exhausted",
        gate_triggered=None,
        next_action=None,
        context_summary_path=None,
        reasoning="No remaining viable hypotheses.",
        hypothesis_card_id=None,
        next_hypothesis_card_id=None,
    )
    main_session = _LoopReportSession(
        decisions=[decision],
        budget=SimpleNamespace(
            total_runs=2,
            wall_clock_elapsed_s=120.0,
            runs_per_hypothesis={},
        ),
        cards=[SimpleNamespace(id=uuid7(), title="Hypothesis A", status="stalled")],
        frontiers=[],
        recommendation=SimpleNamespace(
            id=recommendation_id,
            recommendation_type="halt",
            action="Stop",
            reasoning="Done.",
        ),
    )
    enqueue_session = _EnqueueSession()

    monkeypatch.setattr(
        loop_report_module,
        "get_sync_session_factory",
        lambda: _SequentialFactory([main_session, enqueue_session]),
    )
    monkeypatch.setattr(
        loop_report_module,
        "get_settings",
        lambda: SimpleNamespace(data_root=tmp_path),
    )
    monkeypatch.setattr(
        result_introspection_module,
        "get_settings",
        lambda: SimpleNamespace(data_root=tmp_path),
    )
    monkeypatch.setattr(
        loop_report_module,
        "generate_executive_summary",
        lambda *_args, **_kwargs: "Executive summary for the autonomy loop.",
    )
    monkeypatch.setattr(
        loop_report_module,
        "emit_event_sync",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        loop_report_module,
        "create_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("db flush failed")),
    )

    result = loop_report_module.loop_report_operator(
        _op_input(
            run_id=uuid7(),
            cycle_id=cycle_id,
            charter_id=charter_id,
            payload={"cycle_id": str(cycle_id)},
        )
    )

    assert result.success is True
    assert main_session.committed is True
    assert enqueue_session.rolled_back is True
    report_path = tmp_path / "reports" / "cycles" / str(cycle_id) / "completion" / "report.md"
    assert report_path.exists()
    introspection_path = (
        tmp_path / "reports" / "cycles" / str(cycle_id) / "introspection" / "report.md"
    )
    assert introspection_path.exists()


@pytest.mark.asyncio
async def test_autonomy_report_endpoint_returns_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cycle_id = uuid7()
    report_dir = tmp_path / "reports" / "cycles" / str(cycle_id) / "completion"
    report_dir.mkdir(parents=True)
    (report_dir / "report.md").write_text("# Test Report\n", encoding="utf-8")
    (report_dir / "report.json").write_text('{"ok": true}', encoding="utf-8")

    monkeypatch.setattr(autonomy_router, "read_report_file", read_report_file)
    monkeypatch.setattr(
        "libs.core.services.autonomy_service.get_settings",
        lambda: SimpleNamespace(data_root=tmp_path),
    )

    result = await autonomy_router.get_autonomy_report(cycle_id, db=SimpleNamespace())

    assert result.markdown == "# Test Report\n"
    assert result.json_payload == {"ok": True}


def test_recommend_emits_loop_started_for_first_autonomy_iteration(
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
        best_metric_value=0.91,
        runs_since_improvement=0,
        total_runs=3,
        successful_runs=3,
    )

    class _RecommendSession:
        def __init__(self) -> None:
            self.added: list[Any] = []

        def get(self, _model: Any, _key: Any) -> Any:
            return SimpleNamespace(config={"autonomy": {"mode": "autonomous"}})

        def execute(self, query: Any) -> _ScalarResult:
            query_text = str(query)
            if "FROM directional_signals" in query_text:
                return _ScalarResult(SimpleNamespace(signal="breakthrough"))
            if "count(*) AS count_1" in query_text and "failure_postmortems" in query_text:
                return _ScalarResult(0)
            if "FROM failure_postmortems" in query_text:
                return _ScalarResult(list_value=[])
            if "FROM run_recommendations" in query_text:
                return _ScalarResult(None)
            if "FROM verification_reports" in query_text:
                return _ScalarResult(SimpleNamespace(recommendation_id=None))
            if "count(*) AS count_1" in query_text and "loop_decisions" in query_text:
                return _ScalarResult(0)
            raise AssertionError(f"Unexpected query in recommend test: {query_text}")

        def add(self, obj: Any) -> None:
            self.added.append(obj)

        def commit(self) -> None:
            return None

    session = _RecommendSession()
    events: list[str] = []
    queued_jobs: list[str] = []

    monkeypatch.setattr(
        recommend_module,
        "get_sync_session_factory",
        lambda: _SequentialFactory([session]),
    )
    monkeypatch.setattr(recommend_module, "load_run_record", lambda _db, _run_id: run)
    monkeypatch.setattr(recommend_module, "load_experiment_spec", lambda _db, _sid: spec)
    monkeypatch.setattr(recommend_module, "load_frontier", lambda *_args, **_kwargs: frontier)
    monkeypatch.setattr(recommend_module, "load_lineage_actions", lambda _db, _rid: [])
    monkeypatch.setattr(recommend_module, "load_lineage_run_ids", lambda _db, _rid: [run.id])
    monkeypatch.setattr(
        recommend_module,
        "emit_event_sync",
        lambda _db, *, event_type, **_kwargs: events.append(event_type),
    )
    monkeypatch.setattr(
        "libs.core.services.job_service.create_job",
        lambda _db, *, cycle_id, job_type, payload=None, priority=0: queued_jobs.append(job_type),
    )

    result = recommend_module.recommend_operator(
        _op_input(
            run_id=run.id,
            cycle_id=run.cycle_id,
            charter_id=run.charter_id,
            payload={"run_record_id": str(run.id)},
        )
    )

    assert result.success is True
    assert "autonomy.loop_started" in events
    assert "loop_decide" in queued_jobs
