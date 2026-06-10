"""Operator input/output contracts.

Operators are typed units of work that read from shared state,
execute logic (possibly involving LLM calls), and return a result
containing state mutations, events, and artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from libs.core.errors import ErrorClass


@dataclass(frozen=True)
class OperatorInput:
    """Input context provided to an operator."""

    cycle_id: UUID
    charter_id: UUID
    job_id: UUID
    job_type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OperatorFailure:
    """Structured detail about an operator exception, used for job retry decisions."""

    error_class: ErrorClass
    exc_type: str | None = None
    traceback: str | None = None


@dataclass
class OperatorResult:
    """Output returned by an operator after execution."""

    # Events to emit (event_type -> payload pairs)
    events: list[dict[str, Any]] = field(default_factory=list)

    # State mutations to apply (e.g., cycle status change)
    state_patch: dict[str, Any] = field(default_factory=dict)

    # Artifact paths created
    artifacts: list[str] = field(default_factory=list)

    # Human-readable summary of what the operator did
    summary: str = ""

    # Whether the operator completed successfully
    success: bool = True

    # Error message if not successful
    error: str | None = None

    # Structured failure detail (set by the executor when an operator raises).
    # None for operators that return success=False without raising; the worker
    # treats those as permanent failures.
    failure: OperatorFailure | None = None

    def add_event(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self.events.append({"event_type": event_type, "payload": payload or {}})
