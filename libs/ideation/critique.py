"""LLM-based hypothesis critique and scoring."""

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

PROMPT_PATH = "prompts/ideation/v1/hypothesis_critique.md"
SYSTEM_PROMPT = "You are a research hypothesis critic. Respond only with valid JSON."


class CritiqueRequest(BaseModel):
    hypothesis_title: str
    statement: str
    rationale: str
    approach_summary: str
    supporting_evidence: list[dict[str, Any]]
    counter_evidence: list[dict[str, Any]]
    charter_problem: str


class CritiqueResponse(BaseModel):
    novelty_score: float = 0.5
    feasibility_score: float = 0.5
    impact_score: float = 0.5
    critique_summary: str = ""
    issues: list[dict[str, str]] = []


def _load_prompt_template(prompt_path: str) -> str:
    p = Path(prompt_path)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return (
        "Critique the following hypothesis for a research problem.\n\n"
        "Research problem: {{ charter_problem }}\n\n"
        "Hypothesis: {{ hypothesis_title }}\n"
        "Statement: {{ statement }}\n"
        "Rationale: {{ rationale }}\n"
        "Approach: {{ approach_summary }}\n\n"
        "Supporting evidence:\n{% for e in supporting_evidence %}"
        "- {{ e.claim }}\n{% endfor %}\n\n"
        "Counter evidence:\n{% for e in counter_evidence %}"
        "- {{ e.claim }}\n{% endfor %}\n\n"
        "Return JSON with: novelty_score (0-1), feasibility_score (0-1), impact_score (0-1),\n"
        "critique_summary (string), issues (array of {issue, severity} "
        "where severity is blocking/warning/note)\n"
    )


def _render_prompt(template_text: str, request: CritiqueRequest) -> str:
    try:
        from jinja2 import Template

        tmpl = Template(template_text)
        return tmpl.render(
            charter_problem=request.charter_problem,
            hypothesis_title=request.hypothesis_title,
            statement=request.statement,
            rationale=request.rationale,
            approach_summary=request.approach_summary,
            supporting_evidence=request.supporting_evidence,
            counter_evidence=request.counter_evidence,
        )
    except Exception:
        return template_text


def _parse_critique_json(text: str) -> CritiqueResponse:
    try:
        raw = parse_json_lenient(text)
        if isinstance(raw, dict):
            return CritiqueResponse(**raw)
    except (ValueError, TypeError) as exc:
        log.warning("critique_json_parse_failed", error=str(exc))
    return CritiqueResponse(critique_summary="Failed to parse critique response")


def critique_hypothesis(
    gateway: ModelGateway,
    request: CritiqueRequest,
    prompt_path: str = PROMPT_PATH,
    model_role: str = "critic",
    session: Session | None = None,
    cycle_id: int | None = None,
    job_id: int | None = None,
    invocation_parameters: dict[str, Any] | None = None,
) -> CritiqueResponse:
    """Score a hypothesis on novelty, feasibility, impact."""
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
            temperature=0.2,
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
                    "supporting_evidence_count": len(request.supporting_evidence),
                    "counter_evidence_count": len(request.counter_evidence),
                },
                usage={},
            )
        return _parse_critique_json(response_text)
    except Exception as exc:
        log.warning("critique_failed", error=str(exc))
        return CritiqueResponse(critique_summary=f"Critique failed: {exc}")
