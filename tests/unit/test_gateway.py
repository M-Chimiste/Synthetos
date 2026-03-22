from pathlib import Path

import pytest

from libs.adapters.llm.gateway import ModelGateway
from libs.core.config import AppConfig


def test_route_resolution_prefers_explicit_id() -> None:
    config = AppConfig(model_config_path=Path("configs/models/routes.yaml"))
    gateway = ModelGateway.from_config(config)
    route = gateway.resolve_route("planning", preferred_route_id="local-default")
    assert route.id == "local-default"


def test_route_resolution_supports_triage_role() -> None:
    config = AppConfig(model_config_path=Path("configs/models/routes.yaml"))
    gateway = ModelGateway.from_config(config)
    route = gateway.resolve_route("triage")
    assert route.id == "hosted-triage"


def test_route_resolution_raises_for_missing_triage_role(tmp_path: Path) -> None:
    config_path = tmp_path / "routes.yaml"
    config_path.write_text(
        "\n".join(
            [
                "routes:",
                "  - id: hosted-default",
                "    role: planning",
                "    provider: openai_compatible",
                "    base_url: https://api.openai.com/v1",
                "    model: gpt-5.4-mini",
            ]
        ),
        encoding="utf-8",
    )
    gateway = ModelGateway.from_config(AppConfig(model_config_path=config_path))
    with pytest.raises(ValueError, match="triage"):
        gateway.resolve_route("triage")
