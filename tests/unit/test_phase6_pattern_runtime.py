"""Focused Phase 6 pattern runtime tests."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from uuid_utils import uuid7

from libs.core.operators import OperatorInput
from libs.discovery.operators import search as search_operator
from libs.patterns.retrieval import find_relevant_patterns
from libs.verification.operators import check as verification_check_module


class _ScalarResult:
    def __init__(self, scalar_value=None, list_value=None):
        self._scalar_value = scalar_value
        self._list_value = list_value or []

    def scalar_one_or_none(self):
        return self._scalar_value

    def scalar_one(self):
        return self._scalar_value

    def scalars(self):
        return self

    def all(self):
        return self._list_value


class _PatternSession:
    def __init__(self, patterns):
        self._patterns = patterns

    def execute(self, _stmt):
        return _ScalarResult(list_value=self._patterns)


class _DiscoverySession:
    def __init__(self, cycle):
        self.cycle = cycle
        self.added = []
        self.committed = False

    def get(self, model, _key):
        if getattr(model, "__name__", "") == "ResearchCycle":
            return self.cycle
        return None

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True


class _Factory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc, tb):
        return False


class _VerificationSession:
    def __init__(self, *, run, spec, cycle):
        self.run = run
        self.spec = spec
        self.cycle = cycle
        self.added = []
        self.committed = False

    def get(self, model, key):
        name = getattr(model, "__name__", "")
        if name == "ExperimentSpec":
            return self.spec
        if name == "ResearchCycle":
            return self.cycle
        return None

    def execute(self, query):
        text = str(query)
        if "FROM run_records" in text:
            return _ScalarResult(None)
        raise AssertionError(f"unexpected query: {text}")

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True


def _pattern(*, title: str, summary: str, confidence: float, embedding: list[float]):
    return SimpleNamespace(
        id=uuid7(),
        pattern_type="retrieval_heuristic",
        title=title,
        summary=summary,
        trust_tier="auto",
        evidence_count=2,
        confidence=confidence,
        staleness_score=0.0,
        source_charter_ids=[uuid7(), uuid7()],
        last_reinforced_at=search_operator.utcnow(),
        last_observed_at=search_operator.utcnow(),
        embedding=embedding,
        structured_body={},
    )


def _op_input(*, run_id: UUID, cycle_id: UUID, charter_id: UUID) -> OperatorInput:
    return OperatorInput(
        job_id=uuid7(),
        job_type="verification_check",
        cycle_id=cycle_id,
        charter_id=charter_id,
        payload={"run_record_id": str(run_id)},
    )


def test_find_relevant_patterns_prefers_similarity_when_embeddings_exist() -> None:
    near = _pattern(
        title="Near",
        summary="similar",
        confidence=0.55,
        embedding=[1.0, 0.0, 0.0],
    )
    far = _pattern(
        title="Far",
        summary="higher confidence but dissimilar",
        confidence=0.95,
        embedding=[0.0, 1.0, 0.0],
    )

    matches = find_relevant_patterns(
        _PatternSession([far, near]),
        charter_id=uuid7(),
        current_cycle_id=None,
        problem_profile_embedding=[1.0, 0.0, 0.0],
        limit=2,
    )

    assert [match.pattern.title for match in matches] == ["Near", "Far"]


def test_discovery_search_operator_injects_retrieval_patterns_into_query(monkeypatch) -> None:
    cycle_id = uuid7()
    discovery = SimpleNamespace(
        id=uuid7(),
        cycle_id=cycle_id,
        charter_id=uuid7(),
        profile_id=uuid7(),
        status="created",
        stats={},
        step_log=[],
    )
    profile = SimpleNamespace(
        id=discovery.profile_id,
        source_scope={},
        budget={},
        query_text="baseline query",
    )
    cycle = SimpleNamespace(config={"patterns": {"injection_limit": 2}})
    session = _DiscoverySession(cycle)
    captured: dict[str, object] = {}

    async def fake_run_search(*, profile_text, categories, scope, budget):
        captured["profile_text"] = profile_text
        captured["categories"] = categories
        return [], {"deduped": 0, "dropped_duplicates": 0, "sources_fused": 0}

    monkeypatch.setattr(search_operator, "get_sync_session_factory", lambda: _Factory(session))
    monkeypatch.setattr(search_operator, "load_session", lambda _db, _sid: discovery)
    monkeypatch.setattr(search_operator, "load_profile", lambda _db, _pid: profile)
    monkeypatch.setattr(search_operator, "embed_text", lambda _text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(search_operator, "_run_search", fake_run_search)
    monkeypatch.setattr(search_operator, "enqueue_next", lambda *_args, **_kwargs: None)

    def fake_inject_patterns(*_args, **kwargs):
        captured["embedding"] = kwargs["problem_profile_embedding"]
        return [
            SimpleNamespace(
                pattern=SimpleNamespace(
                    id=uuid7(),
                    structured_body={
                        "heuristic_kind": "loop_parameter_variation",
                        "parameters": {"next_action": "broaden_search"},
                    },
                )
            )
        ]

    monkeypatch.setattr(search_operator, "inject_patterns", fake_inject_patterns)

    result = search_operator.discovery_search_operator(
        OperatorInput(
            job_id=uuid7(),
            job_type="discovery_search",
            cycle_id=cycle_id,
            charter_id=discovery.charter_id,
            payload={"session_id": str(discovery.id)},
        )
    )

    assert result.success is True
    assert captured["embedding"] == [0.1, 0.2, 0.3]
    assert "loop parameter variation" in str(captured["profile_text"])
    assert "broaden search" in str(captured["profile_text"])
    assert session.committed is True


def test_verification_check_operator_records_pattern_priors(monkeypatch) -> None:
    run = SimpleNamespace(
        id=uuid7(),
        experiment_spec_id=uuid7(),
        charter_id=uuid7(),
        cycle_id=uuid7(),
        status="completed",
        metrics_output={"accuracy": 0.9},
        artifact_manifest=[{"name": "metrics.json", "path": "/artifacts/metrics.json"}],
        error=None,
        failure_class=None,
    )
    spec = SimpleNamespace(
        id=run.experiment_spec_id,
        title="Baseline classifier",
        description="Train a simple classifier.",
        metrics=[{"name": "accuracy"}],
        baseline={},
        expected_artifacts=[{"name": "metrics.json", "type": "json", "required": True}],
    )
    cycle = SimpleNamespace(config={"patterns": {"injection_limit": 1}})
    session = _VerificationSession(run=run, spec=spec, cycle=cycle)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        verification_check_module,
        "get_sync_session_factory",
        lambda: _Factory(session),
    )
    monkeypatch.setattr(
        verification_check_module,
        "load_run_record",
        lambda _db, _rid: run,
    )
    monkeypatch.setattr(
        verification_check_module,
        "compare_to_baseline",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        verification_check_module,
        "check_artifact_contract",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                name="metrics.json",
                expected=True,
                found=True,
                required=True,
                passed=True,
                detail="ok",
            )
        ],
    )
    monkeypatch.setattr(
        verification_check_module,
        "enqueue_next_verification",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        verification_check_module,
        "emit_event_sync",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(verification_check_module, "embed_text", lambda _text: [0.3, 0.2, 0.1])

    def fake_inject_patterns(*_args, **kwargs):
        captured["embedding"] = kwargs["problem_profile_embedding"]
        return [
            SimpleNamespace(
                pattern=SimpleNamespace(id=uuid7()),
            )
        ]

    monkeypatch.setattr(verification_check_module, "inject_patterns", fake_inject_patterns)

    result = verification_check_module.verification_check_operator(
        _op_input(run_id=run.id, cycle_id=run.cycle_id, charter_id=run.charter_id)
    )

    assert result.success is True
    assert captured["embedding"] == [0.3, 0.2, 0.1]
    report = session.added[0]
    assert any("pattern priors applied:" in warning for warning in (report.warnings or []))
