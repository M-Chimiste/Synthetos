"""Integration tests for Phase 2 evidence/hypothesis/protocol pipeline."""

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

    app.dependency_overrides[get_db] = override_db

    with patch("libs.core.config.get_config", return_value=tmp_config):
        with patch("apps.api.main.get_config", return_value=tmp_config):
            with test_session() as session:
                services.seed_dev_client_and_token(session, tmp_config)
                services.sync_skill_catalog(session, tmp_config)

            tc = TestClient(app, raise_server_exceptions=True)
            yield tc

    app.dependency_overrides.clear()


AUTH_HEADERS = {"Authorization": "Bearer lab-local-admin"}


def _create_cycle(client: TestClient) -> dict:
    payload = {
        "title": "Phase 2 Test Cycle",
        "problem_statement": "Investigate neural architecture search methods for efficient ML.",
        "success_criteria": {"summary": "Produce evidence cards and experiment spec"},
        "budget_envelope": {"timebox_hours": 2},
        "source_scope": {
            "mode": "arxiv",
            "categories": ["cs"],
            "date_from": "2024-01-01",
            "date_until": "2024-01-31",
            "max_results": 10,
            "fulltext_budget": {"max_fetches": 1},
        },
        "stop_conditions": {"summary": "Protocol compiled"},
        "constraints": {},
    }
    resp = client.post("/api/v1/cycles", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    return resp.json()


def _run_worker(client: TestClient) -> str:
    resp = client.post("/api/v1/admin/worker/run-once", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    return resp.json()["result"]


def _run_phase1(client: TestClient, cycle_id: str) -> None:
    """Run entire Phase 1 pipeline with mocked adapters."""
    # Initialize
    assert _run_worker(client) == "job_succeeded"

    # Start intake
    resp = client.post(
        f"/api/v1/cycles/{cycle_id}/commands",
        json={"command": "start_intake"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200

    # Source retrieval (mock arXiv)
    sample = _sample_papers()
    with patch("libs.orchestration.operators.ArxivMetadataAdapter") as MockAdapter:
        mock_instance = MagicMock()
        mock_instance.search.return_value = sample
        MockAdapter.return_value = mock_instance
        assert _run_worker(client) == "job_succeeded"

    # Literature screen (mock LLM)
    mock_llm_screening = json.dumps({
        "decision": "advance", "score": 0.8,
        "rationale": "Relevant to ML research.",
    })
    with patch(
        "libs.adapters.llm.gateway.ModelGateway.call_chat_completion",
        return_value=mock_llm_screening,
    ):
        assert _run_worker(client) == "job_succeeded"

    # Shortlist rank
    assert _run_worker(client) == "job_succeeded"

    # Fulltext escalation (mock fetcher)
    with patch("libs.orchestration.operators.FulltextFetcher") as MockFetcher:
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_html.return_value = None
        mock_fetcher.fetch_pdf.return_value = None
        MockFetcher.return_value = mock_fetcher
        assert _run_worker(client) == "job_succeeded"

    # Literature report
    assert _run_worker(client) == "job_succeeded"


def test_start_evidence_command(client):
    """Test that start_evidence enqueues the evidence_extraction job."""
    cycle_data = _create_cycle(client)
    cycle_id = cycle_data["cycle"]["public_id"]
    _run_phase1(client, cycle_id)

    resp = client.post(
        f"/api/v1/cycles/{cycle_id}/commands",
        json={"command": "start_evidence"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["cycle"]["current_status"] == "queued"

    jobs_resp = client.get("/api/v1/jobs", headers=AUTH_HEADERS)
    jobs = jobs_resp.json()["items"]
    operator_names = [j["operator_name"] for j in jobs]
    assert "evidence_extraction" in operator_names


def test_evidence_list_endpoint(client):
    """Test evidence listing endpoint returns empty initially."""
    cycle_data = _create_cycle(client)
    cycle_id = cycle_data["cycle"]["public_id"]

    resp = client.get(f"/api/v1/cycles/{cycle_id}/evidence", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_hypothesis_list_endpoint(client):
    """Test hypothesis listing endpoint returns empty initially."""
    cycle_data = _create_cycle(client)
    cycle_id = cycle_data["cycle"]["public_id"]

    resp = client.get(
        f"/api/v1/cycles/{cycle_id}/hypotheses", headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_portfolio_ranking_endpoint(client):
    """Test portfolio ranking endpoint returns empty initially."""
    cycle_data = _create_cycle(client)
    cycle_id = cycle_data["cycle"]["public_id"]

    resp = client.get(
        f"/api/v1/cycles/{cycle_id}/hypotheses/portfolio",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["ranking_method"] == "composite_score"


def test_experiment_spec_list_endpoint(client):
    """Test experiment spec listing endpoint returns empty initially."""
    cycle_data = _create_cycle(client)
    cycle_id = cycle_data["cycle"]["public_id"]

    resp = client.get(
        f"/api/v1/cycles/{cycle_id}/experiment-specs",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def _load_fixture(name: str) -> str:
    with open(FIXTURES_DIR / name) as f:
        return f.read()


def test_full_phase2_pipeline_with_mocks(client, tmp_config):
    """Full Phase 2 pipeline: evidence → hypotheses → critique → protocol."""
    cycle_data = _create_cycle(client)
    cycle_id = cycle_data["cycle"]["public_id"]

    # Run Phase 1 first
    _run_phase1(client, cycle_id)

    # Start evidence extraction
    resp = client.post(
        f"/api/v1/cycles/{cycle_id}/commands",
        json={"command": "start_evidence"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200

    # Mock LLM for evidence extraction
    evidence_fixture = _load_fixture("sample_evidence_response.json")
    with patch(
        "libs.adapters.llm.gateway.ModelGateway.call_chat_completion",
        return_value=evidence_fixture,
    ):
        result = _run_worker(client)
        assert result == "job_succeeded"

    # Verify evidence cards created
    resp = client.get(f"/api/v1/cycles/{cycle_id}/evidence", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    evidence_data = resp.json()
    assert evidence_data["total"] > 0

    # Check evidence summary
    resp = client.get(
        f"/api/v1/cycles/{cycle_id}/evidence/summary", headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["total_evidence"] > 0

    # Mock LLM for hypothesis generation
    hypotheses_fixture = _load_fixture("sample_hypotheses_response.json")
    with patch(
        "libs.adapters.llm.gateway.ModelGateway.call_chat_completion",
        return_value=hypotheses_fixture,
    ):
        result = _run_worker(client)
        assert result == "job_succeeded"

    # Verify hypotheses created
    resp = client.get(
        f"/api/v1/cycles/{cycle_id}/hypotheses", headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    hyp_data = resp.json()
    assert hyp_data["total"] == 3

    # Mock LLM for hypothesis critique
    critique_fixture = _load_fixture("sample_critique_response.json")
    with patch(
        "libs.adapters.llm.gateway.ModelGateway.call_chat_completion",
        return_value=critique_fixture,
    ):
        result = _run_worker(client)
        assert result == "job_succeeded"

    # Verify portfolio ranking
    resp = client.get(
        f"/api/v1/cycles/{cycle_id}/hypotheses/portfolio",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    portfolio = resp.json()
    assert portfolio["total"] == 3
    assert portfolio["hypotheses"][0]["portfolio_rank"] == 1

    # Mock LLM for protocol compilation
    protocol_fixture = _load_fixture("sample_protocol_response.json")
    with patch(
        "libs.adapters.llm.gateway.ModelGateway.call_chat_completion",
        return_value=protocol_fixture,
    ):
        result = _run_worker(client)
        assert result == "job_succeeded"

    # Verify experiment spec created
    resp = client.get(
        f"/api/v1/cycles/{cycle_id}/experiment-specs",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    specs = resp.json()
    assert specs["total"] == 1
    assert specs["items"][0]["status"] == "valid"
    assert specs["items"][0]["gpu_required"] is True

    # Verify Phase 2 report generated
    resp = client.get(f"/api/v1/cycles/{cycle_id}", headers=AUTH_HEADERS)
    detail = resp.json()
    report_titles = [r["title"] for r in detail["reports"]]
    assert any("Protocol Compilation" in t for t in report_titles)

    # Verify cycle is in READY state with phase2_complete context
    state = detail.get("current_state_snapshot")
    assert state is not None
    assert state["context"].get("phase") == "phase2_complete"
