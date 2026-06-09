"""execution_setup operator -- creates a git worktree, writes generated code,
resolves/builds the Docker image, and enqueues execution_run.
"""

from __future__ import annotations

from uuid_utils import uuid7

from libs.adapters.container.docker_runner import BuildImageError, DockerRunner
from libs.adapters.git.worktree import commit_worktree, create_worktree
from libs.core.clock import utcnow
from libs.core.config import get_settings
from libs.core.container_images import (
    default_base_image_for_hardware,
    gpu_requested,
    is_default_cpu_image,
)
from libs.core.event_types import ExecutionEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.core.types import CycleStatus
from libs.execution.operators._common import (
    ExecutionStateError,
    enqueue_next,
    load_run_record,
    run_record_id_from_payload,
)
from libs.execution.sdk_template import SDK_FILENAME, SDK_SOURCE
from libs.storage.base import get_sync_session_factory
from libs.storage.models.experiment import ExperimentSpec
from libs.storage.models.goals import ResearchGoal
from libs.storage.models.research import ResearchCycle

log = get_logger("execution.setup")


def _goal_protocol_policy(db, cycle_id) -> dict:
    cycle = db.get(ResearchCycle, cycle_id)
    if cycle is None:
        return {}
    goal_cfg = (cycle.config or {}).get("goal") or {}
    goal_id = goal_cfg.get("goal_id")
    if not goal_id:
        return {}
    goal = db.get(ResearchGoal, goal_id)
    if goal is None:
        return {}
    policy = goal.policy or {}
    protocol = policy.get("protocol") or {}
    return protocol if isinstance(protocol, dict) else {}


def _cycle_compute_cap(db, cycle_id) -> dict:
    cycle = db.get(ResearchCycle, cycle_id)
    if cycle is None:
        return {}
    autonomy = (cycle.config or {}).get("autonomy") or {}
    compute_cap = autonomy.get("compute_cap") or {}
    return compute_cap if isinstance(compute_cap, dict) else {}


def _gpu_requested(profile: dict) -> bool:
    return gpu_requested(profile)


def _resolve_base_image(
    *,
    remediation_base: str | None,
    policy_base: str | None,
    spec_base: str | None,
    hardware_profile: dict,
) -> str:
    image_ref = remediation_base or policy_base or spec_base
    if _gpu_requested(hardware_profile) and is_default_cpu_image(image_ref):
        return default_base_image_for_hardware(hardware_profile)
    return image_ref or default_base_image_for_hardware(hardware_profile)


def _dockerfile_with_base_image(content: str, base_image: str) -> str:
    lines = content.splitlines()
    for idx, line in enumerate(lines):
        if line.strip().upper().startswith("FROM "):
            lines[idx] = f"FROM {base_image}"
            return "\n".join(lines) + ("\n" if content.endswith("\n") else "")
    return f"FROM {base_image}\n{content}"


def execution_setup_operator(op_input: OperatorInput) -> OperatorResult:
    factory = get_sync_session_factory()
    try:
        run_id = run_record_id_from_payload(op_input)
    except ExecutionStateError as exc:
        return OperatorResult(success=False, error=str(exc))

    settings = get_settings()

    with factory() as db:
        run = load_run_record(db, run_id)
        spec = db.get(ExperimentSpec, run.experiment_spec_id)
        if spec is None:
            return OperatorResult(success=False, error="experiment spec not found")
        goal_protocol = _goal_protocol_policy(db, run.cycle_id)
        autonomy_hw = _cycle_compute_cap(db, run.cycle_id)
        policy_hw = dict(goal_protocol.get("hardware_profile") or {})
        spec_hw = dict(spec.hardware_profile or {})
        hardware_profile = {**autonomy_hw, **spec_hw, **policy_hw}

        run.status = "workspace_setup"
        run.started_at = utcnow()
        db.flush()

        # 1. Create git worktree
        workspace_base = settings.data_root / "workspaces"
        try:
            worktree_path = create_worktree(
                repo_root=settings.repo_root,
                workspace_base=workspace_base,
                run_id=run.id,
            )
        except Exception as exc:
            run.status = "failed"
            run.failure_class = "dependency"
            run.error = f"worktree creation failed: {exc}"
            run.completed_at = utcnow()
            db.commit()
            return OperatorResult(success=False, error=run.error)

        run.workspace_path = str(worktree_path)

        # 2. Write generated code files (with optional remediation patches)
        code_plan = dict(spec.code_plan or {})
        remediation_overrides = op_input.payload.get("remediation_overrides", {})

        # Apply code_plan patches from remediation
        if "code_plan" in remediation_overrides:
            patched_files = remediation_overrides["code_plan"].get("patched_files", {})
            existing_files = dict(code_plan.get("files", {}))
            existing_files.update(patched_files)
            code_plan["files"] = existing_files

        files = code_plan.get("files", {})
        for filename, content in files.items():
            file_path = worktree_path / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        # Inject the Synthetos signal SDK so user code can do
        # `from synthetos_signal import signal` to emit structured events
        # back to the worker via stdout-tagged lines.
        (worktree_path / SDK_FILENAME).write_text(SDK_SOURCE, encoding="utf-8")

        # 3. Commit generated code
        try:
            commit_sha = commit_worktree(
                worktree_path,
                f"experiment: {spec.title} run {run.run_number}",
            )
        except Exception as exc:
            run.status = "failed"
            run.failure_class = "dependency"
            run.error = f"worktree commit failed: {exc}"
            run.completed_at = utcnow()
            db.commit()
            return OperatorResult(success=False, error=run.error)

        if not commit_sha:
            run.status = "failed"
            run.failure_class = "dependency"
            run.error = "worktree commit failed: empty commit sha"
            run.completed_at = utcnow()
            db.commit()
            return OperatorResult(success=False, error=run.error)

        env_vars = dict(run.env_vars or {})
        env_vars["commit_sha"] = commit_sha
        run.env_vars = env_vars

        # 4. Resolve Docker image
        run.status = "building"
        db.flush()

        # Resolve base_image: a base_image override from remediation
        # (e.g., the LLM proposed a different FROM after a build failure)
        # wins over the spec's value.
        override_base = remediation_overrides.get("base_image")
        policy_base = goal_protocol.get("base_image")
        image_ref = _resolve_base_image(
            remediation_base=override_base,
            policy_base=policy_base,
            spec_base=spec.base_image,
            hardware_profile=hardware_profile,
        )

        # Resolve build_recipe. The override can either:
        #   - replace dockerfile_content wholesale (used by the "build"
        #     failure-class strategy after a Dockerfile is broken), or
        #   - append extra_pip_packages (existing "dependency" strategy).
        spec_recipe = dict(spec.build_recipe) if spec.build_recipe else None
        override_recipe = remediation_overrides.get("build_recipe", {}) or {}

        if "dockerfile_content" in override_recipe:
            build_recipe = {"dockerfile_content": override_recipe["dockerfile_content"]}
        else:
            build_recipe = spec_recipe

        if build_recipe and build_recipe.get("dockerfile_content") and image_ref:
            build_recipe = dict(build_recipe)
            build_recipe["dockerfile_content"] = _dockerfile_with_base_image(
                str(build_recipe["dockerfile_content"]),
                str(image_ref),
            )

        extra_pkgs = override_recipe.get("extra_pip_packages", [])
        if extra_pkgs and build_recipe and build_recipe.get("dockerfile_content"):
            pip_line = f"RUN pip install {' '.join(extra_pkgs)}"
            build_recipe["dockerfile_content"] += f"\n{pip_line}\n"
        elif extra_pkgs:
            # No build recipe yet — create a minimal one.
            build_recipe = {
                "dockerfile_content": (
                    f"FROM {image_ref}\n"
                    f"RUN pip install {' '.join(extra_pkgs)}\n"
                ),
            }

        if build_recipe and build_recipe.get("dockerfile_content"):
            runner = DockerRunner()
            tag = f"synthetos-exp-{uuid7()}"
            try:
                image_ref = runner.build_image(
                    dockerfile_content=build_recipe["dockerfile_content"],
                    tag=tag,
                    context_path=worktree_path,
                )
                emit_event_sync(
                    db,
                    event_type=ExecutionEvents.image_built.value,
                    charter_id=run.charter_id,
                    cycle_id=run.cycle_id,
                    payload={"run_record_id": str(run.id), "image": image_ref},
                )
            except BuildImageError as exc:
                # Build failure — funnel into the same verification →
                # auto-remediate loop that handles run-time failures, so
                # the LLM gets a shot at fixing the Dockerfile or proposing
                # a different base_image.
                log_tail = exc.log_text[-4096:] if exc.log_text else ""
                (worktree_path / "build.log").write_text(
                    exc.log_text or "", encoding="utf-8"
                )
                run.status = "failed"
                run.failure_class = "build"
                run.error = (
                    f"image build failed: {exc.cause}\n\n"
                    f"--- last 4KB of build log ---\n{log_tail}"
                )
                run.image_ref = None
                run.completed_at = utcnow()
                emit_event_sync(
                    db,
                    event_type=ExecutionEvents.run_failed.value,
                    charter_id=run.charter_id,
                    cycle_id=run.cycle_id,
                    payload={
                        "run_record_id": str(run.id),
                        "failure_class": "build",
                    },
                )
                enqueue_next(
                    db,
                    cycle_id=run.cycle_id,
                    next_job_type="verification_check",
                    run_record_id=run.id,
                )
                db.commit()
                return OperatorResult(
                    success=True,
                    summary="image build failed; routed to verification_check",
                )

        run.image_ref = image_ref
        entry_point = code_plan.get("entry_point", "run_experiment.py")
        run.command = f"python {entry_point}"

        # Set resource limits (skip if already set by remediation)
        if not run.resource_limits:
            mem_gb = hardware_profile.get("memory_gb")
            mem_str = f"{mem_gb}g" if isinstance(mem_gb, int) else "16g"
            run.resource_limits = {
                "memory": mem_str,
                "timeout": hardware_profile.get("timeout_seconds", 3600),
                "gpu": _gpu_requested(hardware_profile),
                "gpu_count": hardware_profile.get("gpu_count", 1),
            }
        elif _gpu_requested(hardware_profile):
            limits = dict(run.resource_limits)
            limits["gpu"] = True
            limits["gpu_count"] = hardware_profile.get(
                "gpu_count",
                limits.get("gpu_count", 1),
            )
            if hardware_profile.get("timeout_seconds") and "timeout" not in limits:
                limits["timeout"] = hardware_profile["timeout_seconds"]
            if hardware_profile.get("memory_gb") and "memory" not in limits:
                limits["memory"] = f"{hardware_profile['memory_gb']}g"
            run.resource_limits = limits

        emit_event_sync(
            db,
            event_type=ExecutionEvents.workspace_created.value,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            payload={
                "run_record_id": str(run.id),
                "workspace_path": str(worktree_path),
                "image": image_ref,
                "commit_sha": commit_sha,
            },
        )

        enqueue_next(
            db,
            cycle_id=run.cycle_id,
            next_job_type="execution_run",
            run_record_id=run.id,
        )
        db.commit()

    return OperatorResult(
        success=True,
        summary=f"Workspace ready at {worktree_path}; image {image_ref}; enqueued execution_run",
        state_patch={"cycle_status": CycleStatus.running.value},
    )
