"""Role-based model router that dispatches LLM calls to the appropriate adapter."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import yaml

from libs.adapters.llm.anthropic_adapter import AnthropicAdapter
from libs.adapters.llm.google_adapter import GoogleAdapter
from libs.adapters.llm.openai_adapter import OpenAIAdapter
from libs.adapters.llm.openai_compat import OpenAICompatAdapter
from libs.core.config import get_settings
from libs.core.logging import get_logger
from libs.core.services.model_settings_service import load_db_role_config

if TYPE_CHECKING:
    from libs.adapters.llm.base import LLMAdapter
    from libs.schemas.model_gateway import CompletionResponse, ModelRole

log = get_logger(__name__)
T = TypeVar("T")


class ModelRouter:
    """Routes LLM calls to the appropriate adapter based on the model role.

    Loads ``configs/models.yaml`` (or a custom path) and lazily creates
    adapter instances keyed by provider+model.
    """

    def __init__(self, config_path: Path | str | None = None) -> None:
        if config_path is None:
            config_path = get_settings().model_config_path
        self._config_path = Path(config_path)
        self._config: dict[str, Any] = {}
        self._adapters: dict[str, LLMAdapter] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Load and validate the model routing configuration."""
        if not self._config_path.exists():
            raise FileNotFoundError(f"Model config not found: {self._config_path}")

        with open(self._config_path) as f:
            self._config = yaml.safe_load(f)

        log.info(
            "model_router.config_loaded",
            path=str(self._config_path),
            roles=list(self._config.get("roles", {}).keys()),
        )

    def _get_role_config(self, role: ModelRole) -> dict[str, Any]:
        """Get the configuration for a specific role."""
        db_role_cfg = load_db_role_config(role)
        if db_role_cfg is not None:
            role_cfg = dict(db_role_cfg)
            defaults = self._config.get("defaults", {})
            for key, value in defaults.items():
                role_cfg.setdefault(key, value)
            return role_cfg

        roles = self._config.get("roles", {})
        if role.value not in roles:
            raise ValueError(
                f"No model configuration for role '{role.value}'. "
                f"Available roles: {list(roles.keys())}"
            )
        role_cfg = dict(roles[role.value])

        # Merge defaults for missing values
        defaults = self._config.get("defaults", {})
        for key, value in defaults.items():
            role_cfg.setdefault(key, value)

        return role_cfg

    def get_role_config(self, role: ModelRole) -> dict[str, Any]:
        """Expose resolved role configuration for lineage and diagnostics."""
        return dict(self._get_role_config(role))

    def _get_provider_config(self, provider_name: str) -> dict[str, Any]:
        """Get the provider-level configuration."""
        providers = self._config.get("providers", {})
        return dict(providers.get(provider_name, {}))

    def _build_adapter(self, role_cfg: dict[str, Any]) -> LLMAdapter:
        """Create an adapter instance from role configuration."""
        provider = role_cfg["provider"]
        model = role_cfg["model"]
        provider_cfg = self._get_provider_config(provider)
        provider_type = role_cfg.get("provider_type") or provider_cfg.get("type", provider)

        temperature = role_cfg.get("temperature", 0.7)
        max_tokens = role_cfg.get("max_tokens", 4096)

        if provider_type == "openai_compatible":
            base_url = role_cfg.get("base_url") or provider_cfg.get("base_url")
            if not base_url:
                raise ValueError(f"base_url required for openai_compatible provider '{provider}'")
            return OpenAICompatAdapter(
                base_url=base_url,
                model=model,
                api_key=role_cfg.get("api_key", "not-needed"),
                default_temperature=temperature,
                default_max_tokens=max_tokens,
                extra_body=role_cfg.get("extra_body"),
                strip_reasoning_tags=role_cfg.get("strip_reasoning_tags", False),
            )
        elif provider_type == "anthropic":
            return AnthropicAdapter(
                model=model,
                api_key=role_cfg.get("api_key"),
                default_temperature=temperature,
                default_max_tokens=max_tokens,
            )
        elif provider_type == "openai":
            return OpenAIAdapter(
                model=model,
                api_key=role_cfg.get("api_key"),
                default_temperature=temperature,
                default_max_tokens=max_tokens,
            )
        elif provider_type == "google":
            return GoogleAdapter(
                model=model,
                api_key=role_cfg.get("api_key"),
                default_temperature=temperature,
                default_max_tokens=max_tokens,
            )
        else:
            raise ValueError(f"Unknown provider type: '{provider_type}'")

    def _adapter_cache_key(self, role_cfg: dict[str, Any]) -> str:
        """Generate a cache key for an adapter based on its configuration."""
        provider = role_cfg["provider"]
        provider_type = role_cfg.get("provider_type", "")
        model = role_cfg["model"]
        base_url = role_cfg.get("base_url", "")
        return f"{provider}:{provider_type}:{model}:{base_url}"

    def route(self, role: ModelRole) -> LLMAdapter:
        """Get the adapter for a given model role, creating it if needed."""
        role_cfg = self._get_role_config(role)
        cache_key = self._adapter_cache_key(role_cfg)

        if cache_key not in self._adapters:
            log.info(
                "model_router.creating_adapter",
                role=role.value,
                provider=role_cfg["provider"],
                model=role_cfg["model"],
            )
            self._adapters[cache_key] = self._build_adapter(role_cfg)

        return self._adapters[cache_key]

    async def complete(
        self,
        role: ModelRole,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResponse:
        """Dispatch a completion request to the adapter for the given role."""
        adapter = self.route(role)
        return await adapter.complete(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def complete_structured(
        self,
        role: ModelRole,
        messages: list[dict[str, str]],
        response_model: type[T],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> T:
        """Dispatch a structured completion request to the adapter for the given role."""
        adapter = self.route(role)
        return await adapter.complete_structured(
            messages,
            response_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def close(self) -> None:
        """Close all cached adapter instances."""
        for adapter in self._adapters.values():
            if hasattr(adapter, "close"):
                await adapter.close()
        self._adapters.clear()
        log.info("model_router.closed")
