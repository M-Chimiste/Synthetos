"""Application configuration loaded from environment variables and .env files."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Synthetos application settings.

    Values are loaded from environment variables prefixed with LAB_,
    with fallback to a .env file in the project root.
    """

    model_config = SettingsConfigDict(
        env_prefix="LAB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environment
    env: str = "dev"

    # Database
    db_url: str = "postgresql+psycopg://synthetos:synthetos@localhost:5432/synthetos"

    # Data root for artifacts, cache, workspaces, exports
    data_root: Path = Field(default=Path("data"))

    # Model gateway config path
    model_config_path: Path = Field(default=Path("configs/models.yaml"))

    # Skill discovery paths (colon-separated)
    skill_paths: str = "skills"

    # API
    api_port: int = 8000

    # Auto-initialize database on startup
    auto_init_db: bool = True

    # Repo root (for git worktree operations)
    repo_root: Path = Field(default=Path("."))

    # Worker: stale-job reclaim (Phase 6 §5.1)
    job_heartbeat_timeout_s: int = 120
    job_max_reclaims: int = 3
    worker_periodic_tick_s: int = 30

    # Pattern decay scheduling (Phase 6 §1.5)
    pattern_decay_interval_h: int = 24
    pattern_max_staleness_days: int = 90

    @property
    def skill_path_list(self) -> list[Path]:
        return [Path(p.strip()) for p in self.skill_paths.split(":") if p.strip()]

    @property
    def sync_db_url(self) -> str:
        """Return synchronous database URL for Alembic and other sync contexts."""
        return self.db_url


_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create the singleton settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
