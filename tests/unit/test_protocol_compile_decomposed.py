"""Tests for the decomposed (plan -> code) protocol compile chain."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from libs.protocols.operators import compile as compile_module
from libs.protocols.operators.compile import _compile_specs, _normalize_compiled_spec

BASE_URL = "http://compile.test/v1"
CHAT_URL = f"{BASE_URL}/chat/completions"

_PLAN_JSON = {
    "title": "Cosine vs step LR decay on tiny LM",
    "description": "Two tiny LMs, identical except LR schedule.",
    "baseline": {
        "description": "Step decay schedule, same model and data.",
        "expected_metrics": {"val_loss": 2.9},
    },
    "controls": [{"name": "seed", "value": 42}],
    "metrics": [{"name": "val_loss", "direction": "minimize", "threshold": None}],
    "expected_artifacts": [{"name": "metrics.json", "required": True}],
    "stop_conditions": [{"description": "stop after 200 steps"}],
    "dependencies": [],
    "approach_summary": "Tiny char LM in pure torch on a synthetic corpus.",
}

_CODE_JSON = {
    "entry_point": "run_experiment.py",
    "files": [
        {
            "path": "run_experiment.py",
            "content": (
                "import json\n"
                "json.dump({'val_loss': 1.0}, open('/artifacts/metrics.json','w'))\n"
            ),
        }
    ],
}


def _ok(content: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": "test-model",
        "choices": [{"message": {"content": json.dumps(content)}, "finish_reason": "stop"}],
    }


@pytest.fixture
def routed_to_mock(monkeypatch, tmp_path):
    """Route protocol_drafting + coding roles at a mock endpoint via tmp YAML."""
    config = tmp_path / "models.yaml"
    config.write_text(
        f"""
defaults:
  temperature: 0.3
  max_tokens: 2048
  context_window: 32768
  retry:
    transport_attempts: 1
    timeout_attempts: 1
    validation_attempts: 0
    truncation_attempts: 0
    backoff_base_s: 0.01
    backoff_max_s: 0.01
    jitter_frac: 0.0

roles:
  protocol_drafting:
    provider: local
    model: test-model
    base_url: {BASE_URL}
  coding:
    provider: local
    model: test-model
    base_url: {BASE_URL}

providers:
  local:
    type: openai_compatible
    base_url: {BASE_URL}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("LAB_MODEL_CONFIG", str(config))  # bypasses DB role bindings
    monkeypatch.setattr(
        "libs.adapters.llm.router.get_settings",
        lambda: SimpleNamespace(model_config_path=config),
    )
    # Keep transcript logging from touching a DB in unit tests.
    from libs.core.services import llm_call_service

    settings = llm_call_service.get_settings()
    monkeypatch.setattr(settings, "llm_call_logging_enabled", False)
    return config


_HYPOTHESIS = {
    "title": "Cosine decay helps",
    "statement": "Cosine decay beats step decay on tiny LMs.",
    "rationale": "Smoother schedule avoids loss spikes.",
    "novelty_score": 0.5,
    "feasibility_score": 0.9,
    "impact_score": 0.5,
}


def test_chain_makes_exactly_two_requests_and_reassembles(httpx_mock, routed_to_mock) -> None:
    httpx_mock.add_response(method="POST", url=CHAT_URL, json=_ok(_PLAN_JSON))
    httpx_mock.add_response(method="POST", url=CHAT_URL, json=_ok(_CODE_JSON))

    spec_set, role_cfg = asyncio.run(
        _compile_specs([_HYPOTHESIS], "Improve tiny LM training.", None, "synthetos:latest", None)
    )

    # No third (build) request: the recipe is synthesized deterministically.
    assert len(httpx_mock.get_requests()) == 2
    assert role_cfg.get("model") == "test-model"

    assert len(spec_set.specs) == 1
    spec = spec_set.specs[0]
    assert spec.hypothesis_index == 0
    assert spec.title == _PLAN_JSON["title"]
    # Legacy interchange shapes preserved for every downstream consumer.
    assert spec.baseline == _PLAN_JSON["baseline"]
    assert spec.metrics == _PLAN_JSON["metrics"]
    assert spec.code_plan["entry_point"] == "run_experiment.py"
    assert "run_experiment.py" in spec.code_plan["files"]
    assert spec.code_plan["dependencies"] == []
    assert spec.code_plan["expected_artifacts"] == _PLAN_JSON["expected_artifacts"]

    # The reassembled dict passes the unchanged downstream validation.
    normalized = _normalize_compiled_spec(spec.model_dump(), fallback_base_image="synthetos:latest")
    validation = compile_module.validate_spec(normalized)
    assert validation.valid, validation.errors


def test_plan_prompt_carries_hypothesis_and_code_prompt_carries_plan(
    httpx_mock, routed_to_mock
) -> None:
    httpx_mock.add_response(method="POST", url=CHAT_URL, json=_ok(_PLAN_JSON))
    httpx_mock.add_response(method="POST", url=CHAT_URL, json=_ok(_CODE_JSON))

    asyncio.run(_compile_specs([_HYPOTHESIS], "Improve tiny LM training.", None, None, None))

    requests = httpx_mock.get_requests()
    plan_body = json.loads(requests[0].read())
    code_body = json.loads(requests[1].read())
    plan_user = plan_body["messages"][-1]["content"]
    code_user = code_body["messages"][-1]["content"]

    assert _HYPOTHESIS["statement"] in plan_user
    assert "no code" in plan_body["messages"][0]["content"].lower()
    # Stage 2 receives the plan, not the raw hypothesis.
    assert _PLAN_JSON["approach_summary"] in code_user
    assert "val_loss" in code_user


def test_fixture_expected_artifacts_are_forced_into_plan_and_spec(
    httpx_mock,
    routed_to_mock,
) -> None:
    httpx_mock.add_response(method="POST", url=CHAT_URL, json=_ok(_PLAN_JSON))
    httpx_mock.add_response(method="POST", url=CHAT_URL, json=_ok(_CODE_JSON))

    fixture_expected = {
        "required_artifacts": ["metrics.json", "model_weights.pt", "report.md"],
        "reference_sources": ["https://arxiv.org/html/2506.14202v3"],
    }
    spec_set, _ = asyncio.run(
        _compile_specs(
            [_HYPOTHESIS],
            "Improve tiny LM training.",
            None,
            None,
            None,
            fixture_expected=fixture_expected,
        )
    )

    requests = httpx_mock.get_requests()
    plan_user = json.loads(requests[0].read())["messages"][-1]["content"]
    code_user = json.loads(requests[1].read())["messages"][-1]["content"]
    artifact_names = {artifact["name"] for artifact in spec_set.specs[0].expected_artifacts}

    assert "Pilot fixture expectations" in plan_user
    assert "model_weights.pt" in plan_user
    assert "report.md" in code_user
    assert artifact_names == {"metrics.json", "model_weights.pt", "report.md"}
    assert spec_set.specs[0].code_plan["expected_artifacts"] == spec_set.specs[0].expected_artifacts


def test_failed_card_chain_is_skipped_not_fatal(httpx_mock, routed_to_mock) -> None:
    """First hypothesis compiles; the second's plan call fails validation and
    is skipped. The surviving spec keeps its hypothesis_index."""
    httpx_mock.add_response(method="POST", url=CHAT_URL, json=_ok(_PLAN_JSON))
    httpx_mock.add_response(method="POST", url=CHAT_URL, json=_ok(_CODE_JSON))
    httpx_mock.add_response(method="POST", url=CHAT_URL, json=_ok({"not": "a plan"}))

    second = dict(_HYPOTHESIS, title="Second hypothesis")
    spec_set, _ = asyncio.run(
        _compile_specs([_HYPOTHESIS, second], "Improve tiny LM training.", None, None, None)
    )

    assert len(spec_set.specs) == 1
    assert spec_set.specs[0].hypothesis_index == 0


def test_all_chains_failing_raises(httpx_mock, routed_to_mock) -> None:
    httpx_mock.add_response(method="POST", url=CHAT_URL, json=_ok({"not": "a plan"}))

    with pytest.raises(RuntimeError, match="all hypothesis compile chains failed"):
        asyncio.run(_compile_specs([_HYPOTHESIS], "Improve tiny LM training.", None, None, None))


def test_build_recipe_synthesized_deterministically() -> None:
    """Dependencies beyond the base image get a pip-install Dockerfile with no LLM."""
    spec_data = {
        "title": "t",
        "description": "d",
        "baseline": {"description": "b"},
        "metrics": [{"name": "acc", "direction": "maximize"}],
        "stop_conditions": [{"description": "s"}],
        "code_plan": {
            "entry_point": "run_experiment.py",
            "files": {"run_experiment.py": "print('hi')"},
            "dependencies": ["scikit-learn"],
        },
        "base_image": "python:3.12-slim",
        "build_recipe": None,
    }
    normalized = _normalize_compiled_spec(spec_data, fallback_base_image="python:3.12-slim")
    dockerfile = (normalized.get("build_recipe") or {}).get("dockerfile_content", "")
    assert dockerfile.startswith("FROM python:3.12-slim")
    assert "pip install" in dockerfile
    assert "scikit-learn" in dockerfile


def test_deps_satisfied_by_base_image_leave_recipe_none() -> None:
    spec_data = {
        "title": "t",
        "description": "d",
        "baseline": {"description": "b"},
        "metrics": [{"name": "acc", "direction": "maximize"}],
        "stop_conditions": [{"description": "s"}],
        "code_plan": {
            "entry_point": "run_experiment.py",
            "files": {"run_experiment.py": "import torch"},
            "dependencies": ["torch"],
        },
        "base_image": "synthetos:latest",
        "build_recipe": None,
    }
    normalized = _normalize_compiled_spec(spec_data, fallback_base_image="synthetos:latest")
    assert normalized.get("build_recipe") is None
