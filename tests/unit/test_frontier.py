"""Tests for metric frontier persistence: upsert, improvement tracking, unique constraints."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.core.ids import generate_public_id
from libs.storage.models import (
    ExperimentSpecModel,
    HypothesisCardModel,
    MetricFrontierModel,
    ResearchCharterModel,
    ResearchCycleModel,
    RunRecordModel,
)
from libs.storage.services import upsert_metric_frontier


class TestUpsertMetricFrontier:
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
        )
        db_session.add(hyp)
        db_session.flush()

        spec = ExperimentSpecModel(
            public_id=generate_public_id("spec"),
            cycle_id=cycle.id,
            hypothesis_card_id=hyp.id,
            title="Spec",
            objective="Objective",
            baseline_description="Baseline",
            method_description="Method",
            controls=[],
            metrics=[{"name": "accuracy"}],
            datasets=[],
            artifacts=[],
            stop_conditions=[],
            expected_outputs=[],
            gpu_required=False,
            status="valid",
            prompt_id="prompt",
            model_route_id="route",
        )
        db_session.add(spec)
        db_session.flush()

        run = RunRecordModel(
            public_id=generate_public_id("run"),
            cycle_id=cycle.id,
            experiment_spec_id=spec.id,
            status="succeeded",
            execution_profile="cpu-small",
            workspace_path="/tmp/run",
            artifact_root="/tmp/artifacts",
            image="python:3.12",
            build_recipe={},
            command=["python", "train.py"],
            env_vars={},
            mounts=[],
            hardware_profile="cpu-small",
            timeout_seconds=60,
            memory_limit_mb=512,
            network_mode="disabled",
            bound_skill_keys=[],
            prompt_lineage=[],
            model_lineage=[],
            latest_resource_snapshot={},
            metrics_summary={"accuracy": 0.85},
            artifact_manifest={},
            attempt_count=1,
        )
        db_session.add(run)
        db_session.flush()

        return {
            "charter": charter,
            "cycle": cycle,
            "hyp": hyp,
            "spec": spec,
            "run": run,
        }

    def test_creates_new_frontier(self, db_session: Session, seed: dict) -> None:
        frontier = upsert_metric_frontier(
            db_session,
            hypothesis_card_id=seed["hyp"].id,
            charter_id=seed["charter"].id,
            metric_name="accuracy",
            best_value=0.85,
            best_run_public_id=seed["run"].public_id,
            best_run_id=seed["run"].id,
            current_run_id=seed["run"].id,
            higher_is_better=True,
        )

        assert frontier.best_value == 0.85
        assert frontier.runs_since_improvement == 0
        assert frontier.metric_name == "accuracy"

    def test_updates_on_improvement(self, db_session: Session, seed: dict) -> None:
        # Create initial frontier
        upsert_metric_frontier(
            db_session,
            hypothesis_card_id=seed["hyp"].id,
            charter_id=seed["charter"].id,
            metric_name="accuracy",
            best_value=0.85,
            best_run_public_id="old-run",
            best_run_id=seed["run"].id,
            current_run_id=seed["run"].id,
            higher_is_better=True,
        )

        # Update with improvement
        frontier = upsert_metric_frontier(
            db_session,
            hypothesis_card_id=seed["hyp"].id,
            charter_id=seed["charter"].id,
            metric_name="accuracy",
            best_value=0.90,
            best_run_public_id=seed["run"].public_id,
            best_run_id=seed["run"].id,
            current_run_id=seed["run"].id,
            higher_is_better=True,
        )

        assert frontier.best_value == 0.90
        assert frontier.runs_since_improvement == 0

    def test_increments_on_no_improvement(self, db_session: Session, seed: dict) -> None:
        upsert_metric_frontier(
            db_session,
            hypothesis_card_id=seed["hyp"].id,
            charter_id=seed["charter"].id,
            metric_name="accuracy",
            best_value=0.90,
            best_run_public_id="best-run",
            best_run_id=seed["run"].id,
            current_run_id=seed["run"].id,
            higher_is_better=True,
        )

        # No improvement
        frontier = upsert_metric_frontier(
            db_session,
            hypothesis_card_id=seed["hyp"].id,
            charter_id=seed["charter"].id,
            metric_name="accuracy",
            best_value=0.85,
            best_run_public_id=seed["run"].public_id,
            best_run_id=seed["run"].id,
            current_run_id=seed["run"].id,
            higher_is_better=True,
        )

        assert frontier.best_value == 0.90  # unchanged
        assert frontier.runs_since_improvement == 1

    def test_unique_per_hypothesis_metric(self, db_session: Session, seed: dict) -> None:
        upsert_metric_frontier(
            db_session,
            hypothesis_card_id=seed["hyp"].id,
            charter_id=seed["charter"].id,
            metric_name="accuracy",
            best_value=0.85,
            best_run_public_id=seed["run"].public_id,
            best_run_id=seed["run"].id,
            current_run_id=seed["run"].id,
            higher_is_better=True,
        )

        # Different metric = different row
        upsert_metric_frontier(
            db_session,
            hypothesis_card_id=seed["hyp"].id,
            charter_id=seed["charter"].id,
            metric_name="loss",
            best_value=0.3,
            best_run_public_id=seed["run"].public_id,
            best_run_id=seed["run"].id,
            current_run_id=seed["run"].id,
            higher_is_better=False,
        )

        count = db_session.query(MetricFrontierModel).count()
        assert count == 2


class TestMetricFrontierModel:
    def test_in_metadata(self) -> None:
        """MetricFrontierModel is registered in SQLAlchemy metadata."""
        from libs.storage.base import Base

        assert "metric_frontiers" in Base.metadata.tables
