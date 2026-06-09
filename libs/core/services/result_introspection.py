"""Result introspection services for autonomous cycles and goals."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select

from libs.core.config import get_settings
from libs.schemas.results import (
    CycleResultIntrospection,
    GoalAttemptResult,
    GoalResultSummary,
    GoalRunResult,
    PublicationReadiness,
    RunArtifactRead,
)
from libs.storage.models.experiment import (
    ExperimentSpec,
    FailurePostmortem,
    RunRecord,
    VerificationReport,
)
from libs.storage.models.goals import GoalAttempt, ResearchGoal
from libs.storage.models.remediation import RemediationAction
from libs.storage.models.research import ResearchCycle


class ResultIntrospectionError(Exception):
    """Raised when introspection data or artifacts cannot be resolved."""


def cycle_introspection_paths(data_root: Path, cycle_id: UUID) -> dict[str, str]:
    root = data_root / "reports" / "cycles" / str(cycle_id) / "introspection"
    return {
        "root": str(root),
        "markdown": str(root / "report.md"),
        "json": str(root / "report.json"),
    }


def completion_report_paths(data_root: Path, cycle_id: UUID) -> dict[str, str | None]:
    root = data_root / "reports" / "cycles" / str(cycle_id) / "completion"
    markdown = root / "report.md"
    json_path = root / "report.json"
    return {
        "markdown": str(markdown) if markdown.exists() else None,
        "json": str(json_path) if json_path.exists() else None,
    }


def artifact_id_for_path(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]


def normalize_run_artifacts(run: RunRecord) -> list[RunArtifactRead]:
    artifacts: list[RunArtifactRead] = []
    for item in run.artifact_manifest or []:
        rel_path = str(item.get("path") or item.get("name") or "")
        if not rel_path:
            continue
        artifact_id = artifact_id_for_path(rel_path)
        artifacts.append(
            RunArtifactRead(
                artifact_id=artifact_id,
                run_id=_std_uuid(run.id),
                name=str(item.get("name") or Path(rel_path).name),
                path=rel_path,
                size_bytes=_as_int(item.get("size_bytes")),
                hash=str(item.get("hash")) if item.get("hash") else None,
                artifact_type=_artifact_type(rel_path),
                download_url=f"/api/v1/runs/{run.id}/artifacts/{artifact_id}",
            )
        )
    return artifacts


def resolve_run_artifact_path(
    session,
    run_id: UUID,
    artifact_id: str,
) -> tuple[Path, RunArtifactRead]:
    run = session.get(RunRecord, run_id)
    if run is None:
        raise ResultIntrospectionError("run not found")
    for artifact in normalize_run_artifacts(run):
        if artifact.artifact_id != artifact_id:
            continue
        root = (Path(get_settings().data_root) / "artifacts" / str(run.id)).resolve()
        rel_path = Path(artifact.path)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise ResultIntrospectionError("unsafe artifact path")
        file_path = (root / rel_path).resolve()
        try:
            file_path.relative_to(root)
        except ValueError as exc:
            raise ResultIntrospectionError("unsafe artifact path") from exc
        if not file_path.is_file():
            raise ResultIntrospectionError("artifact file not found")
        return file_path, artifact
    raise ResultIntrospectionError("artifact not found")


def build_cycle_result_introspection(
    session,
    cycle_id: UUID,
    *,
    write_files: bool = False,
) -> CycleResultIntrospection:
    cycle = session.get(ResearchCycle, cycle_id)
    if cycle is None:
        raise ResultIntrospectionError(f"cycle {cycle_id} not found")

    settings = get_settings()
    paths = cycle_introspection_paths(Path(settings.data_root), cycle_id)
    completion_paths = completion_report_paths(Path(settings.data_root), cycle_id)
    runs = _runs_for_cycles(session, [cycle_id])
    attempt = _attempt_for_cycle(session, cycle_id)
    goal_id = _goal_id_from_cycle(cycle)
    run_results = _build_run_results(
        session,
        runs,
        attempt_numbers={cycle_id: attempt.attempt_number if attempt else None},
    )
    metrics = _collect_metrics(run_results)
    model_artifacts = [a for r in run_results for a in r.artifacts if _is_model_artifact(a)]
    remediation_history = _remediation_history(session, [cycle_id])
    readiness = _publication_readiness(run_results)
    caveats = _cycle_caveats(run_results, readiness)
    interpretation = _interpret_cycle(run_results, readiness, caveats)
    next_steps = _next_steps(readiness, run_results)
    summary = _cycle_summary(run_results, readiness)

    payload = CycleResultIntrospection(
        cycle_id=_std_uuid(cycle.id),
        charter_id=_std_uuid(cycle.charter_id),
        goal_id=goal_id,
        publication_readiness=readiness,
        summary=summary,
        interpretation=interpretation,
        caveats=caveats,
        next_steps=next_steps,
        completion_report_path=completion_paths["markdown"],
        completion_report_json_path=completion_paths["json"],
        introspection_markdown_path=paths["markdown"],
        introspection_json_path=paths["json"],
        runs=run_results,
        metrics=metrics,
        model_artifacts=model_artifacts,
        remediation_history=remediation_history,
        generated_at=_now_iso(),
    )
    if write_files:
        _write_introspection_bundle(paths, payload)
    return payload


def read_cycle_introspection_file(cycle_id: UUID) -> tuple[str | None, dict[str, Any] | None]:
    paths = cycle_introspection_paths(Path(get_settings().data_root), cycle_id)
    markdown_path = Path(paths["markdown"])
    json_path = Path(paths["json"])
    markdown = markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else None
    json_payload = (
        json.loads(json_path.read_text(encoding="utf-8")) if json_path.exists() else None
    )
    return markdown, json_payload


def build_goal_result_summary(session, goal: ResearchGoal) -> GoalResultSummary:
    attempts = list(
        session.execute(
            select(GoalAttempt)
            .where(GoalAttempt.goal_id == goal.id)
            .order_by(GoalAttempt.attempt_number)
        ).scalars().all()
    )
    cycle_ids = [a.cycle_id for a in attempts]
    attempt_numbers = {a.cycle_id: a.attempt_number for a in attempts}
    runs = _runs_for_cycles(session, cycle_ids)
    runs_by_cycle: dict[UUID, list[GoalRunResult]] = {}
    for run_result in _build_run_results(session, runs, attempt_numbers=attempt_numbers):
        runs_by_cycle.setdefault(run_result.cycle_id, []).append(run_result)

    attempt_results = [
        GoalAttemptResult(
            attempt_id=_std_uuid(attempt.id),
            attempt_number=attempt.attempt_number,
            cycle_id=_std_uuid(attempt.cycle_id),
            status=attempt.status,
            evaluation=attempt.evaluation,
            introspection_markdown_path=cycle_introspection_paths(
                Path(get_settings().data_root), attempt.cycle_id
            )["markdown"],
            introspection_json_path=cycle_introspection_paths(
                Path(get_settings().data_root), attempt.cycle_id
            )["json"],
            cycle_report_path=attempt.report_path,
            runs=runs_by_cycle.get(_std_uuid(attempt.cycle_id), []),
        )
        for attempt in attempts
    ]
    all_runs = [run for attempt in attempt_results for run in attempt.runs]
    remediation_history = _remediation_history(session, cycle_ids)
    readiness = _publication_readiness(all_runs)
    caveats = _goal_caveats(goal, all_runs, readiness)
    return GoalResultSummary(
        goal_id=_std_uuid(goal.id),
        charter_id=_std_uuid(goal.charter_id),
        title=goal.title,
        status=goal.status,
        publication_readiness=readiness,
        summary=_goal_summary(goal, attempt_results, readiness),
        interpretation=_interpret_goal(goal, all_runs, readiness, caveats),
        caveats=caveats,
        next_steps=_next_steps(readiness, all_runs),
        status_ledger=_goal_status_ledger_summary(goal.id),
        attempts=attempt_results,
        metrics=_collect_metrics(all_runs),
        model_artifacts=[a for r in all_runs for a in r.artifacts if _is_model_artifact(a)],
        remediation_history=remediation_history,
        generated_at=_now_iso(),
    )


def render_cycle_introspection_markdown(payload: CycleResultIntrospection) -> str:
    data = payload.model_dump(mode="json")
    lines = [
        "# Result Introspection",
        "",
        f"- **Cycle ID:** `{data['cycle_id']}`",
        f"- **Goal ID:** `{data['goal_id']}`" if data.get("goal_id") else "- **Goal ID:** none",
        f"- **Publication readiness:** {data['publication_readiness']}",
        "",
        "## What Was Attempted",
        "",
        data["summary"],
        "",
        "## What Was Created",
        "",
        f"- **Runs:** {len(data['runs'])}",
        f"- **Artifacts:** {sum(len(r['artifacts']) for r in data['runs'])}",
        f"- **Model artifacts:** {len(data['model_artifacts'])}",
    ]
    if data.get("completion_report_path"):
        lines.append(f"- **Completion report:** `{data['completion_report_path']}`")
    lines.extend(["", *_metrics_section(data), "", *_artifacts_section(data), ""])
    lines.extend(_verification_section(data))
    lines.extend(["", *_remediation_section(data)])
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            data["interpretation"],
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend([f"- {c}" for c in data["caveats"]] or ["- No caveats were detected."])
    lines.extend(["", "## Next Steps", ""])
    lines.extend([f"- {s}" for s in data["next_steps"]] or ["- No follow-up steps recorded."])
    return "\n".join(lines).rstrip() + "\n"


def render_goal_result_markdown(payload: GoalResultSummary) -> str:
    data = payload.model_dump(mode="json")
    lines = [
        f"# Goal Report: {data['title']}",
        "",
        f"- **Status:** {data['status']}",
        f"- **Publication readiness:** {data['publication_readiness']}",
        f"- **Goal ID:** `{data['goal_id']}`",
        f"- **Charter ID:** `{data['charter_id']}`",
        "",
        "## Goal Summary",
        "",
        data["summary"],
        "",
        "## Attempts",
        "",
        "| # | Status | Cycle | Runs | Criteria | Introspection |",
        "|---|---|---|---:|---|---|",
    ]
    for attempt in data["attempts"]:
        criteria = ((attempt.get("evaluation") or {}).get("criteria") or [])
        passed = sum(1 for c in criteria if c.get("passed"))
        intro = attempt.get("introspection_markdown_path") or ""
        lines.append(
            f"| {attempt.get('attempt_number') or 'n/a'} | {attempt.get('status') or 'n/a'} | "
            f"`{attempt['cycle_id']}` | {len(attempt['runs'])} | "
            f"{passed}/{len(criteria)} | `{intro}` |"
        )
    lines.extend(["", *_metrics_section(data), "", *_artifacts_section(data), ""])
    lines.extend(_verification_section(data))
    lines.extend(["", *_remediation_section(data)])
    ledger = data.get("status_ledger") or {}
    lines.extend(
        [
            "",
            "## Status Ledger",
            "",
            f"- **Markdown:** `{ledger.get('markdown_path', '')}`",
            f"- **JSON:** `{ledger.get('json_path', '')}`",
            "",
            "## Interpretation",
            "",
            data["interpretation"],
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend([f"- {c}" for c in data["caveats"]] or ["- No caveats were detected."])
    lines.extend(["", "## Recommended Next Experiments", ""])
    lines.extend([f"- {s}" for s in data["next_steps"]] or ["- No follow-up steps recorded."])
    return "\n".join(lines).rstrip() + "\n"


def _write_introspection_bundle(
    paths: dict[str, str],
    payload: CycleResultIntrospection,
) -> None:
    root = Path(paths["root"])
    root.mkdir(parents=True, exist_ok=True)
    Path(paths["markdown"]).write_text(
        render_cycle_introspection_markdown(payload), encoding="utf-8"
    )
    Path(paths["json"]).write_text(
        json.dumps(payload.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _build_run_results(
    session,
    runs: list[RunRecord],
    *,
    attempt_numbers: dict[UUID, int | None],
) -> list[GoalRunResult]:
    spec_ids = [r.experiment_spec_id for r in runs]
    specs = {
        spec.id: spec
        for spec in session.execute(
            select(ExperimentSpec).where(ExperimentSpec.id.in_(spec_ids))
        ).scalars().all()
    } if spec_ids else {}
    verifications = _latest_by_run(
        session.execute(
            select(VerificationReport).where(
                VerificationReport.run_record_id.in_([r.id for r in runs])
            )
        ).scalars().all()
    ) if runs else {}
    postmortems = _latest_by_run(
        session.execute(
            select(FailurePostmortem).where(
                FailurePostmortem.run_record_id.in_([r.id for r in runs])
            )
        ).scalars().all()
    ) if runs else {}
    results: list[GoalRunResult] = []
    for run in sorted(runs, key=lambda r: (str(r.cycle_id), r.run_number, str(r.id))):
        spec = specs.get(run.experiment_spec_id)
        verification = verifications.get(run.id)
        postmortem = postmortems.get(run.id)
        warnings = list(verification.warnings or []) if verification else []
        error = run.error or (postmortem.root_cause if postmortem else None)
        results.append(
            GoalRunResult(
                run_id=_std_uuid(run.id),
                experiment_spec_id=_std_uuid(run.experiment_spec_id),
                attempt_number=attempt_numbers.get(run.cycle_id),
                cycle_id=_std_uuid(run.cycle_id),
                run_number=run.run_number,
                status=run.status,
                title=spec.title if spec else None,
                image_ref=run.image_ref,
                command=run.command,
                gpu_enabled=_gpu_enabled(run.resource_limits),
                exit_code=run.exit_code,
                metrics=dict(run.metrics_output or {}),
                artifacts=normalize_run_artifacts(run),
                verification_verdict=verification.verdict if verification else None,
                verification_summary=verification.summary if verification else None,
                verification_warnings=warnings,
                failure_class=run.failure_class,
                error=error,
            )
        )
    return results


def _runs_for_cycles(session, cycle_ids: list[UUID]) -> list[RunRecord]:
    if not cycle_ids:
        return []
    return list(
        session.execute(
            select(RunRecord)
            .where(RunRecord.cycle_id.in_(cycle_ids))
            .order_by(RunRecord.created_at.asc())
        ).scalars().all()
    )


def _remediation_history(session, cycle_ids: list[UUID]) -> list[dict[str, Any]]:
    if not cycle_ids:
        return []
    rows = session.execute(
        select(RemediationAction)
        .where(RemediationAction.cycle_id.in_(cycle_ids))
        .order_by(RemediationAction.created_at.asc())
    ).scalars().all()
    return [
        {
            "id": str(row.id),
            "cycle_id": str(row.cycle_id),
            "run_record_id": str(row.run_record_id),
            "retry_run_id": str(row.retry_run_id) if row.retry_run_id else None,
            "failure_class": row.failure_class,
            "strategy": row.strategy,
            "strategy_tier": row.strategy_tier,
            "outcome": row.outcome,
            "attempt_number": row.attempt_number,
            "reasoning": row.reasoning,
        }
        for row in rows
    ]


def _attempt_for_cycle(session, cycle_id: UUID) -> GoalAttempt | None:
    return session.execute(
        select(GoalAttempt).where(GoalAttempt.cycle_id == cycle_id).limit(1)
    ).scalar_one_or_none()


def _goal_id_from_cycle(cycle: ResearchCycle) -> UUID | None:
    raw = ((cycle.config or {}).get("goal") or {}).get("goal_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None


def _latest_by_run(rows) -> dict[UUID, Any]:
    out: dict[UUID, Any] = {}
    for row in rows:
        current = out.get(row.run_record_id)
        if current is None or getattr(row, "created_at", datetime.min) > getattr(
            current, "created_at", datetime.min
        ):
            out[row.run_record_id] = row
    return out


def _collect_metrics(runs: list[GoalRunResult]) -> dict[str, list[Any]]:
    metrics: dict[str, list[Any]] = {}
    for run in runs:
        for name, value in run.metrics.items():
            metrics.setdefault(name, []).append(value)
    return metrics


def _publication_readiness(runs: list[GoalRunResult]) -> PublicationReadiness:
    if not runs:
        return "incomplete"
    if any(r.verification_verdict == "passed" for r in runs):
        return "ready"
    if any(r.status == "completed" and (r.metrics or r.artifacts) for r in runs):
        return "needs_review"
    if all(r.status in {"failed", "cancelled"} for r in runs):
        return "failed"
    return "incomplete"


def _cycle_caveats(
    runs: list[GoalRunResult],
    readiness: PublicationReadiness,
) -> list[str]:
    caveats: list[str] = []
    if readiness == "needs_review":
        caveats.append(
            "Artifacts or metrics were produced, but no run has a passed verification verdict."
        )
    if any(r.failure_class for r in runs):
        caveats.append("At least one run ended with a failure class and should be reviewed.")
    warnings = [w for r in runs for w in r.verification_warnings]
    if warnings:
        caveats.append(f"Verification warnings were recorded: {'; '.join(warnings[:3])}")
    if not any(r.artifacts for r in runs):
        caveats.append("No captured artifacts are available for this cycle.")
    return caveats


def _goal_caveats(
    goal: ResearchGoal,
    runs: list[GoalRunResult],
    readiness: PublicationReadiness,
) -> list[str]:
    caveats = _cycle_caveats(runs, readiness)
    if goal.status == "satisfied" and readiness != "ready":
        caveats.insert(
            0,
            "The goal is satisfied by configured criteria, but the result is "
            "not publication-ready.",
        )
    return caveats


def _cycle_summary(runs: list[GoalRunResult], readiness: PublicationReadiness) -> str:
    completed = sum(1 for r in runs if r.status == "completed")
    verified = sum(1 for r in runs if r.verification_verdict == "passed")
    artifacts = sum(len(r.artifacts) for r in runs)
    return (
        f"The loop produced {len(runs)} run record(s), including {completed} completed "
        f"run(s), {verified} verified run(s), and {artifacts} captured artifact(s). "
        f"Publication readiness is `{readiness}`."
    )


def _goal_summary(
    goal: ResearchGoal,
    attempts: list[GoalAttemptResult],
    readiness: PublicationReadiness,
) -> str:
    total_runs = sum(len(a.runs) for a in attempts)
    completed = sum(1 for a in attempts for r in a.runs if r.status == "completed")
    return (
        f"Goal `{goal.title}` is `{goal.status}` after {len(attempts)} attempt(s). "
        f"Across those attempts, the system produced {total_runs} run record(s), "
        f"including {completed} completed run(s). Publication readiness is `{readiness}`."
    )


def _interpret_cycle(
    runs: list[GoalRunResult],
    readiness: PublicationReadiness,
    caveats: list[str],
) -> str:
    if readiness == "ready":
        return (
            "At least one run passed verification, so the outputs can be treated as the "
            "current best supported result for this loop. Review the listed artifacts "
            "and metrics before using them outside the system."
        )
    if readiness == "needs_review":
        return (
            "The loop created tangible outputs, but verification did not pass. Treat the "
            "metrics and model artifacts as experimental evidence, not as publication-ready "
            "results, until the failed checks are addressed."
        )
    if readiness == "failed":
        return (
            "The loop did not produce a verified or completed result. The failure classes, "
            "postmortems, and remediation history are the main useful outputs."
        )
    if caveats:
        return "The loop is incomplete and should be resumed or inspected before drawing claims."
    return "The loop has not yet produced enough run evidence for interpretation."


def _interpret_goal(
    goal: ResearchGoal,
    runs: list[GoalRunResult],
    readiness: PublicationReadiness,
    caveats: list[str],
) -> str:
    base = _interpret_cycle(runs, readiness, caveats)
    return (
        f"For goal `{goal.title}`, this means the configured goal state and the "
        f"publication readiness should be read separately. {base}"
    )


def _next_steps(readiness: PublicationReadiness, runs: list[GoalRunResult]) -> list[str]:
    if readiness == "ready":
        return [
            "Inspect the verified run artifacts and preserve the exact run id in "
            "any user-facing writeup.",
            "Run a confirmation attempt with the same protocol if the result will be published.",
        ]
    if readiness == "needs_review":
        return [
            "Review verification failures or warnings for the completed runs.",
            "Tighten goal success criteria to require verification_passed when "
            "publishable output is required.",
        ]
    if readiness == "failed":
        return [
            "Use the failure classes and postmortems to start a repaired attempt.",
            "Avoid reusing the same protocol payload unless the ledger records a specific change.",
        ]
    return ["Resume the loop or start another attempt so it can produce run evidence."]


def _metrics_section(data: dict[str, Any]) -> list[str]:
    lines = ["## Metrics", ""]
    metrics = data.get("metrics") or {}
    if not metrics:
        return [*lines, "No metrics were captured."]
    lines.extend(["| Metric | Values |", "|---|---|"])
    for name, values in metrics.items():
        formatted = ", ".join(_format_value(v) for v in values)
        lines.append(f"| {name} | {formatted} |")
    return lines


def _artifacts_section(data: dict[str, Any]) -> list[str]:
    lines = ["## Artifacts", ""]
    runs = _runs_from_payload(data)
    artifacts = [
        artifact | {"run_id": run["run_id"]}
        for run in runs
        for artifact in run["artifacts"]
    ]
    if not artifacts:
        return [*lines, "No captured artifacts were recorded."]
    lines.extend(["| Run | Name | Type | Size | Download |", "|---|---|---|---:|---|"])
    for artifact in artifacts:
        lines.append(
            f"| `{str(artifact['run_id'])[:12]}` | {artifact['name']} | "
            f"{artifact['artifact_type']} | {artifact.get('size_bytes') or ''} | "
            f"`{artifact['download_url']}` |"
        )
    return lines


def _verification_section(data: dict[str, Any]) -> list[str]:
    lines = ["## Verification", "", "| Run | Status | Verdict | Summary |", "|---|---|---|---|"]
    rows = _runs_from_payload(data)
    if not rows:
        return ["## Verification", "", "No runs were available for verification."]
    for run in rows:
        lines.append(
            f"| `{str(run['run_id'])[:12]}` | {run['status']} | "
            f"{run.get('verification_verdict') or 'n/a'} | "
            f"{_escape_table(run.get('verification_summary') or run.get('failure_class') or '')} |"
        )
    return lines


def _remediation_section(data: dict[str, Any]) -> list[str]:
    lines = ["## Remediation History", ""]
    rows = data.get("remediation_history") or []
    if not rows:
        return [*lines, "No remediation actions were recorded."]
    lines.extend(["| Run | Strategy | Outcome | Reasoning |", "|---|---|---|---|"])
    for row in rows:
        lines.append(
            f"| `{str(row.get('run_record_id') or '')[:12]}` | "
            f"{row.get('strategy') or 'n/a'} | {row.get('outcome') or 'n/a'} | "
            f"{_escape_table(row.get('reasoning') or '')} |"
        )
    return lines


def _runs_from_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    if data.get("runs"):
        return list(data["runs"])
    return [
        run
        for attempt in data.get("attempts", [])
        for run in attempt.get("runs", [])
    ]


def _artifact_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix in {".pt", ".pth", ".bin", ".safetensors", ".ckpt", ".gguf"}:
        return "model"
    if suffix in {".md", ".txt", ".log"}:
        return "text"
    return suffix.lstrip(".") or "file"


def _is_model_artifact(artifact: RunArtifactRead) -> bool:
    return artifact.artifact_type == "model" or "weight" in artifact.name.lower()


def _gpu_enabled(resource_limits: dict[str, Any] | None) -> bool | None:
    if resource_limits is None:
        return None
    value = resource_limits.get("gpu") or resource_limits.get("gpus")
    if value is None:
        return None
    return bool(value)


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _std_uuid(value: Any) -> UUID:
    return UUID(str(value))


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")[:160]


def _goal_status_ledger_summary(goal_id: UUID) -> dict[str, Any] | None:
    root = Path(get_settings().data_root) / "reports" / "goals" / str(goal_id)
    json_path = root / "status.json"
    markdown_path = root / "status.md"
    latest = None
    if json_path.exists():
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            entries = payload.get("entries") or []
            latest = entries[-1] if entries else None
        except json.JSONDecodeError:
            latest = None
    return {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "latest": latest,
    }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
