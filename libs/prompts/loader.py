"""File-based prompt template discovery and loading.

``prompt_id = "<domain>.<name>"`` maps to ``prompts/<domain>/<name>/v<N>.md``.
The highest version wins unless one is pinned. A per-model variant
(``v<N>.<model-slug>.md``) is preferred when present -- the extension point
for tuning prompts per local model without code changes; no variant files
ship by default.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Any

import frontmatter

from libs.core.config import get_settings
from libs.prompts.schema import PromptManifest, PromptTemplate

_VERSION_FILE_RE = re.compile(r"^v(\d+)\.md$")


class PromptNotFoundError(Exception):
    """Raised when a prompt id/version cannot be resolved to a file."""


def prompts_root() -> Path:
    """Root directory for prompt templates (LAB_PROMPTS_ROOT)."""
    return get_settings().prompts_root


def _slug(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")


def _prompt_dir(root: Path, prompt_id: str) -> Path:
    domain, _, name = prompt_id.partition(".")
    if not domain or not name:
        raise PromptNotFoundError(f"Invalid prompt id '{prompt_id}' (expected '<domain>.<name>')")
    return root / domain / name


def _resolve_version(directory: Path, version: int | None) -> int:
    if version is not None:
        return version
    versions = [
        int(m.group(1)) for p in directory.glob("v*.md") if (m := _VERSION_FILE_RE.match(p.name))
    ]
    if not versions:
        raise PromptNotFoundError(f"No prompt versions found in {directory}")
    return max(versions)


def _parse_file(path: Path) -> PromptTemplate:
    post = frontmatter.load(str(path))
    metadata: dict[str, Any] = dict(post.metadata)
    manifest = PromptManifest(**metadata)
    return PromptTemplate(manifest=manifest, body=post.content, path=path)


@cache
def _load(root_str: str, prompt_id: str, version: int | None, model: str | None) -> PromptTemplate:
    root = Path(root_str)
    directory = _prompt_dir(root, prompt_id)
    if not directory.is_dir():
        raise PromptNotFoundError(f"No prompt directory for '{prompt_id}' under {root}")
    resolved = _resolve_version(directory, version)

    if model:
        variant = directory / f"v{resolved}.{_slug(model)}.md"
        if variant.exists():
            return _parse_file(variant)

    base = directory / f"v{resolved}.md"
    if not base.exists():
        raise PromptNotFoundError(f"Prompt file not found: {base}")
    return _parse_file(base)


def load_prompt(
    prompt_id: str,
    *,
    version: int | None = None,
    model: str | None = None,
) -> PromptTemplate:
    """Load a prompt template (cached). Highest version by default."""
    return _load(str(prompts_root()), prompt_id, version, model)


def render_prompt(
    prompt_id: str,
    *,
    version: int | None = None,
    model: str | None = None,
    **variables: Any,
) -> str:
    """Load and render a prompt template in one call."""
    return load_prompt(prompt_id, version=version, model=model).render(**variables)


def list_prompts(root: Path | None = None) -> list[PromptManifest]:
    """Enumerate all prompt manifests under the prompts root (for tests/CLI)."""
    base = root or prompts_root()
    manifests: list[PromptManifest] = []
    if not base.is_dir():
        return manifests
    for path in sorted(base.glob("*/*/v*.md")):
        manifests.append(_parse_file(path).manifest)
    return manifests


def clear_prompt_cache() -> None:
    """Test seam: drop the lru cache after changing prompts_root."""
    _load.cache_clear()
