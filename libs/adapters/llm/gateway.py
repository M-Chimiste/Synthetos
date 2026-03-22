from __future__ import annotations

import os

import httpx
from pydantic import BaseModel

from libs.core.config import AppConfig
from libs.schemas.domain import ModelRouteConfig


class ModelProbeResult(BaseModel):
    id: str
    role: str
    base_url: str
    model: str
    reachable: bool
    detail: str


class ModelGateway:
    def __init__(self, routes: list[ModelRouteConfig]):
        self.routes = routes

    @classmethod
    def from_config(cls, config: AppConfig) -> ModelGateway:
        data = config.load_yaml(config.model_config_path)
        routes = [ModelRouteConfig.model_validate(item) for item in data.get("routes", [])]
        return cls(routes)

    def resolve_route(self, role: str, preferred_route_id: str | None = None) -> ModelRouteConfig:
        if preferred_route_id is not None:
            for route in self.routes:
                if route.id == preferred_route_id:
                    return route
        for route in self.routes:
            if route.role == role:
                return route
        raise ValueError(f"No model route configured for role {role}")

    def probe_route(self, route: ModelRouteConfig) -> ModelProbeResult:
        headers: dict[str, str] = {}
        if route.api_key_env and os.getenv(route.api_key_env):
            headers["Authorization"] = f"Bearer {os.getenv(route.api_key_env)}"
        try:
            response = httpx.get(
                f"{route.base_url.rstrip('/')}/models",
                headers=headers,
                timeout=route.timeout_seconds,
            )
            return ModelProbeResult(
                id=route.id,
                role=route.role,
                base_url=route.base_url,
                model=route.model,
                reachable=response.is_success,
                detail=f"status={response.status_code}",
            )
        except Exception as exc:
            return ModelProbeResult(
                id=route.id,
                role=route.role,
                base_url=route.base_url,
                model=route.model,
                reachable=False,
                detail=str(exc),
            )

    def call_chat_completion(
        self,
        role: str,
        messages: list[dict[str, str]],
        *,
        preferred_route_id: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> dict:
        """Call the OpenAI-compatible chat completions endpoint.

        Returns the parsed JSON response dict.
        """
        route = self.resolve_route(role, preferred_route_id)
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if route.api_key_env and os.getenv(route.api_key_env):
            headers["Authorization"] = f"Bearer {os.getenv(route.api_key_env)}"

        payload = {
            "model": route.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        response = httpx.post(
            f"{route.base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
            timeout=route.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def probe_all(self) -> list[ModelProbeResult]:
        return [self.probe_route(route) for route in self.routes]

