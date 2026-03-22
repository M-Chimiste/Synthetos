from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from libs.core.config import get_config


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


def test_cycle_creation_worker_and_reports(tmp_path: Path) -> None:
    reset_config(tmp_path)
    with TestClient(get_test_app()) as client:
        create_response = client.post(
            "/api/v1/cycles",
            headers=auth_headers(),
            json={
                "title": "Test cycle",
                "problem_statement": "Bootstrap the Phase 0 control plane.",
                "success_criteria": {"summary": "Cycle reaches ready."},
                "budget_envelope": {"timebox_hours": 1},
                "source_scope": {"mode": "internal+arxiv"},
                "stop_conditions": {"summary": "Operator report exists."},
                "constraints": {"phase": "phase0"},
                "notes": "integration test",
            },
        )
        assert create_response.status_code == 200
        cycle_payload = create_response.json()
        assert cycle_payload["cycle"]["current_status"] == "queued"

        worker_response = client.post("/api/v1/admin/worker/run-once", headers=auth_headers())
        assert worker_response.status_code == 200
        assert worker_response.json()["result"] == "job_succeeded"

        cycle_id = cycle_payload["cycle"]["public_id"]
        detail_response = client.get(f"/api/v1/cycles/{cycle_id}", headers=auth_headers())
        detail = detail_response.json()
        assert detail["cycle"]["current_status"] == "ready"
        assert detail["reports"]
        assert detail["recent_events"]

        report_id = detail["reports"][0]["public_id"]
        report_response = client.get(f"/api/v1/reports/{report_id}", headers=auth_headers())
        assert report_response.status_code == 200
        assert "Initialization Report" in report_response.json()["markdown"]


def test_skill_catalog_available(tmp_path: Path) -> None:
    reset_config(tmp_path)
    with TestClient(get_test_app()) as client:
        response = client.get("/api/v1/skills", headers=auth_headers())
        assert response.status_code == 200
        payload = response.json()
        assert len(payload["items"]) >= 2
