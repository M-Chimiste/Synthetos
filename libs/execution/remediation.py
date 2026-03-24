"""Fix primitives for auto-remediation: apply code patches, dependency adds, env changes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.core.config import AppConfig
from libs.execution.debug import RemediationResponse
from libs.execution.policy import evaluate_run_policy
from libs.execution.runner import load_execution_image, load_execution_profile
from libs.storage.models import RemediationActionModel, RunRecordModel

log = structlog.get_logger()

# Fields on ExperimentSpecModel that auto-remediation is allowed to mutate.
_MUTABLE_SPEC_FIELDS = frozenset({
    "resource_requirements",
    "stop_conditions",
    "estimated_runtime_minutes",
    "gpu_required",
})

_MUTABLE_RUN_FIELDS = frozenset({
    "execution_profile",
    "timeout_seconds",
    "memory_limit_mb",
    "cpu_limit",
    "gpu_enabled",
})

# Candidate filenames for the main run script in the workspace.
_CODE_CANDIDATES = ("train.py", "run.py", "main.py")


def apply_code_patch(
    workspace_path: Path,
    run_public_id: str,
    code_patch: str,
) -> Path:
    """Write patched code to the run's workspace. Returns path to patched file."""
    code_dir = workspace_path / "generated_runs" / run_public_id
    code_dir.mkdir(parents=True, exist_ok=True)

    # Find the existing script or default to train.py
    target = code_dir / "train.py"
    for candidate in _CODE_CANDIDATES:
        candidate_path = code_dir / candidate
        if candidate_path.exists():
            target = candidate_path
            break

    target.write_text(code_patch, encoding="utf-8")
    log.info(
        "remediation_code_patch_applied",
        run_public_id=run_public_id,
        target=str(target),
        patch_size=len(code_patch),
    )
    return target


def apply_dependency_adds(
    run: RunRecordModel,
    dependency_adds: list[str],
) -> None:
    """Append dependencies to the run's build_recipe."""
    if not dependency_adds:
        return
    recipe = dict(run.build_recipe or {})
    existing = list(recipe.get("pip_packages", []))
    recipe["pip_packages"] = list(set(existing + dependency_adds))
    run.build_recipe = recipe
    log.info(
        "remediation_dependency_adds",
        run_public_id=run.public_id,
        added=dependency_adds,
    )


def apply_env_changes(
    run: RunRecordModel,
    env_changes: dict[str, str],
) -> None:
    """Merge env changes into the run's env_vars."""
    if not env_changes:
        return
    merged = dict(run.env_vars or {})
    merged.update(env_changes)
    run.env_vars = merged
    log.info(
        "remediation_env_changes",
        run_public_id=run.public_id,
        keys=list(env_changes.keys()),
    )


def apply_spec_mutations(
    spec: Any,
    spec_mutations: dict[str, Any],
) -> dict[str, Any]:
    """Apply whitelisted mutations to experiment spec fields."""
    applied: dict[str, Any] = {}
    if not spec_mutations:
        return applied
    for field, value in spec_mutations.items():
        if field not in _MUTABLE_SPEC_FIELDS:
            log.warning(
                "remediation_spec_mutation_blocked",
                field=field,
                reason="not in mutable whitelist",
            )
            continue
        setattr(spec, field, value)
        applied[field] = value
        log.info("remediation_spec_mutation", field=field)
    return applied


def apply_run_mutations(
    config: AppConfig,
    run: RunRecordModel,
    run_mutations: dict[str, Any],
) -> dict[str, Any]:
    """Apply validated run-level mutations to the retried run record."""
    applied: dict[str, Any] = {}
    if not run_mutations:
        return applied

    execution_profile = run_mutations.get("execution_profile")
    if execution_profile is not None:
        try:
            profile = load_execution_profile(config, str(execution_profile))
        except ValueError:
            log.warning(
                "remediation_run_mutation_blocked",
                field="execution_profile",
                reason="unknown execution profile",
                value=execution_profile,
            )
        else:
            network_mode = str(profile.get("network_mode", "disabled"))
            image_key = str(profile["image_key"])
            decision = evaluate_run_policy(
                config,
                execution_profile=str(execution_profile),
                network_mode=network_mode,
                image_key=image_key,
                force_start=False,
            )
            if not decision.allowed:
                log.warning(
                    "remediation_run_mutation_blocked",
                    field="execution_profile",
                    reason=decision.reason,
                    value=execution_profile,
                )
            else:
                image = load_execution_image(config, image_key)
                run.execution_profile = str(execution_profile)
                run.image = image["image"]
                run.hardware_profile = profile["hardware_profile"]
                run.timeout_seconds = int(profile["timeout_seconds"])
                run.memory_limit_mb = int(profile["memory_limit_mb"])
                run.cpu_limit = (
                    str(profile.get("cpu_limit"))
                    if profile.get("cpu_limit") is not None
                    else None
                )
                run.gpu_enabled = bool(profile.get("gpu_enabled", False))
                run.network_mode = network_mode
                applied["execution_profile"] = run.execution_profile
                applied["hardware_profile"] = run.hardware_profile
                applied["timeout_seconds"] = run.timeout_seconds
                applied["memory_limit_mb"] = run.memory_limit_mb
                applied["cpu_limit"] = run.cpu_limit
                applied["gpu_enabled"] = run.gpu_enabled

    for field, value in run_mutations.items():
        if field == "execution_profile":
            continue
        if field not in _MUTABLE_RUN_FIELDS:
            log.warning(
                "remediation_run_mutation_blocked",
                field=field,
                reason="not in mutable whitelist",
            )
            continue
        if field in {"timeout_seconds", "memory_limit_mb"}:
            coerced = int(value)
        elif field == "gpu_enabled":
            coerced = bool(value)
        elif field == "cpu_limit":
            coerced = None if value in (None, "") else str(value)
        else:
            coerced = value
        setattr(run, field, coerced)
        applied[field] = coerced
        log.info("remediation_run_mutation", field=field, value=coerced)
    return applied


def prepare_run_for_retry(
    run: RunRecordModel,
    response: RemediationResponse,
    prompt_id: str,
    *,
    increment_attempt_count: bool = True,
) -> None:
    """Reset run status and increment counters for re-execution."""
    run.status = "ready_to_execute"
    run.last_error = None
    run.exit_code = None
    run.failure_classification = None
    run.verification_outcome = None
    run.remediation_count = (run.remediation_count or 0) + 1
    run.is_remediated_run = True
    if increment_attempt_count:
        run.attempt_count = (run.attempt_count or 0) + 1
    run.prompt_lineage = [
        *list(run.prompt_lineage or []),
        {"prompt_id": prompt_id, "mode": "auto_remediation"},
    ]
    run.model_lineage = [
        *list(run.model_lineage or []),
        {"mode": "auto_remediation", "fix_type": response.fix_type},
    ]


def build_prior_attempts_summary(
    session: Session,
    run_record_id: int,
) -> list[dict[str, Any]]:
    """Load prior RemediationActionModel rows for this run, for conversation context."""
    rows = session.scalars(
        select(RemediationActionModel)
        .where(RemediationActionModel.run_record_id == run_record_id)
        .order_by(RemediationActionModel.attempt_number.asc())
    ).all()
    return [
        {
            "attempt_number": row.attempt_number,
            "failure_classification": row.failure_classification,
            "diagnosis": row.diagnosis,
            "fix_type": row.fix_type,
            "fix_description": row.fix_description,
            "outcome": row.outcome,
        }
        for row in rows
    ]


def read_code_from_workspace(
    workspace_path: str,
    run_public_id: str,
    max_chars: int,
) -> str:
    """Read the main run script from the workspace, truncated to max_chars."""
    code_dir = Path(workspace_path) / "generated_runs" / run_public_id
    for candidate in _CODE_CANDIDATES:
        code_path = code_dir / candidate
        if code_path.exists():
            text = code_path.read_text(encoding="utf-8")
            return text[-max_chars:] if len(text) > max_chars else text
    return ""


def read_log_tail(path: str | None, max_chars: int) -> str:
    """Read the tail of a log file, returning at most max_chars."""
    if not path:
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8")
        return text[-max_chars:] if len(text) > max_chars else text
    except OSError:
        return ""
