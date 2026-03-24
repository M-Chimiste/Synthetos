"""Integration tests for Phase C autonomous loop control-plane behavior."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.api.main import app, get_db
from libs.core.config import AppConfig
from libs.storage.base import Base
from libs.storage.models import JobModel

AUTH_HEADERS = {"Authorization": "Bearer lab-local-admin"}


def _run_worker(client: TestClient) -> None:
    resp = client.post("/api/v1/admin/worker/run-once", headers=AUTH_HEADERS)
    assert resp.status_code == 200


def _create_cycle(client: TestClient) -> str:
    resp = client.post(
        "/api/v1/cycles",
        headers=AUTH_HEADERS,
        json={
            "title": "Autonomous control-plane test",
            "problem_statement": "Verify the autonomous loop can be started from the API.",
            "success_criteria": {"primary_metric": "accuracy", "target_value": 0.9},
            "budget_envelope": {"max_runs_per_hypothesis": 2},
            "source_scope": {"mode": "internal"},
            "stop_conditions": {"summary": "stop when the loop completes"},
            "constraints": {},
        },
    )
    assert resp.status_code == 200
    return resp.json()["cycle"]["public_id"]


def _make_config(tmp_path) -> AppConfig:
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
    return cfg


def _seed_auth(session_factory, config: AppConfig) -> None:
    from libs.storage import services

    with session_factory() as session:
        services.seed_dev_client_and_token(session, config)
        services.sync_skill_catalog(session, config)


def test_start_autonomous_sets_mode_and_enqueues_loop(tmp_path) -> None:
    from libs.storage import services

    config = _make_config(tmp_path)
    engine = create_engine(config.db_url)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    _seed_auth(session_factory, config)

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    try:
        with patch("libs.core.config.get_config", return_value=config):
            with patch("apps.api.main.get_config", return_value=config):
                with TestClient(app, raise_server_exceptions=True) as client:
                    cycle_id = _create_cycle(client)
                    _run_worker(client)

                    response = client.post(
                        f"/api/v1/cycles/{cycle_id}/commands",
                        headers=AUTH_HEADERS,
                        json={"command": "start_autonomous"},
                    )
                    assert response.status_code == 200
                    data = response.json()
                    assert data["cycle"]["current_status"] == "queued"
                    assert data["cycle"]["autonomy_mode"] == "autonomous"
                    assert data["cycle"]["budget_max_runs_per_hypothesis"] == 2

                    with session_factory() as session:
                        cycle = services.get_cycle_by_public_id(session, cycle_id)
                        jobs = list(
                            session.scalars(
                                select(JobModel)
                                .where(JobModel.cycle_id == cycle.id)
                                .order_by(JobModel.created_at.desc())
                            ).all()
                        )

                    assert jobs
                    assert jobs[0].operator_name == "autonomous_loop_step"
                    assert jobs[0].payload["autonomous_loop_iteration"] == 1
                    assert jobs[0].payload["regeneration_attempted"] is False
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
