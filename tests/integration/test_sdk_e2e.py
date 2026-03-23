"""Integration test: drive a cycle through the SDK against the real API."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from libs.core.config import get_config
from libs.sdk.client import SynthetoClient
from libs.sdk.exceptions import SynthetoNotFoundError


def reset_config(tmp_path: Path) -> None:
    get_config.cache_clear()
    os.environ["LAB_DB_URL"] = f"sqlite:///{tmp_path / 'test.db'}"
    os.environ["LAB_DATA_ROOT"] = str(tmp_path / "lab_data")
    os.environ["LAB_MODEL_CONFIG"] = "configs/models/routes.yaml"
    os.environ["LAB_POLICY_CONFIG"] = "configs/policies/default.yaml"
    os.environ["LAB_SKILL_PATHS"] = "skills"
    os.environ["LAB_DEV_ADMIN_TOKEN"] = "lab-local-admin"
    os.environ["LAB_AUTO_INIT_DB"] = "true"


def get_test_app():
    from apps.api.main import app
    return app


def _make_sdk_client(app_client: TestClient) -> SynthetoClient:
    """Create an SDK client wired to the TestClient's transport."""
    client = SynthetoClient(base_url="http://testserver")
    # Replace the internal httpx.Client with one using the test transport
    client._client.close()
    client._client = httpx.Client(
        transport=app_client._transport,
        base_url="http://testserver",
        headers={
            "Authorization": "Bearer lab-local-admin",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )
    return client


def test_sdk_create_and_list_cycle(tmp_path: Path) -> None:
    """Create a cycle via SDK, then list and verify it appears."""
    reset_config(tmp_path)
    with TestClient(get_test_app()) as app_client:
        sdk = _make_sdk_client(app_client)

        # Create cycle
        result = sdk.create_cycle({
            "title": "SDK E2E Test",
            "problem_statement": "Test the SDK end-to-end.",
            "success_criteria": {"summary": "Cycle created via SDK"},
            "budget_envelope": {"timebox_hours": 1},
            "source_scope": {"mode": "internal"},
            "stop_conditions": {"summary": "Done."},
            "constraints": {},
        })
        assert "cycle" in result
        cycle_id = result["cycle"]["public_id"]
        assert result["cycle"]["current_status"] == "queued"

        # Get cycle
        detail = sdk.get_cycle(cycle_id)
        assert detail["cycle"]["public_id"] == cycle_id

        # List cycles
        cycles = sdk.list_cycles()
        assert len(cycles["items"]) >= 1

        # List reports
        reports = sdk.list_reports()
        assert "items" in reports

        # List skills
        skills = sdk.list_skills()
        assert "items" in skills

        # Get timeline
        timeline = sdk.get_timeline(cycle_id)
        assert "items" in timeline
        assert len(timeline["items"]) >= 1

        # Health
        health = sdk.health()
        assert health["status"] == "ok"

        sdk.close()


def test_sdk_error_handling(tmp_path: Path) -> None:
    """SDK raises appropriate errors for bad requests."""
    reset_config(tmp_path)
    with TestClient(get_test_app()) as app_client:
        sdk = _make_sdk_client(app_client)

        with pytest.raises(SynthetoNotFoundError):
            sdk.get_cycle("nonexistent_cycle_id")

        sdk.close()
