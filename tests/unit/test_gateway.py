from pathlib import Path

from libs.adapters.llm.gateway import ModelGateway
from libs.core.config import AppConfig


def test_route_resolution_prefers_explicit_id() -> None:
    config = AppConfig(model_config_path=Path("configs/models/routes.yaml"))
    gateway = ModelGateway.from_config(config)
    route = gateway.resolve_route("planning", preferred_route_id="local-default")
    assert route.id == "local-default"

