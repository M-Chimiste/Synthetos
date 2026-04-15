"""Pilot evaluation: grade a completed pilot cycle against fixture expectations.

Produces ``evaluation.json`` / ``evaluation.md`` under
``<data_root>/artifacts/pilot/<problem_id>/<timestamp>/`` comparing observed
cycle state to the fixture's ``expected.yaml``.

This is read-only: it inspects existing DB state + filesystem artifacts and
summarizes. It does not mutate any cycle data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from libs.core.clock import utcnow
from libs.core.config import get_settings
from libs.pilot.fixture import PilotFixture
from libs.storage.base import get_sync_session_factory
from libs.storage.models.experiment import FailurePostmortem, RunRecord
from libs.storage.models.patterns import CanonicalPattern, PatternObservation
from libs.storage.models.remediation import MetricFrontier, RemediationAction
from libs.storage.models.research import ResearchCycle


@dataclass
class EvaluationResult:
    problem_id: str
    cycle_id: UUID
    cycle_status: str
    passed: bool
    checks: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "cycle_id": str(self.cycle_id),
            "cycle_status": self.cycle_status,
            "passed": self.passed,
            "checks": self.checks,
            "warnings": self.warnings,
        }


@dataclass
class EvaluationComparison:
    left_label: str
    right_label: str
    left_passed: bool
    right_passed: bool
    left_checks: dict[str, Any] = field(default_factory=dict)
    right_checks: dict[str, Any] = field(default_factory=dict)
    deltas: dict[str, Any] = field(default_factory=dict)
    summary: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "left_label": self.left_label,
            "right_label": self.right_label,
            "left_passed": self.left_passed,
            "right_passed": self.right_passed,
            "left_checks": self.left_checks,
            "right_checks": self.right_checks,
            "deltas": self.deltas,
            "summary": self.summary,
        }


def _count(db, model, cycle_id: UUID, extra=None) -> int:
    stmt = select(func.count()).select_from(model).where(model.cycle_id == cycle_id)
    if extra is not None:
        stmt = stmt.where(extra)
    return int(db.execute(stmt).scalar_one())


def evaluate_cycle(fixture: PilotFixture, cycle_id: UUID) -> EvaluationResult:
    """Grade a completed pilot cycle against the fixture's expectations."""
    factory = get_sync_session_factory()
    with factory() as db:
        cycle = db.get(ResearchCycle, cycle_id)
        if cycle is None:
            return EvaluationResult(
                problem_id=fixture.problem_id,
                cycle_id=cycle_id,
                cycle_status="unknown",
                passed=False,
                checks={"cycle_found": False},
                warnings=[f"cycle {cycle_id} not found"],
            )

        expected = fixture.expected or {}

        total_runs = _count(db, RunRecord, cycle_id)
        successful_runs = _count(
            db, RunRecord, cycle_id, extra=RunRecord.status == "completed"
        )
        postmortems = _count(db, FailurePostmortem, cycle_id)
        remediations = _count(db, RemediationAction, cycle_id)

        frontiers = db.execute(
            select(MetricFrontier).where(
                MetricFrontier.charter_id == cycle.charter_id
            )
        ).scalars().all()

        # Phase 6: look for patterns whose observations touch this cycle.
        pattern_obs = db.execute(
            select(PatternObservation.pattern_id)
            .where(PatternObservation.cycle_id == cycle_id)
            .distinct()
        ).scalars().all()
        pattern_ids = list(pattern_obs)
        patterns = []
        if pattern_ids:
            patterns = db.execute(
                select(CanonicalPattern).where(CanonicalPattern.id.in_(pattern_ids))
            ).scalars().all()

        pattern_type_counts: dict[str, int] = {}
        for p in patterns:
            pattern_type_counts[p.pattern_type] = (
                pattern_type_counts.get(p.pattern_type, 0) + 1
            )

        # Graded checks
        checks: dict[str, Any] = {
            "cycle_found": True,
            "total_runs": total_runs,
            "successful_runs": successful_runs,
            "postmortems": postmortems,
            "remediations": remediations,
            "frontiers": len(frontiers),
            "patterns_touched": len(patterns),
            "pattern_type_counts": pattern_type_counts,
        }

        # Apply the fixture's success_criteria heuristically.
        warnings: list[str] = []

        frontier_prog = expected.get("frontier_progression", {}) or {}
        min_successful = int(frontier_prog.get("min_successful_runs", 0))
        if successful_runs < min_successful:
            warnings.append(
                f"expected >= {min_successful} successful runs, got {successful_runs}"
            )

        pattern_reuse = expected.get("pattern_reuse", {}) or {}
        if pattern_reuse.get("expect_successful_line") and pattern_type_counts.get(
            "successful_line", 0
        ) == 0:
            warnings.append(
                "expected a 'successful_line' pattern to be consolidated"
            )
        if pattern_reuse.get("expect_failure_patterns") and pattern_type_counts.get(
            "failure", 0
        ) == 0:
            warnings.append(
                "expected at least one 'failure' pattern to be consolidated"
            )

        passed = (
            cycle.status.value in {"closed", "reporting"}
            and not warnings
        )

        return EvaluationResult(
            problem_id=fixture.problem_id,
            cycle_id=cycle_id,
            cycle_status=str(
                cycle.status.value if hasattr(cycle.status, "value") else cycle.status
            ),
            passed=passed,
            checks=checks,
            warnings=warnings,
        )


def _markdown(result: EvaluationResult) -> str:
    lines = [
        f"# Pilot evaluation — {result.problem_id}",
        "",
        f"- cycle: `{result.cycle_id}`",
        f"- cycle status: `{result.cycle_status}`",
        f"- passed: **{result.passed}**",
        "",
        "## Checks",
    ]
    for k, v in result.checks.items():
        lines.append(f"- {k}: {v}")
    if result.warnings:
        lines += ["", "## Warnings"]
        lines += [f"- {w}" for w in result.warnings]
    return "\n".join(lines) + "\n"


def _comparison_markdown(result: EvaluationComparison) -> str:
    lines = [
        "# Pilot comparison",
        "",
        f"- left: `{result.left_label}`",
        f"- right: `{result.right_label}`",
        f"- left passed: **{result.left_passed}**",
        f"- right passed: **{result.right_passed}**",
        "",
        "## Deltas",
    ]
    for key, value in result.deltas.items():
        lines.append(f"- {key}: {value}")
    if result.summary:
        lines += ["", "## Summary"]
        lines += [f"- {line}" for line in result.summary]
    return "\n".join(lines) + "\n"


def load_evaluation(path: Path) -> EvaluationResult:
    """Load a persisted pilot evaluation bundle."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return EvaluationResult(
        problem_id=str(payload["problem_id"]),
        cycle_id=UUID(str(payload["cycle_id"])),
        cycle_status=str(payload["cycle_status"]),
        passed=bool(payload["passed"]),
        checks=dict(payload.get("checks") or {}),
        warnings=list(payload.get("warnings") or []),
    )


def compare_evaluations(
    left: EvaluationResult,
    right: EvaluationResult,
) -> EvaluationComparison:
    """Diff two pilot evaluations in a deterministic, artifact-friendly shape."""
    deltas: dict[str, Any] = {}
    summary: list[str] = []

    numeric_keys = sorted(set(left.checks) | set(right.checks))
    for key in numeric_keys:
        left_value = left.checks.get(key)
        right_value = right.checks.get(key)
        if isinstance(left_value, (int, float)) and isinstance(right_value, (int, float)):
            deltas[key] = round(float(right_value) - float(left_value), 4)
        elif left_value != right_value:
            deltas[key] = {"left": left_value, "right": right_value}

    if right.passed and not left.passed:
        summary.append("right run passed where left did not")
    elif left.passed and not right.passed:
        summary.append("left run passed where right did not")

    if "successful_runs" in deltas and isinstance(deltas["successful_runs"], (int, float)):
        if deltas["successful_runs"] > 0:
            summary.append("right run produced more successful runs")
        elif deltas["successful_runs"] < 0:
            summary.append("left run produced more successful runs")

    return EvaluationComparison(
        left_label=f"{left.problem_id}:{left.cycle_id}",
        right_label=f"{right.problem_id}:{right.cycle_id}",
        left_passed=left.passed,
        right_passed=right.passed,
        left_checks=left.checks,
        right_checks=right.checks,
        deltas=deltas,
        summary=summary,
    )


def write_evaluation(
    fixture: PilotFixture,
    result: EvaluationResult,
    timestamp: datetime | None = None,
) -> tuple[Path, Path]:
    """Persist the evaluation under ``<data_root>/artifacts/pilot/...`` and
    return the (json, markdown) paths.
    """
    settings = get_settings()
    stamp = (timestamp or utcnow()).strftime("%Y%m%dT%H%M%SZ")
    out_dir = (
        Path(settings.data_root)
        / "artifacts"
        / "pilot"
        / fixture.problem_id
        / stamp
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "evaluation.json"
    md_path = out_dir / "evaluation.md"
    json_path.write_text(json.dumps(result.to_json(), indent=2, default=str))
    md_path.write_text(_markdown(result))
    return json_path, md_path


def write_comparison(
    result: EvaluationComparison,
    timestamp: datetime | None = None,
) -> tuple[Path, Path]:
    """Persist a comparison artifact under ``<data_root>/artifacts/pilot/compare``."""
    settings = get_settings()
    stamp = (timestamp or utcnow()).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(settings.data_root) / "artifacts" / "pilot" / "compare" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "comparison.json"
    md_path = out_dir / "comparison.md"
    json_path.write_text(json.dumps(result.to_json(), indent=2, default=str))
    md_path.write_text(_comparison_markdown(result))
    return json_path, md_path
