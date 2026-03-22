"""Unit tests for libs.adapters.llm.gateway."""

from pathlib import Path

import pytest

from libs.adapters.llm.gateway import ModelGateway
from libs.core.config import AppConfig
from libs.schemas.domain import ModelRouteConfig


def test_route_resolution_prefers_explicit_id() -> None:
    config = AppConfig(model_config_path=Path("configs/models/routes.yaml"))
    gateway = ModelGateway.from_config(config)
    route = gateway.resolve_route("planning", preferred_route_id="local-default")
    assert route.id == "local-default"


def test_route_resolution_supports_triage_role() -> None:
    config = AppConfig(model_config_path=Path("configs/models/routes.yaml"))
    gateway = ModelGateway.from_config(config)
    route = gateway.resolve_route("triage")
    assert route.id == "local-triage"


def test_route_resolution_raises_for_missing_role(tmp_path: Path) -> None:
    config_path = tmp_path / "routes.yaml"
    config_path.write_text(
        "\n".join([
            "routes:",
            "  - id: test-route",
            "    role: planning",
            "    provider: openai_compatible",
            "    base_url: http://localhost:1234/v1",
            "    model: default",
        ]),
        encoding="utf-8",
    )
    gateway = ModelGateway.from_config(AppConfig(model_config_path=config_path))
    with pytest.raises(ValueError, match="triage"):
        gateway.resolve_route("triage")


def test_route_resolution_respects_priority() -> None:
    routes = [
        ModelRouteConfig(
            id="low-priority", role="triage",
            provider="openai_compatible",
            base_url="http://host-a/v1", model="m",
            priority=10,
        ),
        ModelRouteConfig(
            id="high-priority", role="triage",
            provider="openai_compatible",
            base_url="http://host-b/v1", model="m",
            priority=0,
        ),
    ]
    gateway = ModelGateway(routes)
    route = gateway.resolve_route("triage")
    assert route.id == "high-priority"


def test_route_resolution_preferred_id_overrides_priority() -> None:
    routes = [
        ModelRouteConfig(
            id="fallback", role="triage",
            provider="openai_compatible",
            base_url="http://host-a/v1", model="m",
            priority=10,
        ),
        ModelRouteConfig(
            id="primary", role="triage",
            provider="openai_compatible",
            base_url="http://host-b/v1", model="m",
            priority=0,
        ),
    ]
    gateway = ModelGateway(routes)
    route = gateway.resolve_route("triage", preferred_route_id="fallback")
    assert route.id == "fallback"


def test_default_routes_are_local_first() -> None:
    config = AppConfig(model_config_path=Path("configs/models/routes.yaml"))
    gateway = ModelGateway.from_config(config)
    for route in gateway.routes:
        assert "localhost" in route.base_url or "192.168" in route.base_url, (
            f"Route {route.id} points to non-local URL: {route.base_url}"
        )


def test_no_hardcoded_openai_models_in_default_routes() -> None:
    config = AppConfig(model_config_path=Path("configs/models/routes.yaml"))
    gateway = ModelGateway.from_config(config)
    for route in gateway.routes:
        assert "gpt" not in route.model.lower(), (
            f"Route {route.id} has hardcoded OpenAI model: {route.model}"
        )
