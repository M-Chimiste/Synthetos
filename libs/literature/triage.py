"""LLM-based literature triage for title + abstract scoring.

Calls the model gateway with a rendered prompt template and parses
structured JSON responses for each paper.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jinja2
import structlog
from pydantic import BaseModel

from libs.adapters.llm.gateway import ModelGateway

log = structlog.get_logger(__name__)

DEFAULT_PROMPT_PATH = "prompts/literature/v1/title_abstract_triage.md"


class TriageRequest(BaseModel):
    paper_id: str
    title: str
    abstract: str | None
    charter_problem: str
    charter_criteria: dict[str, Any]


class TriageResponse(BaseModel):
    paper_id: str
    decision: str  # advance, reject, uncertain
    score: float  # 0.0 - 1.0
    rationale: str


def _load_prompt_template(prompt_path: str) -> str:
    path = Path(prompt_path)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    # Fallback inline template
    return (
        "Evaluate this paper for relevance to the research problem.\n\n"
        "## Research Problem\n{{ charter_problem }}\n\n"
        "## Paper\n**Title:** {{ title }}\n"
        "**Abstract:** {{ abstract or 'No abstract available' }}\n\n"
        "Respond in JSON: "
        '{"decision": "advance"|"reject"|"uncertain", '
        '"score": <float 0.0-1.0>, '
        '"rationale": "<2-3 sentences>"}'
    )


def _render_prompt(template_text: str, request: TriageRequest) -> str:
    env = jinja2.Environment(autoescape=False, undefined=jinja2.StrictUndefined)
    tmpl = env.from_string(template_text)
    return tmpl.render(
        charter_problem=request.charter_problem,
        charter_criteria=request.charter_criteria,
        title=request.title,
        abstract=request.abstract or "No abstract available",
    )


def _parse_triage_json(text: str, paper_id: str) -> TriageResponse:
    """Best-effort extraction of triage JSON from LLM response text."""
    # Try to find JSON in the response
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                if isinstance(data, dict):
                    return TriageResponse(
                        paper_id=paper_id,
                        decision=data.get("decision", "uncertain"),
                        score=float(data.get("score", 0.5)),
                        rationale=data.get("rationale", "Parsed from LLM response"),
                    )
            except (json.JSONDecodeError, ValueError):
                continue

    log.warning("triage_json_parse_failed", paper_id=paper_id)
    return TriageResponse(
        paper_id=paper_id,
        decision="uncertain",
        score=0.5,
        rationale="Failed to parse LLM triage response; marked as uncertain.",
    )


def triage_batch(
    gateway: ModelGateway,
    papers: list[TriageRequest],
    prompt_path: str = DEFAULT_PROMPT_PATH,
    model_role: str = "triage",
) -> list[TriageResponse]:
    """Score a batch of papers using the triage model route.

    Each paper is sent as its own chat completion call for deterministic
    per-paper lineage. Returns one TriageResponse per paper.
    """
    template_text = _load_prompt_template(prompt_path)
    responses: list[TriageResponse] = []

    for request in papers:
        rendered = _render_prompt(template_text, request)
        try:
            result = gateway.call_chat_completion(
                role=model_role,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a research paper triage assistant. "
                            "Respond only with valid JSON."
                        ),
                    },
                    {"role": "user", "content": rendered},
                ],
                temperature=0.2,
                max_tokens=512,
            )
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            responses.append(_parse_triage_json(content, request.paper_id))
        except Exception as exc:
            log.warning(
                "triage_call_failed",
                paper_id=request.paper_id,
                error=str(exc),
            )
            responses.append(
                TriageResponse(
                    paper_id=request.paper_id,
                    decision="uncertain",
                    score=0.5,
                    rationale=f"LLM call failed: {exc}",
                )
            )

    return responses
