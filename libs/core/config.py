"""Application configuration loaded from environment variables and .env files."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
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

    # When the worker runs inside a container and spawns sibling experiment
    # containers, set this to the named Docker volume mounted at data_root.
    # DockerRunner uses it instead of host-path bind mounts so siblings see
    # the same workspace files. Leave None when running on the host.
    container_data_volume: str | None = None

    # Model gateway config path
    model_config_path: Path = Field(
        default=Path("configs/models.yaml"),
        validation_alias=AliasChoices("LAB_MODEL_CONFIG_PATH", "LAB_MODEL_CONFIG"),
    )

    # Skill discovery paths (colon-separated)
    skill_paths: str = "skills"

    # Versioned prompt templates root
    prompts_root: Path = Field(default=Path("prompts"))

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

    # Worker: job retry policy. Transient failures (connection errors, LLM
    # retry exhaustion, timeouts) requeue with exponential backoff until
    # max_attempts; permanent failures fail immediately.
    job_default_max_attempts: int = 3
    job_max_attempts_overrides: dict[str, int] = Field(default_factory=dict)
    job_retry_backoff_base_s: int = 60
    job_retry_backoff_cap_s: int = 1800

    # Worker: per-job wall-clock deadline. LLM-heavy operators on slow local
    # inference are legitimately slow, so the default is generous (4h). When
    # the deadline trips, the job supervisor signals cooperative cancellation
    # (classified as a retryable timeout).
    job_default_timeout_s: int = 14400
    job_timeout_overrides: dict[str, int] = Field(default_factory=dict)

    # How long after a cancel/timeout signal before the supervisor starts
    # logging errors about an operator that won't unwind.
    job_cancel_grace_s: int = 600

    # LLM call transcript logging (llm_calls table). Prompt/response text is
    # only stored when llm_log_prompts is enabled; hashes are always stored.
    llm_call_logging_enabled: bool = True
    llm_log_prompts: bool = False
    llm_log_max_response_chars: int = 20000

    # Pattern decay scheduling (Phase 6 §1.5)
    pattern_decay_interval_h: int = 24
    pattern_max_staleness_days: int = 90

    # Experiment image GC: keep at most this many `synthetos-exp-*` images
    # on the host. The periodic tick prunes the oldest beyond this count.
    experiment_image_max_keep: int = 5

    @model_validator(mode="after")
    def resolve_paths(self) -> Settings:
        """Normalize roots early so Docker bind mounts and git worktrees are absolute."""
        if not self.data_root.is_absolute():
            self.data_root = self.data_root.resolve()
        if not self.repo_root.is_absolute():
            self.repo_root = self.repo_root.resolve()
        if not self.prompts_root.is_absolute():
            self.prompts_root = self.prompts_root.resolve()
        return self

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
