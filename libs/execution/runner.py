from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from libs.core.config import AppConfig
from libs.schemas.domain import ExperimentSpec, RunSpec


@dataclass(frozen=True)
class RunPaths:
    artifact_root: Path
    patch_archive_path: Path
    stdout_path: Path
    stderr_path: Path
    workspace_project_path: Path
    workspace_config_path: Path


def determine_run_paths(config: AppConfig, run_public_id: str) -> RunPaths:
    artifact_root = config.run_artifacts_dir / run_public_id
    artifact_root.mkdir(parents=True, exist_ok=True)
    workspace_project_path = (
        config.workspaces_dir / run_public_id / "generated_runs" / run_public_id
    )
    workspace_config_path = workspace_project_path / "run_config.json"
    return RunPaths(
        artifact_root=artifact_root,
        patch_archive_path=config.patches_dir / f"{run_public_id}.diff",
        stdout_path=artifact_root / "stdout.log",
        stderr_path=artifact_root / "stderr.log",
        workspace_project_path=workspace_project_path,
        workspace_config_path=workspace_config_path,
    )


def load_execution_profile(config: AppConfig, execution_profile: str) -> dict[str, Any]:
    profiles = config.load_yaml(config.execution_profiles_path).get("profiles", {})
    if execution_profile not in profiles:
        raise ValueError(f"Unknown execution profile {execution_profile!r}")
    return profiles[execution_profile]


def load_execution_image(config: AppConfig, image_key: str) -> dict[str, Any]:
    images = config.load_yaml(config.execution_images_path).get("approved_images", {})
    if image_key not in images:
        raise ValueError(f"Unknown execution image {image_key!r}")
    return images[image_key]


def stage_execution_harness(
    *,
    config: AppConfig,
    workspace_path: Path,
    run_public_id: str,
    experiment_spec: ExperimentSpec,
) -> RunPaths:
    template_root = Path("libs/execution/templates/offline_baseline")
    paths = determine_run_paths(config, run_public_id)
    paths.workspace_project_path.mkdir(parents=True, exist_ok=True)
    if template_root.exists():
        for item in template_root.iterdir():
            destination = paths.workspace_project_path / item.name
            if destination.exists():
                continue
            if item.is_dir():
                shutil.copytree(item, destination)
            else:
                shutil.copy2(item, destination)

    run_config = {
        "run_public_id": run_public_id,
        "experiment_title": experiment_spec.title,
        "objective": experiment_spec.objective,
        "baseline_description": experiment_spec.baseline_description,
        "method_description": experiment_spec.method_description,
        "metrics": experiment_spec.metrics,
        "expected_outputs": experiment_spec.expected_outputs,
        "gpu_required": experiment_spec.gpu_required,
        "resource_requirements": experiment_spec.resource_requirements,
        "artifact_dir": "/artifacts",
        "dataset_path": "fixtures/offline_binary_classification.jsonl",
    }
    paths.workspace_config_path.write_text(
        json.dumps(run_config, indent=2),
        encoding="utf-8",
    )
    (workspace_path / "generated_runs" / run_public_id / "README.md").write_text(
        "\n".join(
            [
                f"# Run {run_public_id}",
                "",
                f"- Experiment: {experiment_spec.title}",
                f"- Objective: {experiment_spec.objective}",
                f"- GPU required: {experiment_spec.gpu_required}",
            ]
        ),
        encoding="utf-8",
    )
    return paths


def build_run_spec(
    *,
    config: AppConfig,
    run_public_id: str,
    workspace_path: Path,
    experiment_spec: ExperimentSpec,
    execution_profile: str,
    patch_archive_path: Path,
    artifact_root: Path,
    env_overrides: dict[str, str] | None = None,
) -> RunSpec:
    profile = load_execution_profile(config, execution_profile)
    image = load_execution_image(config, profile["image_key"])
    mounts = [
        {"source_path": str(workspace_path), "target_path": "/workspace", "read_only": False},
        {"source_path": str(artifact_root), "target_path": "/artifacts", "read_only": False},
        {"source_path": str(config.datasets_dir), "target_path": "/datasets", "read_only": True},
    ]
    command = [
        "python",
        f"/workspace/generated_runs/{run_public_id}/train.py",
        "--config",
        f"/workspace/generated_runs/{run_public_id}/run_config.json",
        "--artifact-dir",
        "/artifacts",
    ]
    return RunSpec(
        workspace_path=str(workspace_path),
        image=image["image"],
        build_recipe={},
        command=command,
        env_vars={
            "SYTHETOS_EXPERIMENT_TITLE": experiment_spec.title,
            **(env_overrides or {}),
        },
        mounts=mounts,
        hardware_profile=profile["hardware_profile"],
        timeout_seconds=int(profile["timeout_seconds"]),
        memory_limit_mb=int(profile["memory_limit_mb"]),
        cpu_limit=str(profile.get("cpu_limit")) if profile.get("cpu_limit") else None,
        gpu_enabled=bool(profile.get("gpu_enabled", False)),
        network_mode=str(profile.get("network_mode", "disabled")),
        artifact_output_path=str(artifact_root),
        patch_archive_path=str(patch_archive_path),
    )


def preflight_run_spec(spec: RunSpec) -> list[str]:
    issues: list[str] = []
    if not Path(spec.workspace_path).exists():
        issues.append("Workspace path does not exist.")
    if not spec.command:
        issues.append("Execution command is empty.")
    if spec.network_mode not in {"disabled", "bridge", "host"}:
        issues.append(f"Unsupported network mode {spec.network_mode!r}.")
    if not Path(spec.artifact_output_path).exists():
        issues.append("Artifact output path does not exist.")
    return issues
