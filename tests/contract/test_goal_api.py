"""Goal API contract tests."""

from __future__ import annotations

from apps.api.main import app


def test_openapi_exposes_goal_routes() -> None:
    schema = app.openapi()
    paths = schema["paths"]

    assert "/api/v1/goals" in paths
    assert "/api/v1/goals/{goal_id}" in paths
    assert "/api/v1/goals/{goal_id}/attempts" in paths
    assert "/api/v1/goals/{goal_id}/report" in paths
    assert "/api/v1/goals/{goal_id}/results" in paths
    assert "/api/v1/goals/{goal_id}/stop" in paths
    assert "/api/v1/cycles/{cycle_id}/introspection" in paths
    assert "/api/v1/runs/{run_id}/artifacts" in paths
    assert "/api/v1/runs/{run_id}/artifacts/{artifact_id}" in paths
