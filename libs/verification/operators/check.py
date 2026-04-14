"""verification_check operator -- compares metrics to baseline, checks
artifact presence, validates output contracts, and creates a VerificationReport.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.core.event_types import VerificationEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.execution.operators._common import (
    ExecutionStateError,
    load_run_record,
    run_record_id_from_payload,
)
from libs.patterns.embedding import embed_text
from libs.patterns.injection import InjectionPolicy, inject_patterns
from libs.storage.base import get_sync_session_factory
from libs.storage.models.experiment import ExperimentSpec, RunRecord, VerificationReport
from libs.storage.models.research import ResearchCycle
from libs.verification.baseline import compare_to_baseline
from libs.verification.contracts import check_artifact_contract
from libs.verification.operators._common import enqueue_next_verification

log = get_logger("verification.check")


def _build_output_contract(
    *,
    artifact_manifest: list[dict],
    expected_artifacts: list[dict],
) -> dict[str, list[dict]]:
    checks: list[dict] = []
    manifest_by_name = {artifact["name"]: artifact for artifact in artifact_manifest}

    for expected in expected_artifacts:
        name = expected.get("name", "")
        artifact_type = str(expected.get("type", "") or "").lower()
        found = manifest_by_name.get(name)
        if found is None:
            checks.append(
                {
                    "name": name,
                    "pass": not expected.get("required", True),
                    "detail": "artifact missing from manifest",
                }
            )
            continue

        inferred_suffix = Path(str(found.get("path") or name)).suffix.lower().lstrip(".")
        type_ok = not artifact_type or artifact_type == inferred_suffix or artifact_type == "file"
        checks.append(
            {
                "name": name,
                "pass": type_ok,
                "detail": (
                    f"expected type {artifact_type or 'any'}, "
                    f"found path {found.get('path', name)}"
                ),
            }
        )

    return {"checks": checks}


def _build_metric_sanity(
    *,
    run_metrics: dict[str, float],
    spec_metrics: list[dict],
    prior_metrics: dict[str, float] | None,
) -> dict[str, list[dict]]:
    spec_by_name = {
        str(metric.get("name")): metric
        for metric in spec_metrics
        if metric.get("name")
    }
    checks: list[dict] = []

    for name, value in run_metrics.items():
        metric_spec = spec_by_name.get(name, {})
        range_min = metric_spec.get("min")
        range_max = metric_spec.get("max")
        in_range = True
        detail_parts = [f"value={value:.4f}"]
        if range_min is not None:
            in_range = in_range and value >= float(range_min)
            detail_parts.append(f"min={float(range_min):.4f}")
        if range_max is not None:
            in_range = in_range and value <= float(range_max)
            detail_parts.append(f"max={float(range_max):.4f}")

        if prior_metrics and name in prior_metrics:
            detail_parts.append(f"prior={float(prior_metrics[name]):.4f}")

        checks.append(
            {
                "name": name,
                "pass": in_range,
                "detail": ", ".join(detail_parts),
            }
        )

    missing = sorted(set(spec_by_name) - set(run_metrics))
    for name in missing:
        checks.append({"name": name, "pass": False, "detail": "expected metric missing"})

    extras = sorted(set(run_metrics) - set(spec_by_name))
    for name in extras:
        checks.append({"name": name, "pass": True, "detail": "extra metric present"})

    return {"checks": checks}


def verification_check_operator(op_input: OperatorInput) -> OperatorResult:
    factory = get_sync_session_factory()
    try:
        run_id = run_record_id_from_payload(op_input)
    except ExecutionStateError as exc:
        return OperatorResult(success=False, error=str(exc))

    with factory() as db:
        run = load_run_record(db, run_id)
        spec = db.get(ExperimentSpec, run.experiment_spec_id)
        if spec is None:
            return OperatorResult(success=False, error="experiment spec not found")
        cycle = db.get(ResearchCycle, run.cycle_id)

        emit_event_sync(
            db,
            event_type=VerificationEvents.check_started.value,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            payload={"run_record_id": str(run.id)},
        )

        # If the run failed (non-zero exit or metric parse), skip baseline comparison
        if run.status == "failed":
            report = VerificationReport(
                id=uuid7(),
                run_record_id=run.id,
                charter_id=run.charter_id,
                cycle_id=run.cycle_id,
                verdict="failed",
                baseline_comparison=None,
                artifact_checks=None,
                output_contract=None,
                metric_sanity=None,
                warnings=[f"run failed: {run.error or run.failure_class or 'unknown'}"],
                summary=f"Verification skipped: run failed ({run.failure_class or 'unknown'})",
                created_at=utcnow(),
            )
            db.add(report)

            emit_event_sync(
                db,
                event_type=VerificationEvents.check_completed.value,
                charter_id=run.charter_id,
                cycle_id=run.cycle_id,
                payload={
                    "run_record_id": str(run.id),
                    "verdict": "failed",
                    "reason": "run_failed",
                },
            )

            enqueue_next_verification(
                db,
                cycle_id=run.cycle_id,
                next_job_type="auto_remediate",
                run_record_id=run.id,
            )
            db.commit()
            return OperatorResult(
                success=True,
                summary="Run failed; created failure report; enqueued auto_remediate",
            )

        # Run completed successfully — full verification
        run_metrics = run.metrics_output or {}
        spec_metrics = spec.metrics or []
        baseline = spec.baseline or {}
        expected_artifacts = spec.expected_artifacts or []
        artifact_manifest = run.artifact_manifest or []

        pattern_context = "\n".join(
            [
                spec.title,
                spec.description,
                json.dumps(spec.metrics or [], sort_keys=True),
                json.dumps(run.metrics_output or {}, sort_keys=True),
                run.failure_class or "",
            ]
        ).strip()
        pattern_matches = inject_patterns(
            db,
            charter_id=run.charter_id,
            current_cycle_id=run.cycle_id,
            types=["signal_trajectory", "failure"],
            policy=InjectionPolicy.from_cycle_config(cycle.config if cycle else None),
            problem_profile_embedding=embed_text(pattern_context),
            operator_name="verification_check",
        )
        pattern_ids = [str(match.pattern.id) for match in pattern_matches]

        prior_run = db.execute(
            select(RunRecord)
            .where(RunRecord.experiment_spec_id == run.experiment_spec_id)
            .where(RunRecord.id != run.id)
            .where(RunRecord.status == "completed")
            .order_by(RunRecord.completed_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        prior_metrics = dict(prior_run.metrics_output or {}) if prior_run else None

        # 1. Baseline comparison
        metric_verdicts = compare_to_baseline(run_metrics, spec_metrics, baseline)
        baseline_comparison = {
            v.name: {
                "baseline": v.baseline_value,
                "actual": v.value,
                "delta": v.delta,
                "direction": v.direction,
                "pass": v.passed,
                "detail": v.detail,
            }
            for v in metric_verdicts
        }

        # 2. Artifact checks
        artifact_checks_result = check_artifact_contract(artifact_manifest, expected_artifacts)
        artifact_checks = [
            {
                "name": c.name,
                "expected": c.expected,
                "found": c.found,
                "required": c.required,
                "pass": c.passed,
                "detail": c.detail,
            }
            for c in artifact_checks_result
        ]
        output_contract = _build_output_contract(
            artifact_manifest=artifact_manifest,
            expected_artifacts=expected_artifacts,
        )
        metric_sanity = _build_metric_sanity(
            run_metrics=run_metrics,
            spec_metrics=spec_metrics,
            prior_metrics=prior_metrics,
        )

        # 3. Determine verdict
        metrics_all_pass = all(v.passed for v in metric_verdicts)
        artifacts_all_pass = all(c.passed for c in artifact_checks_result)
        output_contract_pass = all(check["pass"] for check in output_contract["checks"])
        metric_sanity_pass = all(check["pass"] for check in metric_sanity["checks"])
        has_thresholds = any(
            m.get("threshold") is not None for m in spec_metrics
        )

        warnings = []

        if metrics_all_pass and artifacts_all_pass and output_contract_pass and metric_sanity_pass:
            if has_thresholds:
                verdict = "passed"
            else:
                verdict = "inconclusive"
                warnings.append("no metric thresholds defined; verdict is informational")
        else:
            verdict = "failed"
            failed_metrics = [v.name for v in metric_verdicts if not v.passed]
            failed_artifacts = [c.name for c in artifact_checks_result if not c.passed]
            failed_output_checks = [
                check["name"] for check in output_contract["checks"] if not check["pass"]
            ]
            failed_sanity_checks = [
                check["name"] for check in metric_sanity["checks"] if not check["pass"]
            ]
            if failed_metrics:
                warnings.append(f"failed metrics: {', '.join(failed_metrics)}")
            if failed_artifacts:
                warnings.append(f"missing artifacts: {', '.join(failed_artifacts)}")
            if failed_output_checks:
                warnings.append(f"output contract issues: {', '.join(failed_output_checks)}")
            if failed_sanity_checks:
                warnings.append(f"metric sanity issues: {', '.join(failed_sanity_checks)}")
        if prior_run is not None:
            warnings.append(f"historical comparison anchor: run {prior_run.id}")
        if pattern_ids:
            warnings.append(f"pattern priors applied: {', '.join(pattern_ids)}")

        summary_parts = [f"Verdict: {verdict}"]
        if metric_verdicts:
            summary_parts.append(
                f"{sum(1 for v in metric_verdicts if v.passed)}/{len(metric_verdicts)} "
                "metrics passed"
            )
        if artifact_checks_result:
            summary_parts.append(
                f"{sum(1 for c in artifact_checks_result if c.passed)}/"
                f"{len(artifact_checks_result)} artifacts present"
            )

        report = VerificationReport(
            id=uuid7(),
            run_record_id=run.id,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            verdict=verdict,
            baseline_comparison=baseline_comparison,
            artifact_checks=artifact_checks,
            output_contract=output_contract,
            metric_sanity=metric_sanity,
            warnings=warnings or None,
            summary="; ".join(summary_parts),
            created_at=utcnow(),
        )
        db.add(report)

        emit_event_sync(
            db,
            event_type=VerificationEvents.check_completed.value,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            payload={
                "run_record_id": str(run.id),
                "verdict": verdict,
            },
        )

        if verdict == "failed":
            enqueue_next_verification(
                db,
                cycle_id=run.cycle_id,
                next_job_type="auto_remediate",
                run_record_id=run.id,
            )
            db.commit()
            return OperatorResult(
                success=True,
                summary=f"Verification failed; enqueued auto_remediate. {'; '.join(summary_parts)}",
            )

        # Passed or inconclusive — enqueue signal classification
        enqueue_next_verification(
            db,
            cycle_id=run.cycle_id,
            next_job_type="signal_classify",
            run_record_id=run.id,
        )
        db.commit()

    return OperatorResult(
        success=True,
        summary=f"{'; '.join(summary_parts)}; enqueued signal_classify",
    )
