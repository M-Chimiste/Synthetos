"""Protocol validation for executable experiment specs."""

from __future__ import annotations

from libs.core.container_images import BLACKWELL_PYTORCH_IMAGE
from libs.protocols.validation import validate_spec


def _valid_spec() -> dict:
    return {
        "baseline": {"description": "baseline"},
        "metrics": [{"name": "score", "direction": "maximize"}],
        "stop_conditions": [{"type": "timeout"}],
        "code_plan": {
            "entry_point": "run_experiment.py",
            "files": {"run_experiment.py": "print('ok')"},
        },
    }


def test_dependencies_require_agent_authored_dockerfile() -> None:
    spec = _valid_spec()
    spec["code_plan"]["dependencies"] = ["numpy"]

    result = validate_spec(spec)

    assert result.valid is False
    assert "code_plan dependencies require build_recipe.dockerfile_content" in result.errors


def test_build_recipe_dockerfile_requires_from_line() -> None:
    spec = _valid_spec()
    spec["build_recipe"] = {"dockerfile_content": "RUN pip install numpy\n"}

    result = validate_spec(spec)

    assert result.valid is False
    assert "build_recipe.dockerfile_content must contain a FROM line" in result.errors


def test_valid_agent_authored_dockerfile_passes_validation() -> None:
    spec = _valid_spec()
    spec["code_plan"]["dependencies"] = ["numpy"]
    spec["build_recipe"] = {
        "dockerfile_content": "FROM python:3.12-slim\nRUN pip install numpy\n"
    }

    result = validate_spec(spec)

    assert result.valid is True


def test_pytorch_base_satisfies_torch_numpy_dependencies() -> None:
    spec = _valid_spec()
    spec["base_image"] = BLACKWELL_PYTORCH_IMAGE
    spec["code_plan"]["dependencies"] = ["torch", "numpy"]

    result = validate_spec(spec)

    assert result.valid is True
