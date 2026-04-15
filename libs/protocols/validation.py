"""Experiment spec completeness validation.

A spec must have enough definition to be safely executed.  Under-specified
specs are rejected before they reach the execution layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    """Result of spec completeness validation."""

    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_spec(spec_data: dict) -> ValidationResult:
    """Validate that a compiled experiment spec is complete enough to execute.

    Checks:
    - baseline must be defined with a description
    - at least one metric with name and direction
    - at least one stop condition
    - code_plan must have entry_point and at least one file
    """
    result = ValidationResult()

    # Baseline
    baseline = spec_data.get("baseline")
    if not baseline or not baseline.get("description"):
        result.errors.append("baseline must be defined with a description")

    # Metrics
    metrics = spec_data.get("metrics", [])
    if not metrics:
        result.errors.append("at least one metric must be defined")
    for i, m in enumerate(metrics):
        if not m.get("name"):
            result.errors.append(f"metric[{i}] missing 'name'")
        if m.get("direction") not in ("maximize", "minimize"):
            result.errors.append(f"metric[{i}] 'direction' must be 'maximize' or 'minimize'")

    # Stop conditions
    stop_conditions = spec_data.get("stop_conditions", [])
    if not stop_conditions:
        result.warnings.append("no stop conditions defined; run will rely on timeout")

    # Code plan
    code_plan = spec_data.get("code_plan")
    if code_plan:
        if not code_plan.get("entry_point"):
            result.errors.append("code_plan missing 'entry_point'")
        files = code_plan.get("files", {})
        if not files:
            result.errors.append("code_plan has no files")
    else:
        result.errors.append("code_plan is required")

    result.valid = len(result.errors) == 0
    return result
