from __future__ import annotations

import subprocess
from pathlib import Path

from libs.adapters.container import build_docker_run_command
from libs.adapters.git import GitWorktreeAdapter
from libs.core.config import AppConfig
from libs.execution.policy import evaluate_run_policy
from libs.schemas.domain import RunSpec


def test_evaluate_run_policy_allows_cpu_small(tmp_path: Path):
    config = AppConfig(
        env="test",
        db_url=f"sqlite:///{tmp_path / 'test.db'}",
        data_root=tmp_path / "data",
        model_config_path=Path("configs/models/routes.yaml"),
        policy_config_path=Path("configs/policies/default.yaml"),
        execution_images_path=Path("configs/execution/images.yaml"),
        execution_profiles_path=Path("configs/execution/profiles.yaml"),
        execution_settings_path=Path("configs/execution/settings.yaml"),
        skill_paths=[Path("skills")],
        auto_init_db=False,
    )
    decision = evaluate_run_policy(
        config,
        execution_profile="cpu-small",
        network_mode="disabled",
        image_key="offline-baseline",
        force_start=False,
    )
    assert decision.allowed is True
    assert decision.reason is None


def test_evaluate_run_policy_blocks_network_without_force_start(tmp_path: Path):
    config = AppConfig(
        env="test",
        db_url=f"sqlite:///{tmp_path / 'test.db'}",
        data_root=tmp_path / "data",
        model_config_path=Path("configs/models/routes.yaml"),
        policy_config_path=Path("configs/policies/default.yaml"),
        execution_images_path=Path("configs/execution/images.yaml"),
        execution_profiles_path=Path("configs/execution/profiles.yaml"),
        execution_settings_path=Path("configs/execution/settings.yaml"),
        skill_paths=[Path("skills")],
        auto_init_db=False,
    )
    decision = evaluate_run_policy(
        config,
        execution_profile="restricted-net",
        network_mode="enabled",
        image_key="offline-baseline",
        force_start=False,
    )
    assert decision.allowed is False
    assert decision.requires_force_start is True
    assert "force_start" in (decision.reason or "")


def test_build_docker_run_command_includes_mounts_and_limits():
    spec = RunSpec(
        workspace_path="/tmp/workspace",
        image="python:3.12-slim",
        build_recipe={},
        command=["python", "train.py"],
        env_vars={"A": "1"},
        mounts=[
            {"source_path": "/tmp/workspace", "target_path": "/workspace", "read_only": False},
            {"source_path": "/tmp/data", "target_path": "/datasets", "read_only": True},
        ],
        hardware_profile="gpu-small",
        timeout_seconds=60,
        memory_limit_mb=4096,
        cpu_limit="4",
        gpu_enabled=True,
        network_mode="disabled",
        artifact_output_path="/tmp/artifacts",
        patch_archive_path="/tmp/patch.diff",
    )
    command = build_docker_run_command("synthetos-run", spec)
    assert "--gpus" in command
    assert "--memory" in command
    assert "4096m" in command
    assert "/tmp/data:/datasets:ro" in command
    assert command[-2:] == ["python", "train.py"]


def test_git_worktree_adapter_creates_patch_archive(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    (repo_root / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )

    adapter = GitWorktreeAdapter(repo_root)
    worktree = adapter.create_worktree(tmp_path / "workspaces", "run-123")
    (worktree.workspace_path / "README.md").write_text("changed\n", encoding="utf-8")
    archive = adapter.capture_patch_archive(
        worktree.workspace_path,
        tmp_path / "patches" / "run-123.diff",
    )

    assert archive.exists()
    assert "diff --git" in archive.read_text(encoding="utf-8")
