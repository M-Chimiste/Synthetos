"""Runtime model settings behavior."""

from __future__ import annotations

import uuid

import pytest

from libs.adapters.llm import router as router_module
from libs.core.services.model_settings_service import (
    catalog_entry_to_role_config,
    resolve_yaml_role_config,
)
from libs.schemas.model_gateway import ModelRole
from libs.schemas.settings import ModelCatalogEntryCreate
from libs.storage.models.settings import ModelCatalogEntry, ModelRoleBinding


def test_catalog_entry_to_role_config_applies_binding_overrides() -> None:
    entry = ModelCatalogEntry(
        id=uuid.uuid4(),
        key="local:test",
        display_name="Local test",
        provider_type="openai_compatible",
        provider_name="local",
        model="qwen-test",
        base_url="http://localhost:11434/v1",
        default_temperature=0.7,
        default_max_tokens=4096,
        enabled=True,
        notes=None,
    )
    binding = ModelRoleBinding(
        role=ModelRole.coding.value,
        catalog_entry_id=entry.id,
        catalog_entry=entry,
        temperature=0.2,
        max_tokens=1024,
    )

    cfg = catalog_entry_to_role_config(entry, binding)

    assert cfg == {
        "provider": "local",
        "provider_type": "openai_compatible",
        "model": "qwen-test",
        "base_url": "http://localhost:11434/v1",
        "temperature": 0.2,
        "max_tokens": 1024,
    }


def test_catalog_entry_to_role_config_rejects_disabled_entry() -> None:
    entry = ModelCatalogEntry(
        id=uuid.uuid4(),
        key="anthropic:test",
        display_name="Disabled",
        provider_type="anthropic",
        provider_name="anthropic",
        model="claude-test",
        enabled=False,
    )

    with pytest.raises(ValueError, match="disabled"):
        catalog_entry_to_role_config(entry)


def test_openai_compatible_catalog_entry_requires_base_url() -> None:
    with pytest.raises(ValueError, match="base_url"):
        ModelCatalogEntryCreate(
            key="local:missing-url",
            display_name="Missing URL",
            provider_type="openai_compatible",
            provider_name="local",
            model="default",
        )


def test_yaml_role_config_merges_defaults_and_provider_type() -> None:
    cfg = {
        "defaults": {"temperature": 0.7, "max_tokens": 4096},
        "providers": {"local": {"type": "openai_compatible", "base_url": "http://llm/v1"}},
        "roles": {"coding": {"provider": "local", "model": "default", "temperature": 0.2}},
    }

    role_cfg = resolve_yaml_role_config(ModelRole.coding, cfg)

    assert role_cfg["provider_type"] == "openai_compatible"
    assert role_cfg["base_url"] == "http://llm/v1"
    assert role_cfg["temperature"] == 0.2
    assert role_cfg["max_tokens"] == 4096


def test_model_router_uses_db_binding_before_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        router_module,
        "load_db_role_config",
        lambda role: {
            "provider": "local",
            "provider_type": "openai_compatible",
            "model": "db-model",
            "base_url": "http://db/v1",
            "temperature": 0.1,
        },
    )
    router = router_module.ModelRouter()

    role_cfg = router.get_role_config(ModelRole.coding)

    assert role_cfg["model"] == "db-model"
    assert role_cfg["base_url"] == "http://db/v1"
    assert role_cfg["max_tokens"] == 4096
