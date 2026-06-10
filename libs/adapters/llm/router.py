"""Role-based model router that dispatches LLM calls to the appropriate adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import yaml

from libs.adapters.llm.anthropic_adapter import AnthropicAdapter
from libs.adapters.llm.concurrency import get_endpoint_limiter
from libs.adapters.llm.google_adapter import GoogleAdapter
from libs.adapters.llm.openai_adapter import OpenAIAdapter
from libs.adapters.llm.openai_compat import OpenAICompatAdapter
from libs.adapters.llm.reliability import ReliableLLMClient
from libs.core.config import get_settings
from libs.core.logging import get_logger
from libs.core.services.llm_call_service import record_llm_call
from libs.core.services.model_settings_service import load_db_role_config

# Keys that must not leak from a primary role config into its fallback: they
# are model-specific (reasoning tags, sampling), endpoint-specific (base_url,
# api_key), or carry retry/fallback state.
_FALLBACK_EXCLUDED_KEYS = (
    "extra_body",
    "strip_reasoning_tags",
    "sampling",
    "fallback",
    "retry",
    "base_url",
    "api_key",
)

# Role-config dict values that deep-merge with defaults instead of shadowing.
_DEEP_MERGE_KEYS = ("retry", "sampling")

if TYPE_CHECKING:
    from pydantic import BaseModel

    from libs.adapters.llm.base import LLMAdapter
    from libs.schemas.model_gateway import CompletionResponse, ModelRole

log = get_logger(__name__)
T = TypeVar("T", bound="BaseModel")


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
        self._reliability = ReliableLLMClient(
            adapter_for_config=self._route_config,
            provider_config=self._get_provider_config,
            limiter=get_endpoint_limiter(),
            recorder=record_llm_call,
        )

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

    def _merge_defaults(self, role_cfg: dict[str, Any]) -> dict[str, Any]:
        """Merge file defaults into a role config.

        Scalar values use setdefault; ``retry``/``sampling`` dicts deep-merge
        so a role can override one retry knob without re-declaring the rest.
        """
        defaults = self._config.get("defaults", {})
        for key, value in defaults.items():
            if key in _DEEP_MERGE_KEYS and isinstance(value, dict):
                merged = dict(value)
                merged.update(role_cfg.get(key) or {})
                role_cfg[key] = merged
            else:
                role_cfg.setdefault(key, value)
        return role_cfg

    def _get_role_config(self, role: ModelRole) -> dict[str, Any]:
        """Get the configuration for a specific role."""
        db_role_cfg = load_db_role_config(role)
        if db_role_cfg is not None:
            return self._merge_defaults(dict(db_role_cfg))

        roles = self._config.get("roles", {})
        if role.value not in roles:
            raise ValueError(
                f"No model configuration for role '{role.value}'. "
                f"Available roles: {list(roles.keys())}"
            )
        return self._merge_defaults(dict(roles[role.value]))

    def _fallback_config(self, role_cfg: dict[str, Any]) -> dict[str, Any] | None:
        """Resolve a role's opt-in fallback into a full role config, or None.

        The fallback inherits generation parameters from the primary role but
        not model-specific keys (extra_body, strip_reasoning_tags, sampling).
        """
        fallback = role_cfg.get("fallback")
        if not fallback:
            return None
        cfg = {
            key: value
            for key, value in role_cfg.items()
            if key not in _FALLBACK_EXCLUDED_KEYS
        }
        cfg.update(fallback)
        provider_cfg = self._get_provider_config(str(cfg.get("provider", "")))
        cfg.setdefault("provider_type", provider_cfg.get("type", cfg.get("provider")))
        if not cfg.get("base_url") and provider_cfg.get("base_url"):
            cfg["base_url"] = provider_cfg["base_url"]
        return cfg

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
        timeout_s = float(role_cfg.get("timeout_s", 600.0))
        sampling = role_cfg.get("sampling")

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
                timeout_s=timeout_s,
                sampling=sampling,
            )
        elif provider_type == "anthropic":
            return AnthropicAdapter(
                model=model,
                api_key=role_cfg.get("api_key"),
                default_temperature=temperature,
                default_max_tokens=max_tokens,
                timeout_s=timeout_s,
                sampling=sampling,
            )
        elif provider_type == "openai":
            return OpenAIAdapter(
                model=model,
                api_key=role_cfg.get("api_key"),
                default_temperature=temperature,
                default_max_tokens=max_tokens,
                timeout_s=timeout_s,
                sampling=sampling,
            )
        elif provider_type == "google":
            return GoogleAdapter(
                model=model,
                api_key=role_cfg.get("api_key"),
                default_temperature=temperature,
                default_max_tokens=max_tokens,
                timeout_s=timeout_s,
                sampling=sampling,
            )
        else:
            raise ValueError(f"Unknown provider type: '{provider_type}'")

    def _adapter_cache_key(self, role_cfg: dict[str, Any]) -> str:
        """Cache key covering every constructor-relevant config value.

        A hash of the full relevant config (not just provider/model/base_url)
        so runtime DB-binding changes to temperature, timeout, etc. rebuild
        the cached adapter instead of silently reusing a stale one.
        """
        relevant = {
            key: role_cfg.get(key)
            for key in (
                "provider",
                "provider_type",
                "model",
                "base_url",
                "api_key",
                "temperature",
                "max_tokens",
                "timeout_s",
                "extra_body",
                "strip_reasoning_tags",
                "sampling",
            )
        }
        payload = json.dumps(relevant, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()

    def _route_config(self, role_cfg: dict[str, Any]) -> LLMAdapter:
        """Get or create the adapter for a resolved role/fallback config."""
        cache_key = self._adapter_cache_key(role_cfg)
        if cache_key not in self._adapters:
            log.info(
                "model_router.creating_adapter",
                provider=role_cfg["provider"],
                model=role_cfg["model"],
            )
            self._adapters[cache_key] = self._build_adapter(role_cfg)
        return self._adapters[cache_key]

    def route(self, role: ModelRole) -> LLMAdapter:
        """Get the adapter for a given model role, creating it if needed."""
        return self._route_config(self._get_role_config(role))

    async def complete(
        self,
        role: ModelRole,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResponse:
        """Dispatch a completion request through the reliability layer."""
        role_cfg = self._get_role_config(role)
        return await self._reliability.complete(
            role=role.value,
            role_cfg=role_cfg,
            fallback_cfg=self._fallback_config(role_cfg),
            messages=messages,
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
        """Dispatch a structured completion through the reliability layer.

        Returns the parsed model directly; response metadata stays internal
        so the ~17 operator call sites keep their signatures.
        """
        role_cfg = self._get_role_config(role)
        structured = await self._reliability.complete_structured(
            role=role.value,
            role_cfg=role_cfg,
            fallback_cfg=self._fallback_config(role_cfg),
            messages=messages,
            response_model=response_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return structured.parsed

    async def close(self) -> None:
        """Close all cached adapter instances."""
        for adapter in self._adapters.values():
            if hasattr(adapter, "close"):
                await adapter.close()
        self._adapters.clear()
        log.info("model_router.closed")
