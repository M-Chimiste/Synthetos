"""Self-critic pre-check: fast LLM pass to catch obvious problems before full verification."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import jinja2

log = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "prompts" / "verification" / "v1"
_JINJA_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=False,
    undefined=jinja2.StrictUndefined,
)


def run_self_critic_precheck(
    *,
    gateway: Any,
    metrics_summary: dict[str, Any],
    baseline_comparison: dict[str, Any],
    spec_metrics: list[dict[str, Any]],
    charter_problem: str,
    experiment_title: str,
) -> dict[str, Any]:
    """Run a fast LLM critic pass to catch obvious problems.

    Returns:
        {passed: bool, flags: [{issue: str, severity: "critical"|"warning"}], rationale: str}
    """
    try:
        template = _JINJA_ENV.get_template("self_critic_precheck.md")
        rendered = template.render(
            charter_problem=charter_problem,
            experiment_title=experiment_title,
            metrics_summary=metrics_summary,
            baseline_comparison=baseline_comparison,
            spec_metrics=spec_metrics,
        )

        prompt_id = "verification/v1/self_critic_precheck"
        response = gateway.call_structured(
            "critic",
            rendered,
            temperature=0.2,
            max_tokens=256,
            prompt_id=prompt_id,
        )

        passed = response.get("passed", True)
        flags = response.get("flags", [])
        rationale = response.get("rationale", "")

        # Validate flag structure
        validated_flags: list[dict[str, str]] = []
        for flag in flags:
            if isinstance(flag, dict) and "issue" in flag:
                validated_flags.append({
                    "issue": str(flag["issue"]),
                    "severity": flag.get("severity", "warning"),
                })

        return {
            "passed": bool(passed),
            "flags": validated_flags,
            "rationale": str(rationale),
        }

    except Exception:
        log.warning("self_critic_precheck_failed", exc_info=True)
        return {"passed": True, "flags": [], "rationale": "skipped"}
