"""Tests for the metric frontier upsert logic."""

from __future__ import annotations

from unittest.mock import MagicMock

from uuid_utils import uuid7

from libs.remediation.frontier import _is_improvement, upsert_frontier


class TestIsImprovement:
    def test_maximize_higher_is_better(self) -> None:
        assert _is_improvement(0.9, 0.8, "maximize") is True
        assert _is_improvement(0.7, 0.8, "maximize") is False
        assert _is_improvement(0.8, 0.8, "maximize") is False

    def test_minimize_lower_is_better(self) -> None:
        assert _is_improvement(0.1, 0.2, "minimize") is True
        assert _is_improvement(0.3, 0.2, "minimize") is False
        assert _is_improvement(0.2, 0.2, "minimize") is False


class TestUpsertFrontier:
    def _make_db(self, existing_frontier=None):
        """Create a mock DB session."""
        db = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing_frontier
        db.execute.return_value = result
        return db

    def test_create_new_frontier(self) -> None:
        db = self._make_db(existing_frontier=None)
        charter_id = uuid7()
        hypothesis_card_id = uuid7()

        frontier, improved = upsert_frontier(
            db,
            charter_id=charter_id,
            hypothesis_card_id=hypothesis_card_id,
            experiment_spec_id=uuid7(),
            run_id=uuid7(),
            metric_name="accuracy",
            metric_direction="maximize",
            metric_value=0.85,
            is_successful=True,
        )

        assert improved is True
        assert frontier.best_metric_value == 0.85
        assert frontier.total_runs == 1
        assert frontier.successful_runs == 1
        assert frontier.runs_since_improvement == 0
        db.add.assert_called_once_with(frontier)

    def test_update_with_improvement(self) -> None:
        existing = MagicMock()
        existing.best_metric_value = 0.80
        existing.total_runs = 3
        existing.successful_runs = 2
        existing.runs_since_improvement = 1

        db = self._make_db(existing_frontier=existing)

        frontier, improved = upsert_frontier(
            db,
            charter_id=uuid7(),
            hypothesis_card_id=uuid7(),
            experiment_spec_id=uuid7(),
            run_id=uuid7(),
            metric_name="accuracy",
            metric_direction="maximize",
            metric_value=0.90,
            is_successful=True,
        )

        assert improved is True
        assert frontier.best_metric_value == 0.90
        assert frontier.total_runs == 4
        assert frontier.successful_runs == 3
        assert frontier.runs_since_improvement == 0

    def test_update_without_improvement(self) -> None:
        existing = MagicMock()
        existing.best_metric_value = 0.90
        existing.total_runs = 5
        existing.successful_runs = 4
        existing.runs_since_improvement = 0

        db = self._make_db(existing_frontier=existing)

        frontier, improved = upsert_frontier(
            db,
            charter_id=uuid7(),
            hypothesis_card_id=uuid7(),
            experiment_spec_id=uuid7(),
            run_id=uuid7(),
            metric_name="accuracy",
            metric_direction="maximize",
            metric_value=0.85,
            is_successful=True,
        )

        assert improved is False
        assert frontier.best_metric_value == 0.90  # unchanged
        assert frontier.total_runs == 6
        assert frontier.successful_runs == 5
        assert frontier.runs_since_improvement == 1

    def test_failed_run_increments_total_only(self) -> None:
        existing = MagicMock()
        existing.best_metric_value = 0.90
        existing.total_runs = 5
        existing.successful_runs = 4
        existing.runs_since_improvement = 0

        db = self._make_db(existing_frontier=existing)

        frontier, improved = upsert_frontier(
            db,
            charter_id=uuid7(),
            hypothesis_card_id=uuid7(),
            experiment_spec_id=uuid7(),
            run_id=uuid7(),
            metric_name="accuracy",
            metric_direction="maximize",
            metric_value=0.95,  # even though value is better
            is_successful=False,
        )

        assert improved is False  # not successful, so not an improvement
        assert frontier.total_runs == 6
        assert frontier.successful_runs == 4  # unchanged
        assert frontier.runs_since_improvement == 1
