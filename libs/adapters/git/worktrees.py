from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorktreeInfo:
    workspace_path: Path
    base_commit: str
    base_branch: str


class GitWorktreeAdapter:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def create_worktree(self, workspaces_root: Path, run_public_id: str) -> WorktreeInfo:
        workspace_path = workspaces_root / run_public_id
        base_commit = self._git("rev-parse", "HEAD")
        base_branch = self._git("rev-parse", "--abbrev-ref", "HEAD")
        if not workspace_path.exists():
            self._git("worktree", "add", "--detach", str(workspace_path), base_commit)
        return WorktreeInfo(
            workspace_path=workspace_path,
            base_commit=base_commit,
            base_branch=base_branch,
        )

    def capture_patch_archive(self, workspace_path: Path, destination: Path) -> Path:
        diff = self._git("-C", str(workspace_path), "diff", "--binary")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(diff, encoding="utf-8")
        return destination

    def _git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()
