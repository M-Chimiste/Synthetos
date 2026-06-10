"""Runtime LLM model settings helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from libs.core.config import get_settings
from libs.core.logging import get_logger
from libs.schemas.model_gateway import ModelRole
from libs.storage.base import get_sync_session_factory
from libs.storage.models.settings import ModelCatalogEntry, ModelRoleBinding

log = get_logger(__name__)

PROVIDER_TYPES = {"anthropic", "openai", "google", "openai_compatible"}


def load_model_config(config_path: Path | str | None = None) -> dict[str, Any]:
    """Load the YAML model configuration used as the runtime fallback."""
    path = Path(config_path or get_settings().model_config_path)
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data


def resolve_yaml_role_config(
    role: ModelRole,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Resolve one role from YAML, including defaults and provider metadata."""
    roles = config.get("roles", {})
    if role.value not in roles:
        raise ValueError(
            f"No model configuration for role '{role.value}'. "
            f"Available roles: {list(roles.keys())}"
        )

    role_cfg = dict(roles[role.value])
    defaults = config.get("defaults", {})
    for key, value in defaults.items():
        role_cfg.setdefault(key, value)

    provider = role_cfg["provider"]
    provider_cfg = dict(config.get("providers", {}).get(provider, {}))
    role_cfg.setdefault("provider_type", provider_cfg.get("type", provider))
    if role_cfg["provider_type"] == "openai_compatible":
        role_cfg.setdefault("base_url", provider_cfg.get("base_url"))
    return role_cfg


def yaml_role_defaults(config: dict[str, Any]) -> dict[ModelRole, dict[str, Any]]:
    """Return all YAML role defaults that are present in the fallback config."""
    defaults: dict[ModelRole, dict[str, Any]] = {}
    for role in ModelRole:
        try:
            defaults[role] = resolve_yaml_role_config(role, config)
        except ValueError:
            continue
    return defaults


def catalog_entry_to_role_config(
    entry: ModelCatalogEntry,
    binding: ModelRoleBinding | None = None,
) -> dict[str, Any]:
    """Convert a catalog entry and optional binding into ModelRouter config."""
    if not entry.enabled:
        raise ValueError(f"Model catalog entry '{entry.key}' is disabled")
    if entry.provider_type not in PROVIDER_TYPES:
        raise ValueError(f"Unknown provider type: '{entry.provider_type}'")
    if entry.provider_type == "openai_compatible" and not entry.base_url:
        raise ValueError("base_url required for openai_compatible provider")

    temperature = (
        binding.temperature
        if binding is not None and binding.temperature is not None
        else entry.default_temperature
    )
    max_tokens = (
        binding.max_tokens
        if binding is not None and binding.max_tokens is not None
        else entry.default_max_tokens
    )
    timeout_s = (
        binding.timeout_s
        if binding is not None and binding.timeout_s is not None
        else entry.default_timeout_s
    )

    cfg: dict[str, Any] = {
        "provider": entry.provider_name,
        "provider_type": entry.provider_type,
        "model": entry.model,
    }
    if entry.base_url:
        cfg["base_url"] = entry.base_url
    if temperature is not None:
        cfg["temperature"] = temperature
    if max_tokens is not None:
        cfg["max_tokens"] = max_tokens
    if timeout_s is not None:
        cfg["timeout_s"] = timeout_s
    return cfg


def load_db_role_config(role: ModelRole) -> dict[str, Any] | None:
    """Load an enabled DB role binding for a router instance.

    Returns ``None`` when tables are unavailable or no binding exists, so
    callers can keep the YAML fallback path during migrations and tests.
    """
    if os.environ.get("LAB_MODEL_CONFIG") or os.environ.get("LAB_MODEL_CONFIG_PATH"):
        return None

    try:
        factory = get_sync_session_factory()
        with factory() as session:
            binding = session.execute(
                select(ModelRoleBinding)
                .options(joinedload(ModelRoleBinding.catalog_entry))
                .where(ModelRoleBinding.role == role.value)
            ).scalar_one_or_none()
            if binding is None:
                return None
            return catalog_entry_to_role_config(binding.catalog_entry, binding)
    except SQLAlchemyError as exc:
        log.debug("model_settings.db_lookup_failed", role=role.value, error=str(exc))
        return None
