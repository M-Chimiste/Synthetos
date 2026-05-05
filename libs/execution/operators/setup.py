"""execution_setup operator -- creates a git worktree, writes generated code,
resolves/builds the Docker image, and enqueues execution_run.
"""

from __future__ import annotations

from uuid_utils import uuid7

from libs.adapters.container.docker_runner import BuildImageError, DockerRunner
from libs.adapters.git.worktree import commit_worktree, create_worktree
from libs.core.clock import utcnow
from libs.core.config import get_settings
from libs.core.event_types import ExecutionEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.execution.operators._common import (
    ExecutionStateError,
    enqueue_next,
    load_run_record,
    run_record_id_from_payload,
)
from libs.storage.base import get_sync_session_factory
from libs.storage.models.experiment import ExperimentSpec

log = get_logger("execution.setup")


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
        image_ref = override_base or spec.base_image or "python:3.12-slim"

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
            hw = spec.hardware_profile or {}
            mem_gb = hw.get("memory_gb")
            mem_str = f"{mem_gb}g" if isinstance(mem_gb, int) else "16g"
            run.resource_limits = {
                "memory": mem_str,
                "timeout": hw.get("timeout_seconds", 3600),
                "gpu": hw.get("gpu_required", False),
                "gpu_count": hw.get("gpu_count", 1),
            }

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
    )
