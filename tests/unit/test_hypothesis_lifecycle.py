"""Tests for hypothesis lifecycle transitions and selection."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.core.ids import generate_public_id
from libs.ideation.hypothesis_lifecycle import (
    pick_next_hypothesis,
    transition_hypothesis,
)
from libs.storage.models import (
    HypothesisCardModel,
    ResearchCharterModel,
    ResearchCycleModel,
)


class TestTransitionHypothesis:
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

    @pytest.fixture()
    def hypothesis(self, db_session: Session) -> HypothesisCardModel:
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
            current_status="running",
        )
        db_session.add(cycle)
        db_session.flush()

        hyp = HypothesisCardModel(
            public_id=generate_public_id("hyp"),
            cycle_id=cycle.id,
            title="Test hypothesis",
            statement="Statement",
            rationale="Rationale",
            approach_summary="Approach",
            status="approved",
            model_route_id="route",
            prompt_id="prompt",
            portfolio_rank=1,
            portfolio_score=0.8,
        )
        db_session.add(hyp)
        db_session.flush()
        return hyp

    def test_valid_transitions(self, db_session: Session, hypothesis: HypothesisCardModel) -> None:
        # approved -> active
        transition_hypothesis(db_session, hypothesis, "active", "Loop selected")
        assert hypothesis.status == "active"

        # active -> promising
        transition_hypothesis(db_session, hypothesis, "promising", "Breakthrough")
        assert hypothesis.status == "promising"

        # promising -> validated
        transition_hypothesis(db_session, hypothesis, "validated", "Success criteria met")
        assert hypothesis.status == "validated"

    def test_invalid_transition_raises(
        self, db_session: Session, hypothesis: HypothesisCardModel,
    ) -> None:
        # approved -> stalled is not allowed
        with pytest.raises(ValueError, match="Invalid hypothesis transition"):
            transition_hypothesis(db_session, hypothesis, "stalled", "test")

    def test_active_to_stalled(self, db_session: Session, hypothesis: HypothesisCardModel) -> None:
        transition_hypothesis(db_session, hypothesis, "active", "Loop selected")
        transition_hypothesis(db_session, hypothesis, "stalled", "3 runs, no progress")
        assert hypothesis.status == "stalled"

    def test_active_to_deprioritized(
        self, db_session: Session, hypothesis: HypothesisCardModel,
    ) -> None:
        transition_hypothesis(db_session, hypothesis, "active", "Loop selected")
        transition_hypothesis(db_session, hypothesis, "deprioritized", "Regressing")
        assert hypothesis.status == "deprioritized"

    def test_deprioritized_is_terminal(
        self, db_session: Session, hypothesis: HypothesisCardModel,
    ) -> None:
        transition_hypothesis(db_session, hypothesis, "active", "Selected")
        transition_hypothesis(db_session, hypothesis, "deprioritized", "Regressing")
        with pytest.raises(ValueError):
            transition_hypothesis(db_session, hypothesis, "active", "Try again")


class TestPickNextHypothesis:
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

    @pytest.fixture()
    def seed(self, db_session: Session) -> dict:
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
            current_status="running",
        )
        db_session.add(cycle)
        db_session.flush()

        hyp_active = HypothesisCardModel(
            public_id=generate_public_id("hyp"),
            cycle_id=cycle.id,
            title="Active hypothesis",
            statement="s", rationale="r", approach_summary="a",
            status="active",
            model_route_id="r", prompt_id="p",
            portfolio_rank=1, portfolio_score=0.9,
        )
        hyp_approved = HypothesisCardModel(
            public_id=generate_public_id("hyp"),
            cycle_id=cycle.id,
            title="Approved hypothesis",
            statement="s", rationale="r", approach_summary="a",
            status="approved",
            model_route_id="r", prompt_id="p",
            portfolio_rank=2, portfolio_score=0.7,
        )
        hyp_stalled = HypothesisCardModel(
            public_id=generate_public_id("hyp"),
            cycle_id=cycle.id,
            title="Stalled hypothesis",
            statement="s", rationale="r", approach_summary="a",
            status="stalled",
            model_route_id="r", prompt_id="p",
            portfolio_rank=3, portfolio_score=0.6,
        )
        db_session.add_all([hyp_active, hyp_approved, hyp_stalled])
        db_session.flush()

        return {
            "charter": charter,
            "cycle": cycle,
            "hyp_active": hyp_active,
            "hyp_approved": hyp_approved,
            "hyp_stalled": hyp_stalled,
        }

    def test_picks_active_first(self, db_session: Session, seed: dict) -> None:
        result = pick_next_hypothesis(db_session, seed["cycle"].id)
        assert result is not None
        assert result.status == "active"
        assert result.portfolio_rank == 1

    def test_skips_stalled(self, db_session: Session, seed: dict) -> None:
        # Exclude active hypothesis — should skip stalled and pick approved
        result = pick_next_hypothesis(
            db_session, seed["cycle"].id,
            exclude_hypothesis_id=seed["hyp_active"].id,
        )
        assert result is not None
        assert result.status == "approved"

    def test_returns_none_when_exhausted(self, db_session: Session, seed: dict) -> None:
        # Set all to stalled/deprioritized
        seed["hyp_active"].status = "stalled"
        seed["hyp_approved"].status = "deprioritized"
        db_session.flush()

        result = pick_next_hypothesis(db_session, seed["cycle"].id)
        # hyp_stalled is already stalled, so no selectable hypotheses
        assert result is None
