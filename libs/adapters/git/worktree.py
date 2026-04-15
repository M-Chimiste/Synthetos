"""Git worktree management for experiment workspace isolation."""

from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import UUID

from libs.core.logging import get_logger

log = get_logger("adapters.git.worktree")


def create_worktree(
    repo_root: Path,
    workspace_base: Path,
    run_id: UUID,
) -> Path:
    """Create a detached git worktree for an experiment run.

    Returns the path to the new worktree directory.
    """
    worktree_path = workspace_base / str(run_id)
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    log.info(
        "worktree.creating",
        repo_root=str(repo_root),
        worktree_path=str(worktree_path),
        run_id=str(run_id),
    )

    subprocess.run(
        ["git", "worktree", "add", str(worktree_path), "--detach"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    return worktree_path


def commit_worktree(worktree_path: Path, message: str) -> str:
    """Stage all files and commit in the worktree. Returns the commit SHA."""
    subprocess.run(
        ["git", "add", "."],
        cwd=str(worktree_path),
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", message, "--allow-empty"],
        cwd=str(worktree_path),
        capture_output=True,
        text=True,
        check=True,
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(worktree_path),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def cleanup_worktree(repo_root: Path, worktree_path: Path) -> None:
    """Remove a git worktree."""
    log.info("worktree.removing", worktree_path=str(worktree_path))
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,  # don't fail if already removed
    )
