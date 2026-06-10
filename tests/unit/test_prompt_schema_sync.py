"""Prompt <-> pydantic schema sync guard.

Every shipped prompt that declares a ``response_schema`` must carry a JSON
output example that validates against that model. This fails CI the moment a
prompt example and its pydantic schema diverge -- the structural mitigation
for prompt/schema drift now that prompts live in files.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from libs.prompts import list_prompts, load_prompt

_REPO_PROMPTS = Path(__file__).resolve().parents[2] / "prompts"

_MANIFESTS = list_prompts(_REPO_PROMPTS)


def _resolve_schema(dotted: str) -> type[BaseModel]:
    module_path, _, attr = dotted.partition(":")
    module = importlib.import_module(module_path)
    model = getattr(module, attr)
    assert issubclass(model, BaseModel)
    return model


def test_prompts_directory_is_populated() -> None:
    assert len(_MANIFESTS) >= 8, "expected the shipped prompt templates to be discoverable"


@pytest.mark.parametrize("manifest", _MANIFESTS, ids=[m.id for m in _MANIFESTS])
def test_prompt_id_matches_path_and_loads(manifest, monkeypatch) -> None:
    from libs.prompts import clear_prompt_cache
    from libs.prompts import loader as loader_module

    monkeypatch.setattr(loader_module, "prompts_root", lambda: _REPO_PROMPTS)
    clear_prompt_cache()
    try:
        template = load_prompt(manifest.id, version=manifest.version)
        assert template.manifest.id == manifest.id
        # Every declared required variable must appear in the body.
        for variable in template.manifest.variables:
            assert re.search(r"\{\{\s*" + re.escape(variable) + r"[\s|}]", template.body), (
                f"variable '{variable}' not referenced in {manifest.id}"
            )
    finally:
        clear_prompt_cache()


@pytest.mark.parametrize(
    "manifest",
    [m for m in _MANIFESTS if m.response_schema],
    ids=[m.id for m in _MANIFESTS if m.response_schema],
)
def test_prompt_example_validates_against_schema(manifest, monkeypatch) -> None:
    from libs.prompts import clear_prompt_cache
    from libs.prompts import loader as loader_module

    monkeypatch.setattr(loader_module, "prompts_root", lambda: _REPO_PROMPTS)
    clear_prompt_cache()
    try:
        template = load_prompt(manifest.id, version=manifest.version)
        example = template.example_json()
        assert example is not None, (
            f"prompt '{manifest.id}' declares response_schema but has no ```json example"
        )
        model = _resolve_schema(manifest.response_schema)
        model.model_validate_json(example)  # raises on drift
    finally:
        clear_prompt_cache()
