"""Helpers for validating API response dicts against Pydantic schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError


def validate_response(data: dict[str, Any], schema: type[BaseModel]) -> None:
    """Validate that a response dict matches the given Pydantic model.

    Raises AssertionError with details if validation fails.
    """
    try:
        schema.model_validate(data)
    except ValidationError as exc:
        raise AssertionError(
            f"Response does not match {schema.__name__}:\n{exc}"
        ) from exc


def validate_list_response(
    data: dict[str, Any],
    list_key: str,
    item_schema: type[BaseModel],
) -> None:
    """Validate a list response: check that `data[list_key]` is a list of valid items."""
    assert list_key in data, f"Response missing key '{list_key}'"
    items = data[list_key]
    assert isinstance(items, list), f"Expected list for '{list_key}', got {type(items)}"
    for i, item in enumerate(items):
        try:
            item_schema.model_validate(item)
        except ValidationError as exc:
            raise AssertionError(
                f"Item {i} in '{list_key}' does not match {item_schema.__name__}:\n{exc}"
            ) from exc
