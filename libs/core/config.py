from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class PolicyConfig(BaseModel):
    """Typed representation of parsed policy defaults."""

    max_retry_attempts: int = 3
    max_concurrent_runs: int = 2
    lease_timeout_minutes: int = 5
    skill_validation_mode: str = "strict"

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> PolicyConfig:
        execution = raw.get("execution", {})
        skills = raw.get("skills", {})
        return cls(
            max_retry_attempts=execution.get("max_retry_attempts", 3),
            max_concurrent_runs=execution.get("max_concurrent_runs", 2),
            lease_timeout_minutes=execution.get("lease_timeout_minutes", 5),
            skill_validation_mode=skills.get("validation_mode", "strict"),
        )

    def validate_policy(self) -> list[str]:
        errors: list[str] = []
        if self.max_retry_attempts < 0:
            errors.append("execution.max_retry_attempts must be >= 0")
        if self.max_concurrent_runs < 1:
            errors.append("execution.max_concurrent_runs must be >= 1")
        if self.lease_timeout_minutes < 1:
            errors.append("execution.lease_timeout_minutes must be >= 1")
        if self.skill_validation_mode not in {"strict", "lenient"}:
            errors.append(
                f"skills.validation_mode must be 'strict' or 'lenient', "
                f"got '{self.skill_validation_mode}'"
            )
        return errors


class AppConfig(BaseModel):
    env: str = "dev"
    db_url: str = "sqlite:///./synthetos.db"
    data_root: Path = Path(".lab_data")
    model_config_path: Path = Path("configs/models/routes.yaml")
    policy_config_path: Path = Path("configs/policies/default.yaml")
    execution_images_path: Path = Path("configs/execution/images.yaml")
    execution_profiles_path: Path = Path("configs/execution/profiles.yaml")
    execution_settings_path: Path = Path("configs/execution/settings.yaml")
    skill_paths: list[Path] = Field(default_factory=lambda: [Path("skills")])
    dev_admin_token: str = "lab-local-admin"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    auto_init_db: bool = True
    _policy: PolicyConfig | None = None

    def load_yaml(self, path: Path) -> dict[str, Any]:
        resolved = Path(path)
        if not resolved.exists():
            return {}
        with resolved.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return data

    @property
    def policy(self) -> PolicyConfig:
        if self._policy is None:
            raw = self.load_yaml(self.policy_config_path)
            self._policy = PolicyConfig.from_raw(raw)
        return self._policy

    @property
    def reports_dir(self) -> Path:
        return self.data_root / "artifacts" / "reports"

    @property
    def workspaces_dir(self) -> Path:
        return self.data_root / "workspaces"

    @property
    def run_artifacts_dir(self) -> Path:
        return self.data_root / "artifacts" / "runs"

    @property
    def patches_dir(self) -> Path:
        return self.data_root / "artifacts" / "patches"

    @property
    def datasets_dir(self) -> Path:
        return self.data_root / "cache" / "datasets"

    def ensure_data_dirs(self) -> None:
        for directory in [
            self.data_root / "artifacts",
            self.data_root / "cache",
            self.reports_dir,
            self.run_artifacts_dir,
            self.patches_dir,
            self.workspaces_dir,
            self.datasets_dir,
            self.data_root / "exports",
        ]:
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    raw_skill_paths = os.getenv("LAB_SKILL_PATHS", "skills")
    config = AppConfig(
        env=os.getenv("LAB_ENV", "dev"),
        db_url=os.getenv("LAB_DB_URL", "sqlite:///./synthetos.db"),
        data_root=Path(os.getenv("LAB_DATA_ROOT", ".lab_data")),
        model_config_path=Path(os.getenv("LAB_MODEL_CONFIG", "configs/models/routes.yaml")),
        policy_config_path=Path(os.getenv("LAB_POLICY_CONFIG", "configs/policies/default.yaml")),
        execution_images_path=Path(
            os.getenv("LAB_EXECUTION_IMAGES_CONFIG", "configs/execution/images.yaml")
        ),
        execution_profiles_path=Path(
            os.getenv("LAB_EXECUTION_PROFILES_CONFIG", "configs/execution/profiles.yaml")
        ),
        execution_settings_path=Path(
            os.getenv("LAB_EXECUTION_SETTINGS_CONFIG", "configs/execution/settings.yaml")
        ),
        skill_paths=[Path(item) for item in raw_skill_paths.split(":") if item],
        dev_admin_token=os.getenv("LAB_DEV_ADMIN_TOKEN", "lab-local-admin"),
        api_host=os.getenv("LAB_API_HOST", "127.0.0.1"),
        api_port=int(os.getenv("LAB_API_PORT", "8000")),
        auto_init_db=os.getenv("LAB_AUTO_INIT_DB", "true").lower() == "true",
    )
    config.ensure_data_dirs()
    return config
