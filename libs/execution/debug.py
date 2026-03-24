"""LLM-assisted failure diagnosis and fix generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jinja2
import structlog
from pydantic import BaseModel, Field

from libs.adapters.llm.gateway import ModelGateway
from libs.core.policy import RemediationPolicyConfig

log = structlog.get_logger()

FOCUSED_PROMPT_PATH = "prompts/remediation/v1/focused_fix.md"
FULL_DEBUG_PROMPT_PATH = "prompts/remediation/v1/full_debug.md"

_FOCUSED_FALLBACK = (
    "Diagnose this {{ failure_classification }} failure.\n"
    "Stderr: {{ stderr_excerpt }}\n"
    "Respond with JSON: {diagnosis, fix_type, fix_description, code_patch, "
    "dependency_adds, env_changes, spec_mutations}"
)
_FULL_DEBUG_FALLBACK = _FOCUSED_FALLBACK


class RemediationResponse(BaseModel):
    """Structured response from the LLM debugger."""

    diagnosis: str
    fix_type: str  # code_patch, dependency_add, env_change, spec_mutation
    fix_description: str
    code_patch: str | None = None
    dependency_adds: list[str] = Field(default_factory=list)
    env_changes: dict[str, str] = Field(default_factory=dict)
    run_mutations: dict[str, Any] = Field(default_factory=dict)
    spec_mutations: dict[str, Any] = Field(default_factory=dict)


def determine_prompt_mode(
    failure_classification: str,
    attempt_number: int,
    policy: RemediationPolicyConfig,
) -> str:
    """Return 'focused' or 'full_debug' based on failure class and attempt history."""
    if failure_classification in policy.full_debug_failure_classes:
        return "full_debug"
    if failure_classification in policy.focused_failure_classes:
        if attempt_number > policy.escalate_to_full_debug_after:
            return "full_debug"
        return "focused"
    return "full_debug"


def _load_template(path: str, fallback: str) -> str:
    p = Path(path)
    if p.is_file():
        return p.read_text(encoding="utf-8")
    log.warning("remediation_template_not_found", path=path, using="fallback")
    return fallback


def build_remediation_prompt(
    *,
    mode: str,
    charter_problem: str,
    experiment_title: str,
    experiment_objective: str,
    method_description: str,
    expected_outputs: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    failure_classification: str,
    exit_code: int | None,
    last_error: str,
    stderr_excerpt: str,
    stdout_excerpt: str,
    generated_code: str,
    artifact_manifest: dict[str, Any],
    resource_snapshot: dict[str, Any],
    verification_summary: str | None,
    prior_attempts: list[dict[str, Any]],
    attempt_number: int,
    run_status: str,
    attempt_count: int,
    policy: RemediationPolicyConfig,
    canonical_fix_hints: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Render the appropriate Jinja2 prompt template.

    Returns ``(rendered_prompt, prompt_id)``.
    """
    if mode == "focused":
        template_text = _load_template(FOCUSED_PROMPT_PATH, _FOCUSED_FALLBACK)
        prompt_id = FOCUSED_PROMPT_PATH
    else:
        template_text = _load_template(FULL_DEBUG_PROMPT_PATH, _FULL_DEBUG_FALLBACK)
        prompt_id = FULL_DEBUG_PROMPT_PATH

    env = jinja2.Environment(autoescape=False, undefined=jinja2.StrictUndefined)
    tmpl = env.from_string(template_text)
    rendered = tmpl.render(
        charter_problem=charter_problem,
        experiment_title=experiment_title,
        experiment_objective=experiment_objective,
        method_description=method_description,
        expected_outputs=expected_outputs,
        metrics=metrics,
        failure_classification=failure_classification,
        exit_code=exit_code,
        last_error=last_error or "",
        stderr_excerpt=stderr_excerpt,
        stdout_excerpt=stdout_excerpt,
        generated_code=generated_code,
        artifact_manifest=json.dumps(artifact_manifest, indent=2) if artifact_manifest else "{}",
        resource_snapshot=json.dumps(resource_snapshot, indent=2) if resource_snapshot else "{}",
        verification_summary=verification_summary or "",
        prior_attempts=prior_attempts,
        attempt_number=attempt_number,
        run_status=run_status,
        attempt_count=attempt_count,
        max_stderr_chars=policy.max_stderr_chars,
        canonical_fix_hints=canonical_fix_hints or [],
    )
    return rendered, prompt_id


def call_debugger(
    gateway: ModelGateway,
    rendered_prompt: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> RemediationResponse:
    """Call the LLM debugger route and parse the structured response."""
    raw = gateway.call_structured(
        "debugger",
        [{"role": "user", "content": rendered_prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    return RemediationResponse.model_validate(raw)
