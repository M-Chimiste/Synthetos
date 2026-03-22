"""LLM-based protocol compilation: hypothesis → ExperimentSpec."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel

from libs.adapters.llm.gateway import ModelGateway
from libs.adapters.llm.json_utils import parse_json_lenient

log = structlog.get_logger(__name__)

PROMPT_PATH = "prompts/ideation/v1/protocol_compilation.md"
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


def _parse_protocol_json(text: str) -> ProtocolCompileResponse:
    try:
        raw = parse_json_lenient(text)
        if isinstance(raw, dict):
            return ProtocolCompileResponse(**raw)
    except (ValueError, TypeError) as exc:
        log.warning("protocol_json_parse_failed", error=str(exc))
    return ProtocolCompileResponse()


def compile_protocol(
    gateway: ModelGateway,
    request: ProtocolCompileRequest,
    prompt_path: str = PROMPT_PATH,
    model_role: str = "protocol_drafter",
) -> ProtocolCompileResponse:
    """Turn an approved hypothesis into a structured experiment spec."""
    template_text = _load_prompt_template(prompt_path)
    user_content = _render_prompt(template_text, request)

    try:
        response_text = gateway.call_chat_completion(
            role=model_role,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=2048,
            json_mode=True,
        )
        return _parse_protocol_json(response_text)
    except Exception as exc:
        log.warning("protocol_compilation_failed", error=str(exc))
        return ProtocolCompileResponse()
