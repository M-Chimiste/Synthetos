"""LLM-based protocol compilation: hypothesis → ExperimentSpec."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy.orm import Session

from libs.adapters.llm.gateway import ModelGateway
from libs.adapters.llm.json_utils import parse_json_lenient
from libs.storage.services import record_model_invocation

log = structlog.get_logger(__name__)

PROMPT_PATH = "prompts/ideation/v1/protocol_compilation.md"
VARIATION_PROMPT_PATH = "prompts/ideation/v1/parameter_variation.md"
SYSTEM_PROMPT = "You are a research protocol compiler. Respond only with valid JSON."


class ProtocolCompileRequest(BaseModel):
    hypothesis: dict[str, Any]
    evidence: list[dict[str, Any]]
    charter_problem: str
    charter_criteria: dict[str, Any]
    constraints: dict[str, Any]


class ProtocolCompileResponse(BaseModel):
    title: str = "Untitled Experiment"
    objective: str = ""
    baseline_description: str = ""
    method_description: str = ""
    controls: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    datasets: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    stop_conditions: list[dict[str, Any]] = []
    expected_outputs: list[dict[str, Any]] = []
    estimated_runtime_minutes: int | None = None
    gpu_required: bool = False
    resource_requirements: dict[str, Any] = {}


class ParameterVariationRequest(BaseModel):
    hypothesis_title: str
    objective: str
    method_description: str
    current_controls: list[dict[str, Any]]
    recent_runs: list[dict[str, Any]]
    directional_signal: str | None = None
    hypothesis_run_count: int = 0
    variation_hints: list[dict[str, Any]] = []


class ParameterVariationResponse(BaseModel):
    varied_controls: list[dict[str, Any]] = []
    method_modification: str = ""
    expected_impact: str = ""


def _load_prompt_template(prompt_path: str) -> str:
    p = Path(prompt_path)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return (
        "Compile an experiment protocol from the following hypothesis and evidence.\n\n"
        "Research problem: {{ charter_problem }}\n\n"
        "Hypothesis: {{ hypothesis.title }}\n"
        "Statement: {{ hypothesis.statement }}\n"
        "Approach: {{ hypothesis.approach_summary }}\n\n"
        "Evidence:\n{% for e in evidence %}"
        "- {{ e.claim }} ({{ e.evidence_type }})\n{% endfor %}\n\n"
        "Constraints: {{ constraints }}\n\n"
        "Return JSON with: title, objective, baseline_description, method_description,\n"
        "controls (array), metrics (array), datasets (array), artifacts (array),\n"
        "stop_conditions (array), expected_outputs (array),\n"
        "estimated_runtime_minutes (int or null), gpu_required (bool),\n"
        "resource_requirements (object)\n"
    )


def _render_prompt(template_text: str, request: ProtocolCompileRequest) -> str:
    try:
        from jinja2 import Template

        tmpl = Template(template_text)
        return tmpl.render(
            charter_problem=request.charter_problem,
            charter_criteria=request.charter_criteria,
            hypothesis=request.hypothesis,
            evidence=request.evidence,
            constraints=request.constraints,
        )
    except Exception:
        return template_text


def _render_variation_prompt(
    template_text: str,
    request: ParameterVariationRequest,
) -> str:
    try:
        from jinja2 import Template

        tmpl = Template(template_text)
        return tmpl.render(
            hypothesis_title=request.hypothesis_title,
            objective=request.objective,
            method_description=request.method_description,
            current_controls=request.current_controls,
            recent_runs=request.recent_runs,
            directional_signal=request.directional_signal,
            hypothesis_run_count=request.hypothesis_run_count,
            variation_hints=request.variation_hints,
        )
    except Exception:
        return template_text


def _parse_protocol_json(text: str) -> ProtocolCompileResponse:
    try:
        raw = parse_json_lenient(text)
        if isinstance(raw, dict):
            return ProtocolCompileResponse(**raw)
    except (ValueError, TypeError) as exc:
        log.warning("protocol_json_parse_failed", error=str(exc))
    return ProtocolCompileResponse()


def _parse_variation_json(text: str) -> ParameterVariationResponse:
    try:
        raw = parse_json_lenient(text)
        if isinstance(raw, dict):
            return ParameterVariationResponse(**raw)
    except (ValueError, TypeError) as exc:
        log.warning("parameter_variation_parse_failed", error=str(exc))
    return ParameterVariationResponse()


def compile_protocol(
    gateway: ModelGateway,
    request: ProtocolCompileRequest,
    prompt_path: str = PROMPT_PATH,
    model_role: str = "protocol_drafter",
    session: Session | None = None,
    cycle_id: int | None = None,
    job_id: int | None = None,
    invocation_parameters: dict[str, Any] | None = None,
) -> ProtocolCompileResponse:
    """Turn an approved hypothesis into a structured experiment spec."""
    template_text = _load_prompt_template(prompt_path)
    user_content = _render_prompt(template_text, request)
    route = gateway.resolve_route(model_role)

    try:
        response_text = gateway.call_chat_completion(
            role=model_role,
            preferred_route_id=route.id,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=2048,
            json_mode=True,
        )
        if session is not None and cycle_id is not None:
            record_model_invocation(
                session,
                cycle_id=cycle_id,
                job_id=job_id,
                route_id=route.id,
                model_id=route.model,
                prompt_id=prompt_path,
                parameters={
                    **(invocation_parameters or {}),
                    "hypothesis_title": request.hypothesis.get("title", ""),
                    "evidence_count": len(request.evidence),
                },
                usage={},
            )
        return _parse_protocol_json(response_text)
    except Exception as exc:
        log.warning("protocol_compilation_failed", error=str(exc))
        return ProtocolCompileResponse()


def compile_parameter_variation(
    gateway: ModelGateway,
    request: ParameterVariationRequest,
    prompt_path: str = VARIATION_PROMPT_PATH,
    model_role: str = "protocol_drafter",
    session: Session | None = None,
    cycle_id: int | None = None,
    job_id: int | None = None,
    invocation_parameters: dict[str, Any] | None = None,
) -> ParameterVariationResponse:
    """Ask the protocol drafter for a concrete parameter variation."""

    template_text = _load_prompt_template(prompt_path)
    user_content = _render_variation_prompt(template_text, request)
    route = gateway.resolve_route(model_role)

    try:
        response_text = gateway.call_chat_completion(
            role=model_role,
            preferred_route_id=route.id,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=1024,
            json_mode=True,
        )
        if session is not None and cycle_id is not None:
            record_model_invocation(
                session,
                cycle_id=cycle_id,
                job_id=job_id,
                route_id=route.id,
                model_id=route.model,
                prompt_id=prompt_path,
                parameters={
                    **(invocation_parameters or {}),
                    "hypothesis_title": request.hypothesis_title,
                    "recent_run_count": len(request.recent_runs),
                },
                usage={},
            )
        return _parse_variation_json(response_text)
    except Exception as exc:
        log.warning("parameter_variation_failed", error=str(exc))
        return ParameterVariationResponse()
