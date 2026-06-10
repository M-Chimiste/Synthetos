"""Prompt template manifest and rendering.

Prompt files live under ``prompts/<domain>/<name>/v<N>.md``: YAML frontmatter
(manifest) plus a markdown body that is the system-message template. Bodies
are jinja2 templates restricted by convention to variable substitution and
``{% if %}`` blocks -- no loops or macros.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined
from jinja2 import TemplateError as JinjaTemplateError
from pydantic import BaseModel, Field

_JSON_FENCE_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)

_env = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)


class PromptRenderError(Exception):
    """Raised when a template cannot be rendered (missing/extra variables)."""


class PromptManifest(BaseModel):
    """Frontmatter of a prompt template file."""

    id: str
    version: int
    description: str = ""
    # Informational ModelRole hint; not enforced at render time.
    role: str | None = None
    variables: list[str] = Field(default_factory=list)
    optional_variables: list[str] = Field(default_factory=list)
    # Dotted "module:Attr" path to the pydantic response model. Used only by
    # the schema-sync test (never imported by the loader at runtime).
    response_schema: str | None = None


class PromptTemplate(BaseModel):
    """A parsed prompt template: manifest + body + source path."""

    model_config = {"arbitrary_types_allowed": True}

    manifest: PromptManifest
    body: str
    path: Path

    def render(self, **variables: Any) -> str:
        """Render the body with StrictUndefined (missing variables fail fast)."""
        missing = [v for v in self.manifest.variables if v not in variables]
        if missing:
            raise PromptRenderError(
                f"Prompt '{self.manifest.id}' v{self.manifest.version} missing "
                f"required variables: {missing}"
            )
        try:
            return _env.from_string(self.body).render(**variables)
        except JinjaTemplateError as exc:
            raise PromptRenderError(
                f"Prompt '{self.manifest.id}' v{self.manifest.version} failed to render: {exc}"
            ) from exc

    def example_json(self) -> str | None:
        """Return the last ```json fenced block (the output example), if any."""
        matches = _JSON_FENCE_RE.findall(self.body)
        return matches[-1] if matches else None
