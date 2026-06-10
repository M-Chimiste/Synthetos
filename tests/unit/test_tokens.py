"""Tests for token estimation and prompt context budgeting."""

from __future__ import annotations

from libs.core.tokens import (
    DEFAULT_CONTEXT_WINDOW,
    ContextSection,
    estimate_tokens,
    prompt_budget,
    trim_to_budget,
)


def test_estimate_tokens_basics() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("ab") == 1  # floor of 1 for non-empty text
    assert estimate_tokens("a" * 400) == 100
    assert estimate_tokens("a" * 100) < estimate_tokens("a" * 1000)


def test_trim_within_budget_keeps_everything() -> None:
    sections = [
        ContextSection("problem", "the problem statement", priority=0),
        ContextSection("evidence", "some evidence", priority=1),
    ]
    report = trim_to_budget(sections, budget_tokens=1000)
    assert not report.trimmed
    assert "the problem statement" in report.text
    assert "some evidence" in report.text
    # Original order preserved.
    assert report.text.index("problem statement") < report.text.index("some evidence")


def test_priority_zero_never_dropped_or_truncated() -> None:
    core = "core content\n" * 100
    filler = "filler line\n" * 500
    sections = [
        ContextSection("core", core, priority=0),
        ContextSection("filler", filler, priority=2),
    ]
    # Budget fits the core but nowhere near the filler.
    report = trim_to_budget(sections, budget_tokens=estimate_tokens(core) + 20)
    assert core.rstrip() in report.text or core in report.text
    assert "core" not in report.dropped
    assert "core" not in report.truncated
    assert report.estimated_tokens <= estimate_tokens(core) + 20


def test_shrinkable_truncated_at_line_boundary_with_marker() -> None:
    lines = "\n".join(f"line {i}: some moderately long content here" for i in range(200))
    sections = [
        ContextSection("head", "must stay", priority=0),
        ContextSection("body", lines, priority=1, shrinkable=True),
    ]
    budget = estimate_tokens(lines) // 2
    report = trim_to_budget(sections, budget_tokens=budget)
    assert "body" in report.truncated
    assert "[...truncated]" in report.text
    # Cut lands on a line boundary: the char before the marker ends a full line.
    before_marker = report.text.split("\n[...truncated]")[0]
    assert before_marker.endswith("here")
    assert report.estimated_tokens <= budget


def test_non_shrinkable_dropped_whole() -> None:
    sections = [
        ContextSection("keep", "important", priority=0),
        ContextSection("blob", "x" * 4000, priority=1, shrinkable=False),
    ]
    report = trim_to_budget(sections, budget_tokens=100)
    assert report.dropped == ["blob"]
    assert "xxxx" not in report.text


def test_shrinkable_below_min_chars_dropped() -> None:
    sections = [
        ContextSection("keep", "important", priority=0),
        ContextSection("body", "y" * 4000, priority=1, shrinkable=True, min_chars=3000),
    ]
    # Budget so small the section can't shrink to min_chars -> dropped.
    report = trim_to_budget(sections, budget_tokens=50)
    assert report.dropped == ["body"]


def test_higher_priority_number_sacrificed_first() -> None:
    sections = [
        ContextSection("p1", "a" * 2000, priority=1, shrinkable=False),
        ContextSection("p3", "b" * 2000, priority=3, shrinkable=False),
        ContextSection("p2", "c" * 2000, priority=2, shrinkable=False),
    ]
    # Budget fits exactly two sections (plus joiner slack).
    report = trim_to_budget(sections, budget_tokens=1100)
    assert report.dropped[0] == "p3"
    assert "p1" not in report.dropped


def test_prompt_budget_arithmetic() -> None:
    cfg = {"context_window": 32768, "max_tokens": 4096}
    budget = prompt_budget(cfg, system_text="s" * 4000, safety_fraction=0.15)
    expected = 32768 - 4096 - 1000 - int(32768 * 0.15)
    assert budget == expected


def test_prompt_budget_defaults_conservative_window() -> None:
    budget = prompt_budget({})
    assert budget == DEFAULT_CONTEXT_WINDOW - 4096 - int(DEFAULT_CONTEXT_WINDOW * 0.15)
    # Reserve override wins over max_tokens.
    assert prompt_budget({"max_tokens": 100}, reserve_output=200) == (
        DEFAULT_CONTEXT_WINDOW - 200 - int(DEFAULT_CONTEXT_WINDOW * 0.15)
    )


def test_prompt_budget_never_negative() -> None:
    assert prompt_budget({"context_window": 1024, "max_tokens": 4096}) == 0
