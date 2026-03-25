"""Integration tests for Phase D pattern memory control plane and API surfaces."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.main import app, get_db
from libs.core.config import AppConfig
from libs.core.ids import generate_public_id
from libs.storage import services
from libs.storage.base import Base
from libs.storage.models import (
    ExperimentSpecModel,
    FailurePostmortemModel,
    HypothesisCardModel,
    ResearchCharterModel,
    ResearchCycleModel,
    RunRecordModel,
    VerificationReportModel,
)

AUTH_HEADERS = {"Authorization": "Bearer lab-local-admin"}


class FakePatternEmbedder:
    def __init__(self, _config: AppConfig):
        pass

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, _text: str) -> list[float]:
        return [1.0, 0.0]


class FakePatternGateway:
    def call_structured(self, *, role, messages, temperature, max_tokens):
        del role, temperature, max_tokens
        prompt = messages[0]["content"]
        if "canonical failure pattern" in prompt:
            return {
                "title": "Shared OOM failure",
                "description": "Repeated out-of-memory failures under similar settings.",
                "category": "failure/resource/oom",
                "polarity": "negative",
                "trigger_conditions": ["oom_or_resource_limit"],
                "proven_actions": [
                    {
                        "action": "reduce batch size",
                        "success_rate": 0.8,
                        "evidence_count": 2,
                    }
                ],
                "disproven_actions": ["retry unchanged"],
                "staleness_context": {"hardware": "cpu-small"},
            }
        if "canonical method pattern" in prompt:
            return {
                "title": "Reliable baseline tuning",
                "description": "Simple tuning changes that repeatedly improve the baseline.",
                "category": "method/optimization/baseline",
                "polarity": "positive",
                "trigger_conditions": ["baseline accuracy plateaus"],
                "proven_actions": [
                    {
                        "action": "tune the baseline before scaling",
                        "success_rate": 0.9,
                        "evidence_count": 2,
                    }
                ],
                "disproven_actions": [],
                "staleness_context": {"hardware": "cpu-small"},
            }
        return {
            "title": "Frontier breakthrough signal",
            "description": "Repeated frontier improvements that indicate a real breakthrough.",
            "category": "signal/frontier/breakthrough",
            "polarity": "positive",
            "trigger_conditions": ["directional signal is breakthrough"],
            "proven_actions": [
                {
                    "action": "prioritize follow-up validation",
                    "success_rate": 0.85,
                    "evidence_count": 2,
                }
            ],
            "disproven_actions": ["dismiss as noise"],
            "staleness_context": {"hardware": "cpu-small"},
        }


def _make_config(tmp_path: Path) -> AppConfig:
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        "\n".join([
            "memory:",
            "  enabled: true",
            "  consolidation_interval_hours: 24",
            "  min_cluster_size: 2",
            "  min_charters_for_pattern: 2",
            "  similarity_threshold: 0.75",
        ]),
        encoding="utf-8",
    )
    cfg = AppConfig(
        env="test",
        db_url=f"sqlite:///{tmp_path / 'test.db'}",
        data_root=tmp_path / "data",
        model_config_path=Path("configs/models/routes.yaml"),
        policy_config_path=policy_path,
        skill_paths=[Path("skills")],
        auto_init_db=False,
    )
    cfg.ensure_data_dirs()
    return cfg


def _build_run(
    *,
    cycle_id: int,
    spec_id: int,
    status: str,
    verification_outcome: str | None,
    failure_classification: str | None = None,
    metrics_summary: dict[str, float] | None = None,
) -> RunRecordModel:
    now = datetime.now(UTC)
    return RunRecordModel(
        public_id=generate_public_id("run"),
        cycle_id=cycle_id,
        experiment_spec_id=spec_id,
        status=status,
        execution_profile="cpu-small",
        workspace_path="/tmp/workspace",
        artifact_root="/tmp/artifacts",
        image="python:3.12-slim",
        build_recipe={},
        command=["python", "train.py"],
        env_vars={},
        mounts=[],
        hardware_profile="cpu-small",
        timeout_seconds=60,
        memory_limit_mb=1024,
        cpu_limit="2",
        gpu_enabled=False,
        network_mode="disabled",
        bound_skill_keys=[],
        prompt_lineage=[],
        model_lineage=[],
        latest_resource_snapshot={},
        metrics_summary=metrics_summary or {},
        artifact_manifest={},
        failure_classification=failure_classification,
        verification_outcome=verification_outcome,
        attempt_count=1,
        started_at=now,
        completed_at=now,
    )


def _seed_pattern_observations(session) -> None:
    for index in range(2):
        charter = ResearchCharterModel(
            public_id=generate_public_id("charter"),
            title=f"Pattern charter {index}",
            problem_statement="Improve bounded experiments.",
            success_criteria={},
            budget_envelope={},
            source_scope={},
            stop_conditions={},
            constraints={"hardware_profile": "cpu-small"},
        )
        session.add(charter)
        session.flush()

        cycle = ResearchCycleModel(
            public_id=generate_public_id("cycle"),
            charter_id=charter.id,
            current_status="ready",
        )
        session.add(cycle)
        session.flush()

        hypothesis = HypothesisCardModel(
            public_id=generate_public_id("hyp"),
            cycle_id=cycle.id,
            title="Tune baseline",
            statement="A small tuning pass will improve the baseline.",
            rationale="Repeatedly useful.",
            approach_summary="Adjust key hyperparameters first.",
            supporting_evidence=[],
            counter_evidence=[],
            status="approved",
            model_route_id="hypothesis_gen",
            prompt_id="prompt",
        )
        session.add(hypothesis)
        session.flush()

        spec = ExperimentSpecModel(
            public_id=generate_public_id("spec"),
            cycle_id=cycle.id,
            hypothesis_card_id=hypothesis.id,
            title="Baseline tuning spec",
            objective="Tune a bounded baseline.",
            baseline_description="Untuned baseline.",
            method_description="Tune learning rate and regularization.",
            controls=[],
            metrics=[{"name": "accuracy", "higher_is_better": True}],
            datasets=[],
            artifacts=[],
            stop_conditions=[],
            expected_outputs=[],
            status="approved",
            validation_issues=[],
            rejection_reason=None,
            estimated_runtime_minutes=5,
            gpu_required=False,
            resource_requirements={},
            model_route_id="protocol",
            prompt_id="prompt",
        )
        session.add(spec)
        session.flush()

        success_run = _build_run(
            cycle_id=cycle.id,
            spec_id=spec.id,
            status="succeeded",
            verification_outcome="robust",
            metrics_summary={"accuracy": 0.9 + index * 0.01},
        )
        failed_run = _build_run(
            cycle_id=cycle.id,
            spec_id=spec.id,
            status="failed",
            verification_outcome=None,
            failure_classification="oom_or_resource_limit",
        )
        session.add(success_run)
        session.add(failed_run)
        session.flush()

        verification = VerificationReportModel(
            public_id=generate_public_id("ver"),
            cycle_id=cycle.id,
            run_record_id=success_run.id,
            experiment_spec_id=spec.id,
            hypothesis_card_id=hypothesis.id,
            outcome="robust",
            outcome_rationale="Improved clearly.",
            baseline_comparison={"delta": 0.1},
            historical_comparisons=[],
            metric_sanity_checks=[],
            artifact_checks=[],
            output_contract_checks=[],
            leakage_signals=[],
            split_validation={},
            rerun_note=None,
            reviewer_summary="Strong improvement.",
            model_route_id="verifier",
            prompt_id="prompt",
            directional_signal="breakthrough",
            directional_signal_detail={"frontier": {"best_value": 0.9 + index * 0.01}},
            self_critic_result={},
        )
        session.add(verification)

        postmortem = FailurePostmortemModel(
            public_id=generate_public_id("pm"),
            cycle_id=cycle.id,
            run_record_id=failed_run.id,
            verification_report_id=None,
            failure_class="oom_or_resource_limit",
            failure_stage="execution",
            root_cause_summary="Batch size exceeded memory budget.",
            contributing_factors=[{"factor": "large batch"}],
            remediation_suggestions=[{"suggestion": "reduce batch size"}],
            retrieval_hints=[],
            protocol_update_hints=[],
            similar_prior_failures=[],
            model_route_id="verifier",
            prompt_id="prompt",
        )
        session.add(postmortem)

    session.commit()


def test_pattern_consolidation_and_curation_api(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    engine = create_engine(config.db_url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    try:
        with patch("libs.core.config.get_config", return_value=config), patch(
            "apps.api.main.get_config", return_value=config,
        ):
            with factory() as session:
                services.seed_dev_client_and_token(session, config)
                services.sync_skill_catalog(session, config)
                _seed_pattern_observations(session)

            with TestClient(app, raise_server_exceptions=True) as client, patch(
                "libs.adapters.embeddings.sentence_transformers.SentenceTransformerEmbeddingAdapter",
                FakePatternEmbedder,
            ), patch(
                "libs.orchestration.operators.ModelGateway.from_config",
                return_value=FakePatternGateway(),
            ):
                response = client.post(
                    "/api/v1/patterns/consolidate",
                    headers=AUTH_HEADERS,
                )
                assert response.status_code == 200
                assert response.json()["status"] == "queued"

                worker = client.post(
                    "/api/v1/admin/worker/run-once",
                    headers=AUTH_HEADERS,
                )
                assert worker.status_code == 200
                assert worker.json()["result"] == "job_succeeded"

                patterns = client.get("/api/v1/patterns", headers=AUTH_HEADERS)
                assert patterns.status_code == 200
                titles = {item["title"] for item in patterns.json()["patterns"]}
                assert {
                    "Shared OOM failure",
                    "Reliable baseline tuning",
                    "Frontier breakthrough signal",
                }.issubset(titles)

                categories = client.get("/api/v1/patterns/categories", headers=AUTH_HEADERS)
                assert categories.status_code == 200
                category_roots = {item["name"] for item in categories.json()["categories"]}
                assert {"failure", "method", "signal"}.issubset(category_roots)

                pattern_id = patterns.json()["patterns"][0]["public_id"]
                curate = client.post(
                    f"/api/v1/patterns/{pattern_id}/curate",
                    headers=AUTH_HEADERS,
                    json={
                        "action": "refine",
                        "category": "failure/resource/oom",
                        "refinement_notes": "Confirmed after cross-charter review.",
                    },
                )
                assert curate.status_code == 200

                detail = client.get(
                    f"/api/v1/patterns/{pattern_id}",
                    headers=AUTH_HEADERS,
                )
                assert detail.status_code == 200
                assert detail.json()["curation_notes"][0]["note"] == (
                    "Confirmed after cross-charter review."
                )
    finally:
        app.dependency_overrides.clear()
