"""LLM-based hypothesis generation from evidence cards."""

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

PROMPT_PATH = "prompts/ideation/v1/hypothesis_generation.md"
SYSTEM_PROMPT = "You are a research hypothesis generation assistant. Respond only with valid JSON."


class GeneratedHypothesis(BaseModel):
    title: str
    statement: str
    rationale: str
    approach_summary: str
    supporting_evidence_ids: list[str] = []
    counter_evidence_ids: list[str] = []


class HypothesisGenRequest(BaseModel):
    charter_problem: str
    charter_criteria: dict[str, Any]
    evidence_summary: list[dict[str, Any]]
    num_hypotheses: int = 5


class HypothesisGenResponse(BaseModel):
    hypotheses: list[GeneratedHypothesis]


def _load_prompt_template(prompt_path: str) -> str:
    p = Path(prompt_path)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return (
        "Generate {{ num_hypotheses }} candidate research hypotheses "
        "based on the evidence below.\n\n"
        "Research problem: {{ charter_problem }}\n\n"
        "Evidence:\n{% for e in evidence_summary %}"
        "- [{{ e.public_id }}] {{ e.claim }} ({{ e.evidence_type }}, {{ e.strength }})\n"
        "{% endfor %}\n\n"
        "Return a JSON array of hypothesis objects, each with:\n"
        "- title, statement, rationale, approach_summary,\n"
        "- supporting_evidence_ids (list of evidence public_ids),\n"
        "- counter_evidence_ids (list of evidence public_ids)\n"
    )


def _render_prompt(template_text: str, request: HypothesisGenRequest) -> str:
    try:
        from jinja2 import Template

        tmpl = Template(template_text)
        return tmpl.render(
            charter_problem=request.charter_problem,
            charter_criteria=request.charter_criteria,
            evidence_summary=request.evidence_summary,
            num_hypotheses=request.num_hypotheses,
        )
    except Exception:
        return template_text


def _parse_hypotheses_json(text: str) -> list[GeneratedHypothesis]:
    try:
        raw = parse_json_lenient(text)
        if isinstance(raw, list):
            return [GeneratedHypothesis(**item) for item in raw if isinstance(item, dict)]
        return []
    except (ValueError, TypeError) as exc:
        log.warning("hypothesis_json_parse_failed", error=str(exc))
        return []


def generate_hypotheses(
    gateway: ModelGateway,
    request: HypothesisGenRequest,
    prompt_path: str = PROMPT_PATH,
    model_role: str = "ideation",
    session: Session | None = None,
    cycle_id: int | None = None,
    job_id: int | None = None,
    invocation_parameters: dict[str, Any] | None = None,
) -> HypothesisGenResponse:
    """Generate N candidate hypotheses from evidence (single LLM call)."""
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
            temperature=0.7,
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
                    "evidence_count": len(request.evidence_summary),
                    "num_hypotheses": request.num_hypotheses,
                },
                usage={},
            )
        hypotheses = _parse_hypotheses_json(response_text)
    except Exception as exc:
        log.warning("hypothesis_generation_failed", error=str(exc))
        hypotheses = []

    return HypothesisGenResponse(hypotheses=hypotheses)
