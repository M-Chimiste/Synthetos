from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    env: str = "dev"
    db_url: str = "sqlite:///./synthetos.db"
    data_root: Path = Path(".lab_data")
    model_config_path: Path = Path("configs/models/routes.yaml")
    policy_config_path: Path = Path("configs/policies/default.yaml")
    skill_paths: list[Path] = Field(default_factory=lambda: [Path("skills")])
    dev_admin_token: str = "lab-local-admin"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    auto_init_db: bool = True

    def load_yaml(self, path: Path) -> dict[str, Any]:
        resolved = Path(path)
        if not resolved.exists():
            return {}
        with resolved.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return data

    @property
    def reports_dir(self) -> Path:
        return self.data_root / "artifacts" / "reports"

    @property
    def workspaces_dir(self) -> Path:
        return self.data_root / "workspaces"

    def ensure_data_dirs(self) -> None:
        for directory in [
            self.data_root / "artifacts",
            self.data_root / "cache",
            self.reports_dir,
            self.workspaces_dir,
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
        skill_paths=[Path(item) for item in raw_skill_paths.split(":") if item],
        dev_admin_token=os.getenv("LAB_DEV_ADMIN_TOKEN", "lab-local-admin"),
        api_host=os.getenv("LAB_API_HOST", "127.0.0.1"),
        api_port=int(os.getenv("LAB_API_PORT", "8000")),
        auto_init_db=os.getenv("LAB_AUTO_INIT_DB", "true").lower() == "true",
    )
    config.ensure_data_dirs()
    return config

