"""SDK exception types."""

from __future__ import annotations


class SynthetoAPIError(Exception):
    """Base exception for API errors."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class SynthetoAuthError(SynthetoAPIError):
    """Authentication or authorization failure (401/403)."""

    def __init__(self, detail: str = "Authentication failed") -> None:
        super().__init__(401, detail)


class SynthetoNotFoundError(SynthetoAPIError):
    """Resource not found (404)."""

    def __init__(self, detail: str = "Not found") -> None:
        super().__init__(404, detail)


class SynthetoValidationError(SynthetoAPIError):
    """Request validation error (422)."""

    def __init__(self, detail: str = "Validation error") -> None:
        super().__init__(422, detail)
