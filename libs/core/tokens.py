"""Token estimation and prompt context budgeting.

Local models are served with 8-32K context windows; silently overflowing one
truncates the prompt server-side and produces garbage with no error. Operators
assemble large prompts from prioritized sections and trim them to a budget
derived from the role's ``context_window`` config.

Estimation is a chars/4 heuristic rather than a real tokenizer: Qwen-class
tokenizers average ~3.4-4 chars/token including code, and the budget already
carries a safety margin. A tokenizer dependency buys precision this guard
doesn't need.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

_CHARS_PER_TOKEN = 4
_TRUNCATION_MARKER = "\n[...truncated]"

# Conservative fallback when a role config carries no context_window (e.g. a
# stale DB role binding). Small enough to be safe on any local model.
DEFAULT_CONTEXT_WINDOW = 8192
_DEFAULT_RESERVE_OUTPUT = 4096


def estimate_tokens(text: str) -> int:
    """Heuristic token estimate (~chars/4). Pair with a safety margin."""
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


@dataclass(frozen=True)
class ContextSection:
    """One prioritized block of prompt context.

    priority 0 sections are never dropped or truncated; higher numbers are
    sacrificed first. Non-shrinkable sections are kept whole or dropped whole.
    """

    name: str
    content: str
    priority: int
    shrinkable: bool = True
    min_chars: int = 0


@dataclass
class BudgetReport:
    """Result of trimming sections to a token budget."""

    text: str
    estimated_tokens: int
    dropped: list[str] = field(default_factory=list)
    truncated: list[str] = field(default_factory=list)

    @property
    def trimmed(self) -> bool:
        return bool(self.dropped or self.truncated)


def _truncate_at_line(content: str, target_chars: int) -> str:
    """Cut content to at most target_chars, preferring a line boundary."""
    if target_chars <= 0:
        return ""
    cut = content[:target_chars]
    newline = cut.rfind("\n")
    # Only honor the line boundary if it doesn't sacrifice most of the budget.
    if newline > target_chars // 2:
        cut = cut[:newline]
    return cut.rstrip()


def trim_to_budget(
    sections: Sequence[ContextSection],
    budget_tokens: int,
    *,
    joiner: str = "\n\n",
) -> BudgetReport:
    """Assemble sections into one text, trimming to fit the token budget.

    Sections are emitted in the given order. When over budget, sections are
    sacrificed in descending priority number (ties: later sections first):
    shrinkable sections are truncated at a line boundary down to ``min_chars``
    then dropped; non-shrinkable sections are dropped whole. Priority 0
    sections are never touched.
    """
    kept: dict[int, str] = {i: s.content for i, s in enumerate(sections) if s.content}
    dropped: list[str] = []
    truncated: list[str] = []

    def assemble() -> str:
        return joiner.join(kept[i] for i in sorted(kept))

    def total_tokens() -> int:
        return estimate_tokens(assemble())

    sacrifice_order = sorted(
        (i for i in kept if sections[i].priority > 0),
        key=lambda i: (sections[i].priority, i),
        reverse=True,
    )

    for i in sacrifice_order:
        excess = total_tokens() - budget_tokens
        if excess <= 0:
            break
        section = sections[i]
        if section.shrinkable:
            excess_chars = excess * _CHARS_PER_TOKEN
            target = len(kept[i]) - excess_chars - len(_TRUNCATION_MARKER)
            if target >= max(section.min_chars, 1):
                kept[i] = _truncate_at_line(kept[i], target) + _TRUNCATION_MARKER
                truncated.append(section.name)
                continue
        del kept[i]
        dropped.append(section.name)

    text = assemble()
    return BudgetReport(
        text=text,
        estimated_tokens=estimate_tokens(text),
        dropped=dropped,
        truncated=truncated,
    )


def prompt_budget(
    role_cfg: Mapping[str, Any],
    *,
    system_text: str = "",
    reserve_output: int | None = None,
    safety_fraction: float = 0.15,
) -> int:
    """Token budget available for user-message context under a role config.

    ``context_window`` must reflect the *serving* window (e.g. llama.cpp -c),
    not the model-card maximum. Reserves space for the system prompt, the
    expected output (defaults to the role's max_tokens), and a safety margin
    for estimation error.
    """
    window = int(role_cfg.get("context_window") or DEFAULT_CONTEXT_WINDOW)
    reserve = (
        reserve_output
        if reserve_output is not None
        else int(role_cfg.get("max_tokens") or _DEFAULT_RESERVE_OUTPUT)
    )
    budget = window - reserve - estimate_tokens(system_text) - int(window * safety_fraction)
    return max(0, budget)
