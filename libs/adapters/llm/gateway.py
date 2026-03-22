"""Provider-agnostic LLM gateway with role-based routing.

Supports OpenAI-compatible (vLLM, LM Studio, Ollama, OpenAI), Anthropic,
and Google providers.  All calls go through raw ``httpx`` — no vendor SDKs.
"""

from __future__ import annotations

import os

import httpx
from pydantic import BaseModel

from libs.adapters.llm import providers
from libs.adapters.llm.json_utils import parse_json_lenient
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

    # ------------------------------------------------------------------
    # Route resolution
    # ------------------------------------------------------------------

    def resolve_route(
        self, role: str, preferred_route_id: str | None = None,
    ) -> ModelRouteConfig:
        """Resolve a model route by *preferred_route_id* or *role*.

        When multiple routes share the same role the one with the lowest
        ``priority`` value wins (0 = highest priority).
        """
        if preferred_route_id is not None:
            for route in self.routes:
                if route.id == preferred_route_id:
                    return route

        candidates = [r for r in self.routes if r.role == role]
        if not candidates:
            raise ValueError(f"No model route configured for role {role!r}")
        candidates.sort(key=lambda r: r.priority)
        return candidates[0]

    # ------------------------------------------------------------------
    # Chat completion
    # ------------------------------------------------------------------

    def _get_api_key(self, route: ModelRouteConfig) -> str | None:
        if route.api_key_env:
            return os.getenv(route.api_key_env)
        return None

    def call_chat_completion(
        self,
        role: str,
        messages: list[dict[str, str]],
        *,
        preferred_route_id: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> str:
        """Call an LLM and return the extracted content string.

        The ``route.provider`` field determines how the HTTP request is
        constructed and how the response is parsed.  When *json_mode* is
        ``True`` and the route supports it, a structured-output hint is
        sent to the provider (e.g. ``response_format`` for OpenAI).
        """
        route = self.resolve_route(role, preferred_route_id)
        api_key = self._get_api_key(route)

        endpoint = providers.get_endpoint(route.provider, route.base_url, route.model)
        headers = providers.build_headers(route.provider, api_key)
        params = providers.get_query_params(route.provider, api_key)
        payload = providers.build_payload(
            route.provider,
            route.model,
            messages,
            temperature,
            max_tokens,
            json_mode=json_mode and route.supports_json_mode,
        )

        response = httpx.post(
            endpoint,
            headers=headers,
            params=params or None,
            json=payload,
            timeout=route.timeout_seconds,
        )
        response.raise_for_status()
        return providers.extract_content(route.provider, response.json())

    def call_structured(
        self,
        role: str,
        messages: list[dict[str, str]],
        *,
        preferred_route_id: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> dict | list:
        """Call an LLM with JSON mode and return parsed JSON.

        Uses ``json-repair`` as a fallback for malformed LLM output.
        """
        text = self.call_chat_completion(
            role=role,
            messages=messages,
            preferred_route_id=preferred_route_id,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
        )
        return parse_json_lenient(text)

    # ------------------------------------------------------------------
    # Health probes
    # ------------------------------------------------------------------

    def probe_route(self, route: ModelRouteConfig) -> ModelProbeResult:
        headers: dict[str, str] = {}
        api_key = self._get_api_key(route)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
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

    def probe_all(self) -> list[ModelProbeResult]:
        return [self.probe_route(route) for route in self.routes]
