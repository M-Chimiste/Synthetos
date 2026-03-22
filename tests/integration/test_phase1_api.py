"""Integration tests for Phase 1 literature intake pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.main import app, get_db
from libs.adapters.literature import RawPaperRecord
from libs.core.config import AppConfig
from libs.storage.base import Base

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _sample_papers() -> list[RawPaperRecord]:
    with open(FIXTURES_DIR / "sample_papers.json") as f:
        data = json.load(f)
    return [RawPaperRecord.model_validate(item) for item in data]


@pytest.fixture()
def tmp_config(tmp_path):
    cfg = AppConfig(
        env="test",
        db_url=f"sqlite:///{tmp_path / 'test.db'}",
        data_root=str(tmp_path / "data"),
        model_config_path="configs/models/routes.yaml",
        policy_config_path="configs/policies/default.yaml",
        skill_paths=["skills"],
        auto_init_db=False,
    )
    cfg.ensure_data_dirs()
    (tmp_path / "data" / "artifacts" / "literature").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "corpus").mkdir(parents=True, exist_ok=True)
    return cfg


@pytest.fixture()
def test_session(tmp_config):
    engine = create_engine(tmp_config.db_url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return factory


@pytest.fixture()
def client(tmp_config, test_session):
    from libs.storage import services

    def override_db():
        session = test_session()
        try:
            yield session
        finally:
            session.close()

    def override_config():
        return tmp_config

    app.dependency_overrides[get_db] = override_db

    with patch("libs.core.config.get_config", return_value=tmp_config):
        with patch("apps.api.main.get_config", return_value=tmp_config):
            # Seed dev client and sync skills
            with test_session() as session:
                services.seed_dev_client_and_token(session, tmp_config)
                services.sync_skill_catalog(session, tmp_config)

            tc = TestClient(app, raise_server_exceptions=True)
            yield tc

    app.dependency_overrides.clear()


AUTH_HEADERS = {"Authorization": "Bearer lab-local-admin"}


def _create_cycle(client: TestClient) -> dict:
    payload = {
        "title": "Phase 1 Test Cycle",
        "problem_statement": "Investigate neural architecture search methods for efficient ML.",
        "success_criteria": {"summary": "Produce a credible literature screening report"},
        "budget_envelope": {"timebox_hours": 2},
        "source_scope": {
            "mode": "arxiv",
            "categories": ["cs"],
            "date_from": "2024-01-01",
            "date_until": "2024-01-31",
            "max_results": 10,
        },
        "stop_conditions": {"summary": "Literature report generated"},
        "constraints": {},
    }
    resp = client.post("/api/v1/cycles", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    return resp.json()


def _run_worker(client: TestClient) -> str:
    resp = client.post("/api/v1/admin/worker/run-once", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    return resp.json()["result"]


def test_start_intake_command(client):
    """Test that start_intake enqueues the source_retrieval job."""
    cycle_data = _create_cycle(client)
    cycle_id = cycle_data["cycle"]["public_id"]

    # Run initialize_cycle first
    result = _run_worker(client)
    assert result == "job_succeeded"

    # Now start intake
    resp = client.post(
        f"/api/v1/cycles/{cycle_id}/commands",
        json={"command": "start_intake"},
        headers=AUTH_HEADERS,
    )
    if resp.status_code != 200:
        print(f"start_intake error: {resp.text}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cycle"]["current_status"] == "queued"

    # Verify job was enqueued
    jobs_resp = client.get("/api/v1/jobs", headers=AUTH_HEADERS)
    jobs = jobs_resp.json()["items"]
    operator_names = [j["operator_name"] for j in jobs]
    assert "source_retrieval" in operator_names


def test_list_papers_endpoint(client):
    """Test paper listing after simulated ingestion."""
    cycle_data = _create_cycle(client)
    cycle_id = cycle_data["cycle"]["public_id"]

    # Initially no papers
    resp = client.get(f"/api/v1/cycles/{cycle_id}/papers", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_literature_triage_endpoint(client):
    """Test literature triage summary endpoint."""
    cycle_data = _create_cycle(client)
    cycle_id = cycle_data["cycle"]["public_id"]

    resp = client.get(f"/api/v1/cycles/{cycle_id}/literature", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_papers"] == 0
    assert "retrieval_sessions" in data


def test_full_literature_pipeline_with_mock_adapters(client, tmp_config):
    """Full pipeline test with mocked arXiv adapter (no real network calls)."""
    cycle_data = _create_cycle(client)
    cycle_id = cycle_data["cycle"]["public_id"]

    # Run initialize_cycle
    assert _run_worker(client) == "job_succeeded"

    # Start intake
    resp = client.post(
        f"/api/v1/cycles/{cycle_id}/commands",
        json={"command": "start_intake"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200

    # Mock the ArxivMetadataAdapter to return sample papers
    sample = _sample_papers()
    with patch(
        "libs.orchestration.operators.ArxivMetadataAdapter"
    ) as MockAdapter:
        mock_instance = MagicMock()
        mock_instance.search.return_value = sample
        MockAdapter.return_value = mock_instance

        # Run source_retrieval
        result = _run_worker(client)
        assert result == "job_succeeded"

    # Check papers were ingested
    resp = client.get(f"/api/v1/cycles/{cycle_id}/papers", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    papers = resp.json()
    assert papers["total"] == 3

    # Mock the LLM gateway for screening
    mock_llm_response = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "decision": "advance",
                    "score": 0.8,
                    "rationale": "Relevant to ML research."
                })
            }
        }]
    }

    with patch(
        "libs.adapters.llm.gateway.ModelGateway.call_chat_completion",
        return_value=mock_llm_response,
    ):
        # Run literature_screen (may loop)
        result = _run_worker(client)
        assert result == "job_succeeded"

    # Run shortlist_rank
    result = _run_worker(client)
    assert result == "job_succeeded"

    # Mock fulltext fetcher (skip real HTTP)
    with patch(
        "libs.orchestration.operators.FulltextFetcher"
    ) as MockFetcher:
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_html.return_value = None
        mock_fetcher.fetch_pdf.return_value = None
        MockFetcher.return_value = mock_fetcher

        # Run fulltext_escalation
        result = _run_worker(client)
        assert result == "job_succeeded"

    # Run literature_report
    result = _run_worker(client)
    assert result == "job_succeeded"

    # Verify literature report exists
    resp = client.get(f"/api/v1/cycles/{cycle_id}", headers=AUTH_HEADERS)
    detail = resp.json()
    report_titles = [r["title"] for r in detail["reports"]]
    assert any("Literature Screening Report" in t for t in report_titles)

    # Verify literature triage summary
    resp = client.get(f"/api/v1/cycles/{cycle_id}/literature", headers=AUTH_HEADERS)
    triage = resp.json()
    assert triage["total_papers"] == 3
    assert triage["shortlisted_count"] > 0
