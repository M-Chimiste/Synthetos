"""Tests for recovery/resume flows: state machine, checkpoints, resume logic, crash recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.core.state_machine import ALLOWED_TRANSITIONS, CycleStatus, ensure_transition
from libs.execution import TRANSIENT_FAILURES
from libs.orchestration.worker import OPERATOR_PIPELINES, next_operator_after

# ---------------------------------------------------------------------------
# State machine: RESUMING transitions
# ---------------------------------------------------------------------------


class TestResumingState:
    def test_resuming_is_a_valid_status(self) -> None:
        assert CycleStatus.RESUMING == "resuming"

    def test_paused_can_transition_to_resuming(self) -> None:
        ensure_transition(CycleStatus.PAUSED, CycleStatus.RESUMING)

    def test_failed_can_transition_to_resuming(self) -> None:
        ensure_transition(CycleStatus.FAILED, CycleStatus.RESUMING)

    def test_resuming_can_transition_to_running(self) -> None:
        ensure_transition(CycleStatus.RESUMING, CycleStatus.RUNNING)

    def test_resuming_can_transition_to_verifying(self) -> None:
        ensure_transition(CycleStatus.RESUMING, CycleStatus.VERIFYING)

    def test_resuming_can_transition_to_failed(self) -> None:
        ensure_transition(CycleStatus.RESUMING, CycleStatus.FAILED)

    def test_resuming_can_transition_to_initializing(self) -> None:
        ensure_transition(CycleStatus.RESUMING, CycleStatus.INITIALIZING)

    def test_resuming_can_transition_to_queued(self) -> None:
        ensure_transition(CycleStatus.RESUMING, CycleStatus.QUEUED)

    def test_resuming_cannot_transition_to_paused(self) -> None:
        with pytest.raises(ValueError, match="Invalid cycle transition"):
            ensure_transition(CycleStatus.RESUMING, CycleStatus.PAUSED)

    def test_created_cannot_transition_to_resuming(self) -> None:
        with pytest.raises(ValueError, match="Invalid cycle transition"):
            ensure_transition(CycleStatus.CREATED, CycleStatus.RESUMING)

    def test_running_cannot_transition_to_resuming(self) -> None:
        with pytest.raises(ValueError, match="Invalid cycle transition"):
            ensure_transition(CycleStatus.RUNNING, CycleStatus.RESUMING)

    def test_all_transitions_are_symmetric(self) -> None:
        """If A -> RESUMING is allowed, RESUMING should have at least one outbound transition."""
        sources = [
            s for s, targets in ALLOWED_TRANSITIONS.items()
            if CycleStatus.RESUMING in targets
        ]
        assert len(sources) >= 2  # At least PAUSED and FAILED
        assert len(ALLOWED_TRANSITIONS[CycleStatus.RESUMING]) >= 3


# ---------------------------------------------------------------------------
# next_operator_after — resume pipeline logic
# ---------------------------------------------------------------------------


class TestNextOperatorAfter:
    def test_explore_pipeline_sequence(self) -> None:
        assert next_operator_after("initialize_cycle") == "source_retrieval"
        assert next_operator_after("source_retrieval") == "literature_screen"
        assert next_operator_after("literature_screen") == "shortlist_rank"

    def test_execution_pipeline_sequence(self) -> None:
        assert next_operator_after("run_prepare") == "run_execute"
        assert next_operator_after("run_execute") == "run_finalize"

    def test_verification_pipeline_sequence(self) -> None:
        assert next_operator_after("run_verify") == "failure_postmortem"
        assert next_operator_after("failure_postmortem") == "verification_report"

    def test_last_operator_returns_none(self) -> None:
        assert next_operator_after("literature_report") is None
        assert next_operator_after("run_finalize") is None
        assert next_operator_after("verification_report") is None

    def test_unknown_operator_returns_none(self) -> None:
        assert next_operator_after("nonexistent_operator") is None

    def test_all_pipeline_operators_are_in_registry(self) -> None:
        from libs.orchestration.operators import OPERATOR_REGISTRY

        for pipeline_name, operators in OPERATOR_PIPELINES.items():
            for op in operators:
                assert op in OPERATOR_REGISTRY, (
                    f"Operator '{op}' from pipeline '{pipeline_name}' not in OPERATOR_REGISTRY"
                )


# ---------------------------------------------------------------------------
# TRANSIENT_FAILURES set
# ---------------------------------------------------------------------------


class TestTransientFailures:
    def test_transient_set_is_not_empty(self) -> None:
        assert len(TRANSIENT_FAILURES) >= 2

    def test_runtime_exception_is_transient(self) -> None:
        assert "runtime_exception" in TRANSIENT_FAILURES

    def test_dependency_failure_is_transient(self) -> None:
        assert "dependency_failure" in TRANSIENT_FAILURES

    def test_timeout_is_not_transient(self) -> None:
        assert "timeout" not in TRANSIENT_FAILURES

    def test_oom_is_not_transient(self) -> None:
        assert "oom_or_resource_limit" not in TRANSIENT_FAILURES


# ---------------------------------------------------------------------------
# Crash recovery: reclaim_expired_leases marks cycles FAILED
# ---------------------------------------------------------------------------


class TestCrashRecovery:
    @pytest.fixture()
    def db_session(self) -> Session:
        from libs.storage.base import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        session = factory()
        yield session
        session.close()
        engine.dispose()

    def test_reclaim_expired_leases_marks_cycle_failed(self, db_session: Session) -> None:
        from libs.core.ids import generate_public_id
        from libs.storage.models import JobModel, ResearchCharterModel, ResearchCycleModel

        # Create a charter and cycle
        charter = ResearchCharterModel(
            public_id=generate_public_id("charter"),
            title="Test",
            problem_statement="Test problem",
        )
        db_session.add(charter)
        db_session.flush()

        cycle = ResearchCycleModel(
            public_id=generate_public_id("cycle"),
            charter_id=charter.id,
            current_status=CycleStatus.RUNNING.value,
        )
        db_session.add(cycle)
        db_session.flush()

        # Create a stale job with expired lease
        job = JobModel(
            public_id=generate_public_id("job"),
            cycle_id=cycle.id,
            operator_name="run_execute",
            status="claimed",
            payload={},
            attempts=1,
            max_attempts=3,
            claimed_by="worker-1",
            lease_expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        db_session.add(job)
        db_session.flush()

        from libs.orchestration.job_queue import reclaim_expired_leases

        reclaimed = reclaim_expired_leases(db_session)
        assert reclaimed == 1
        assert job.status == "pending"
        assert cycle.current_status == CycleStatus.FAILED.value
        assert "lease expired" in (cycle.last_error or "").lower()

    def test_reclaim_does_not_affect_paused_cycles(self, db_session: Session) -> None:
        from libs.core.ids import generate_public_id
        from libs.storage.models import JobModel, ResearchCharterModel, ResearchCycleModel

        charter = ResearchCharterModel(
            public_id=generate_public_id("charter"),
            title="Test",
            problem_statement="Test",
        )
        db_session.add(charter)
        db_session.flush()

        cycle = ResearchCycleModel(
            public_id=generate_public_id("cycle"),
            charter_id=charter.id,
            current_status=CycleStatus.PAUSED.value,
        )
        db_session.add(cycle)
        db_session.flush()

        job = JobModel(
            public_id=generate_public_id("job"),
            cycle_id=cycle.id,
            operator_name="run_execute",
            status="claimed",
            payload={},
            attempts=1,
            max_attempts=3,
            claimed_by="worker-1",
            lease_expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        db_session.add(job)
        db_session.flush()

        from libs.orchestration.job_queue import reclaim_expired_leases

        reclaimed = reclaim_expired_leases(db_session)
        assert reclaimed == 1
        assert job.status == "pending"
        # Paused cycle should NOT be changed to failed
        assert cycle.current_status == CycleStatus.PAUSED.value
