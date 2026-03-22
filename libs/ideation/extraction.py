"""LLM-based evidence extraction from shortlisted papers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel

from libs.adapters.llm.gateway import ModelGateway
from libs.adapters.llm.json_utils import parse_json_lenient

log = structlog.get_logger(__name__)

PROMPT_PATH = "prompts/ideation/v1/evidence_extraction.md"
SYSTEM_PROMPT = "You are a research evidence extraction assistant. Respond only with valid JSON."


class ExtractedEvidence(BaseModel):
    claim: str
    evidence_type: str  # finding, method, metric, baseline, limitation, dataset
    strength: str  # strong, moderate, weak, anecdotal
    relevance_score: float
    relevance_rationale: str
    source_section: str | None = None
    source_quote: str | None = None


class EvidenceExtractionRequest(BaseModel):
    paper_id: str
    title: str
    abstract: str | None = None
    fulltext_excerpt: str | None = None
    charter_problem: str
    charter_criteria: dict[str, Any]


class EvidenceExtractionResponse(BaseModel):
    paper_id: str
    evidence_items: list[ExtractedEvidence]


def _load_prompt_template(prompt_path: str) -> str:
    p = Path(prompt_path)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return (
        "Extract structured evidence from the following paper.\n\n"
        "Research problem: {{ charter_problem }}\n"
        "Paper title: {{ title }}\n"
        "Abstract: {{ abstract }}\n"
        "{% if fulltext_excerpt %}Fulltext excerpt: {{ fulltext_excerpt }}{% endif %}\n\n"
        "Return a JSON array of evidence items. Each item must have:\n"
        "- claim (string), evidence_type "
        "(one of: finding, method, metric, baseline, limitation, dataset),\n"
        '- strength (one of: strong, moderate, weak, anecdotal),\n'
        '- relevance_score (float 0.0-1.0), relevance_rationale (string),\n'
        '- source_section (string or null), source_quote (string or null)\n'
    )


def _render_prompt(template_text: str, request: EvidenceExtractionRequest) -> str:
    try:
        from jinja2 import Template

        tmpl = Template(template_text)
        return tmpl.render(
            charter_problem=request.charter_problem,
            charter_criteria=request.charter_criteria,
            title=request.title,
            abstract=request.abstract or "",
            fulltext_excerpt=request.fulltext_excerpt or "",
        )
    except Exception:
        return template_text


def _parse_evidence_json(text: str, paper_id: str) -> list[ExtractedEvidence]:
    """Best-effort parse of JSON array from LLM output."""
    try:
        raw = parse_json_lenient(text)
        if isinstance(raw, list):
            return [ExtractedEvidence(**item) for item in raw if isinstance(item, dict)]
        return []
    except (ValueError, TypeError) as exc:
        log.warning("evidence_json_parse_failed", paper_id=paper_id, error=str(exc))
        return []


def extract_evidence_batch(
    gateway: ModelGateway,
    requests: list[EvidenceExtractionRequest],
    prompt_path: str = PROMPT_PATH,
    model_role: str = "evidence_extractor",
) -> list[EvidenceExtractionResponse]:
    """Call LLM for each paper to extract structured evidence claims."""
    template_text = _load_prompt_template(prompt_path)
    results: list[EvidenceExtractionResponse] = []

    for req in requests:
        user_content = _render_prompt(template_text, req)
        try:
            response_text = gateway.call_chat_completion(
                role=model_role,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
                max_tokens=1024,
                json_mode=True,
            )
            items = _parse_evidence_json(response_text, req.paper_id)
        except Exception as exc:
            log.warning("evidence_extraction_failed", paper_id=req.paper_id, error=str(exc))
            items = []

        results.append(EvidenceExtractionResponse(paper_id=req.paper_id, evidence_items=items))

    return results
