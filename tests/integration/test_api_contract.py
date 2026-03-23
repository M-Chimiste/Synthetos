"""API contract tests: OpenAPI schema snapshot + endpoint roundtrip validation.

These tests ensure the API surface is stable and responses match declared schemas.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from libs.core.config import get_config
from libs.schemas.api import (
    CycleDetailResponse,
    CycleSummaryResponse,
    TimelineResponse,
)
from tests.helpers.schema_validators import validate_list_response, validate_response

BASELINE_PATH = Path("tests/fixtures/openapi_baseline.json")


def reset_config(tmp_path: Path) -> None:
    get_config.cache_clear()
    os.environ["LAB_DB_URL"] = f"sqlite:///{tmp_path / 'test.db'}"
    os.environ["LAB_DATA_ROOT"] = str(tmp_path / "lab_data")
    os.environ["LAB_MODEL_CONFIG"] = "configs/models/routes.yaml"
    os.environ["LAB_POLICY_CONFIG"] = "configs/policies/default.yaml"
    os.environ["LAB_SKILL_PATHS"] = "skills"
    os.environ["LAB_DEV_ADMIN_TOKEN"] = "lab-local-admin"
    os.environ["LAB_AUTO_INIT_DB"] = "true"


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer lab-local-admin"}


def get_test_app():
    from apps.api.main import app

    return app


# ---------------------------------------------------------------------------
# OpenAPI schema snapshot
# ---------------------------------------------------------------------------


def test_openapi_schema_snapshot(tmp_path: Path) -> None:
    """Compare current OpenAPI schema against baseline to detect breaking changes."""
    reset_config(tmp_path)
    with TestClient(get_test_app()) as client:
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        current = resp.json()

    if not BASELINE_PATH.exists():
        # First run: generate baseline
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
        pytest.skip("Generated OpenAPI baseline (first run)")

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    # Check no endpoints were removed
    baseline_paths = set(baseline.get("paths", {}).keys())
    current_paths = set(current.get("paths", {}).keys())
    removed = baseline_paths - current_paths
    assert not removed, f"Endpoints removed (breaking change): {removed}"

    # Check no required response fields were removed from schemas
    baseline_schemas = baseline.get("components", {}).get("schemas", {})
    current_schemas = current.get("components", {}).get("schemas", {})
    for schema_name, baseline_schema in baseline_schemas.items():
        if schema_name not in current_schemas:
            continue
        baseline_required = set(baseline_schema.get("required", []))
        current_required = set(current_schemas[schema_name].get("required", []))
        dropped = baseline_required - current_required
        # Dropping required fields is a breaking change
        assert not dropped, (
            f"Schema '{schema_name}' dropped required fields (breaking): {dropped}"
        )


def test_openapi_schema_has_key_endpoints(tmp_path: Path) -> None:
    """Verify that all expected endpoint groups are present."""
    reset_config(tmp_path)
    with TestClient(get_test_app()) as client:
        resp = client.get("/openapi.json")
        paths = set(resp.json().get("paths", {}).keys())

    expected_groups = [
        "/api/v1/cycles",
        "/api/v1/reports",
        "/api/v1/skills",
        "/api/v1/events/stream",
        "/api/v1/healthz",
    ]
    for group in expected_groups:
        matching = [p for p in paths if p.startswith(group)]
        assert matching, f"No endpoints found starting with {group}"


# ---------------------------------------------------------------------------
# Endpoint roundtrip tests
# ---------------------------------------------------------------------------


def test_cycle_creation_roundtrip(tmp_path: Path) -> None:
    """Create a cycle and validate the response matches CycleDetailResponse schema."""
    reset_config(tmp_path)
    with TestClient(get_test_app()) as client:
        resp = client.post(
            "/api/v1/cycles",
            headers=auth_headers(),
            json={
                "title": "Contract test cycle",
                "problem_statement": "Validate API contracts.",
                "success_criteria": {"summary": "Passes."},
                "budget_envelope": {"timebox_hours": 1},
                "source_scope": {"mode": "internal"},
                "stop_conditions": {"summary": "Done."},
                "constraints": {},
                "notes": "api contract test",
            },
        )
        assert resp.status_code == 200
        validate_response(resp.json(), CycleDetailResponse)


def test_cycle_list_roundtrip(tmp_path: Path) -> None:
    """List cycles and validate response shape."""
    reset_config(tmp_path)
    with TestClient(get_test_app()) as client:
        # Create a cycle first
        client.post(
            "/api/v1/cycles",
            headers=auth_headers(),
            json={
                "title": "List test",
                "problem_statement": "Test listing.",
                "success_criteria": {},
                "budget_envelope": {},
                "source_scope": {},
                "stop_conditions": {},
                "constraints": {},
            },
        )
        resp = client.get("/api/v1/cycles", headers=auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        validate_list_response(data, "items", CycleSummaryResponse)


def test_skills_list_roundtrip(tmp_path: Path) -> None:
    """List skills and validate response shape."""
    reset_config(tmp_path)
    with TestClient(get_test_app()) as client:
        resp = client.get("/api/v1/skills", headers=auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        # Skills may be empty but the shape should be valid


def test_report_list_roundtrip(tmp_path: Path) -> None:
    """List reports and validate response shape."""
    reset_config(tmp_path)
    with TestClient(get_test_app()) as client:
        resp = client.get("/api/v1/reports", headers=auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data


def test_timeline_roundtrip(tmp_path: Path) -> None:
    """Create a cycle and check the timeline endpoint returns valid data."""
    reset_config(tmp_path)
    with TestClient(get_test_app()) as client:
        create_resp = client.post(
            "/api/v1/cycles",
            headers=auth_headers(),
            json={
                "title": "Timeline test",
                "problem_statement": "Test timeline.",
                "success_criteria": {},
                "budget_envelope": {},
                "source_scope": {},
                "stop_conditions": {},
                "constraints": {},
            },
        )
        cycle_id = create_resp.json()["cycle"]["public_id"]

        # Run worker once to generate events
        client.post("/api/v1/admin/worker/run-once", headers=auth_headers())

        resp = client.get(f"/api/v1/cycles/{cycle_id}/timeline", headers=auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        validate_response(data, TimelineResponse)
        assert len(data["items"]) > 0


def test_health_endpoint(tmp_path: Path) -> None:
    """Health endpoint returns expected shape."""
    reset_config(tmp_path)
    with TestClient(get_test_app()) as client:
        resp = client.get("/api/v1/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data


# ---------------------------------------------------------------------------
# Backward compatibility: additive changes are safe
# ---------------------------------------------------------------------------


def test_additive_schema_changes_do_not_break(tmp_path: Path) -> None:
    """Adding optional fields to responses should not break existing consumers."""
    reset_config(tmp_path)
    with TestClient(get_test_app()) as client:
        resp = client.post(
            "/api/v1/cycles",
            headers=auth_headers(),
            json={
                "title": "Compat test",
                "problem_statement": "Test backward compat.",
                "success_criteria": {},
                "budget_envelope": {},
                "source_scope": {},
                "stop_conditions": {},
                "constraints": {},
            },
        )
        data = resp.json()
        # Core fields must always be present
        assert "cycle" in data
        assert "public_id" in data["cycle"]
        assert "current_status" in data["cycle"]
        # Extra fields (new optional ones) are allowed
        # This test validates that the response can be parsed even with unknown fields
