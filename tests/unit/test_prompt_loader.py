"""Tests for the file-based prompt template loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from libs.prompts import (
    PromptNotFoundError,
    PromptRenderError,
    clear_prompt_cache,
    list_prompts,
    load_prompt,
)
from libs.prompts import loader as loader_module

_TEMPLATE = """\
---
id: testing.sample
version: {version}
description: Test prompt.
variables: [name]
optional_variables: [flavor]
---
Hello {{{{ name }}}}.{{% if flavor is defined %}} Flavor: {{{{ flavor }}}}.{{% endif %}}

Output example (illustrative content — do not copy):
```json
{{"greeting": "hi"}}
```
"""


@pytest.fixture
def prompt_root(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(loader_module, "prompts_root", lambda: tmp_path)
    clear_prompt_cache()
    yield tmp_path
    clear_prompt_cache()


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_load_and_render(prompt_root: Path) -> None:
    _write(prompt_root, "testing/sample/v1.md", _TEMPLATE.format(version=1))
    template = load_prompt("testing.sample")
    assert template.manifest.id == "testing.sample"
    assert template.manifest.version == 1

    rendered = template.render(name="world")
    assert "Hello world." in rendered

    rendered_with_flavor = template.render(name="world", flavor="mint")
    assert "Flavor: mint." in rendered_with_flavor


def test_missing_required_variable_fails_fast(prompt_root: Path) -> None:
    _write(prompt_root, "testing/sample/v1.md", _TEMPLATE.format(version=1))
    with pytest.raises(PromptRenderError, match="missing required variables"):
        load_prompt("testing.sample").render()


def test_highest_version_wins(prompt_root: Path) -> None:
    _write(prompt_root, "testing/sample/v1.md", _TEMPLATE.format(version=1))
    _write(prompt_root, "testing/sample/v3.md", _TEMPLATE.format(version=3))
    assert load_prompt("testing.sample").manifest.version == 3
    assert load_prompt("testing.sample", version=1).manifest.version == 1


def test_model_variant_preferred_with_fallback(prompt_root: Path) -> None:
    _write(prompt_root, "testing/sample/v1.md", _TEMPLATE.format(version=1))
    variant = _TEMPLATE.format(version=1).replace("Hello", "Variant hello")
    _write(prompt_root, "testing/sample/v1.qwen3-6-35b.md", variant)

    chosen = load_prompt("testing.sample", model="Qwen3.6 35B")
    assert "Variant hello" in chosen.body
    # Model without a variant file falls back to the base template.
    base = load_prompt("testing.sample", model="other-model")
    assert "Variant hello" not in base.body


def test_example_json_extraction(prompt_root: Path) -> None:
    _write(prompt_root, "testing/sample/v1.md", _TEMPLATE.format(version=1))
    example = load_prompt("testing.sample").example_json()
    assert example == '{"greeting": "hi"}'


def test_unknown_prompt_raises(prompt_root: Path) -> None:
    with pytest.raises(PromptNotFoundError):
        load_prompt("testing.never_written")
    with pytest.raises(PromptNotFoundError):
        load_prompt("not-a-dotted-id".replace("-", ""))


def test_list_prompts(prompt_root: Path) -> None:
    _write(prompt_root, "testing/sample/v1.md", _TEMPLATE.format(version=1))
    _write(prompt_root, "testing/other/v1.md", _TEMPLATE.format(version=1))
    manifests = list_prompts(prompt_root)
    assert len(manifests) == 2


def test_cache_returns_same_object(prompt_root: Path) -> None:
    _write(prompt_root, "testing/sample/v1.md", _TEMPLATE.format(version=1))
    assert load_prompt("testing.sample") is load_prompt("testing.sample")
