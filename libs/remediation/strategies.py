"""Remediation strategy selection and patch generation.

Each failure class maps to a focused remediation strategy. When the focused
strategy has already been tried for the same failure class, the system
escalates to broad debug (LLM-assisted).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StrategyResult:
    """Output of strategy selection."""

    strategy: str
    strategy_tier: str  # "focused" or "broad"
    remediable: bool  # False means skip to postmortem
    reasoning: str
    overrides: dict[str, Any] = field(default_factory=dict)


# Focused strategies per failure class
_MEMORY_CAP = "64g"
_TIMEOUT_CAP_SECONDS = 14400  # 4 hours


def select_strategy(
    failure_class: str,
    stderr_tail: str,
    current_resource_limits: dict[str, Any] | None,
    prior_strategies: list[str],
    prior_failure_classes: list[str],
) -> StrategyResult:
    """Select a remediation strategy based on failure class and history.

    Args:
        failure_class: The classified failure type.
        stderr_tail: Last ~50 lines of stderr for error analysis.
        current_resource_limits: The failed run's resource limits.
        prior_strategies: Strategies already tried in this lineage.
        prior_failure_classes: Failure classes from prior attempts.

    Returns:
        A StrategyResult with the selected strategy and overrides.
    """
    limits = current_resource_limits or {}

    # Check for tier escalation: same failure class was already tried with focused
    same_class_prior = [
        s for s, fc in zip(prior_strategies, prior_failure_classes, strict=False)
        if fc == failure_class and s != "debug_broad"
    ]
    needs_escalation = len(same_class_prior) > 0

    if failure_class == "metric_parse":
        return StrategyResult(
            strategy="skip",
            strategy_tier="focused",
            remediable=False,
            reasoning="Metric parse failures are not auto-remediable.",
        )

    if failure_class == "dependency":
        if needs_escalation:
            return _broad_debug_result(
                failure_class,
                "Focused dep-install already tried; escalating to broad debug.",
            )
        missing = _extract_missing_modules(stderr_tail)
        if missing:
            return StrategyResult(
                strategy="install_deps",
                strategy_tier="focused",
                remediable=True,
                reasoning=f"Missing modules detected: {', '.join(missing)}.",
                overrides={
                    "build_recipe": {
                        "extra_pip_packages": missing,
                    },
                },
            )
        return _broad_debug_result(
            failure_class,
            "Dependency failure but could not parse missing module names.",
        )

    if failure_class == "oom":
        if needs_escalation:
            return _broad_debug_result(
                failure_class,
                "OOM after memory increase; escalating to broad debug.",
            )
        current_mem = _parse_memory(limits.get("memory", "16g"))
        new_mem = min(current_mem * 2, _parse_memory(_MEMORY_CAP))
        if new_mem <= current_mem:
            return StrategyResult(
                strategy="skip",
                strategy_tier="focused",
                remediable=False,
                reasoning=f"Memory already at cap ({_MEMORY_CAP}).",
            )
        return StrategyResult(
            strategy="increase_memory",
            strategy_tier="focused",
            remediable=True,
            reasoning=f"Doubling memory from {current_mem}GB to {new_mem}GB.",
            overrides={
                "run_resource_limits": {"memory": f"{new_mem}g"},
            },
        )

    if failure_class == "timeout":
        if needs_escalation:
            return _broad_debug_result(
                failure_class,
                "Timeout after increase; escalating to broad debug.",
            )
        current_timeout = int(limits.get("timeout", 3600))
        new_timeout = min(int(current_timeout * 1.5), _TIMEOUT_CAP_SECONDS)
        if new_timeout <= current_timeout:
            return StrategyResult(
                strategy="skip",
                strategy_tier="focused",
                remediable=False,
                reasoning=f"Timeout already at cap ({_TIMEOUT_CAP_SECONDS}s).",
            )
        return StrategyResult(
            strategy="extend_timeout",
            strategy_tier="focused",
            remediable=True,
            reasoning=f"Increasing timeout from {current_timeout}s to {new_timeout}s.",
            overrides={
                "run_resource_limits": {"timeout": new_timeout},
            },
        )

    if failure_class == "invalid_artifact":
        if needs_escalation:
            return _broad_debug_result(
                failure_class,
                "Artifact fix already tried; escalating to broad debug.",
            )
        return _broad_debug_result(
            failure_class,
            "Invalid artifact output; needs LLM analysis to fix code.",
        )

    if failure_class == "runtime":
        # Runtime failures always go to broad debug
        return _broad_debug_result(
            failure_class,
            "Runtime exception; LLM analysis needed for code fix.",
        )

    # Unknown failure class
    return StrategyResult(
        strategy="skip",
        strategy_tier="focused",
        remediable=False,
        reasoning=f"Unknown failure class '{failure_class}'; cannot auto-remediate.",
    )


def _broad_debug_result(failure_class: str, reasoning: str) -> StrategyResult:
    """Create a broad debug strategy result."""
    return StrategyResult(
        strategy="debug_broad",
        strategy_tier="broad",
        remediable=True,
        reasoning=reasoning,
    )


def _extract_missing_modules(stderr_tail: str) -> list[str]:
    """Parse stderr to find missing Python module names."""
    # Match patterns like "ModuleNotFoundError: No module named 'foo'"
    pattern = r"(?:ModuleNotFoundError|ImportError).*?['\"]([^'\"]+)['\"]"
    matches = re.findall(pattern, stderr_tail, re.IGNORECASE)
    # Take the top-level package name (e.g., 'foo.bar' → 'foo')
    modules = list(dict.fromkeys(m.split(".")[0] for m in matches))
    return modules[:10]  # Cap at 10 to avoid pathological cases


def _parse_memory(mem_str: str) -> int:
    """Parse a memory string like '16g' to an integer in GB."""
    mem_str = str(mem_str).strip().lower()
    if mem_str.endswith("g"):
        return int(mem_str[:-1])
    if mem_str.endswith("m"):
        return max(1, int(mem_str[:-1]) // 1024)
    try:
        return int(mem_str)
    except ValueError:
        return 16  # default
