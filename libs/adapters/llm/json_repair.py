"""JSON repair helpers for local-model structured output.

Small models wrap JSON in markdown fences, emit raw LaTeX backslashes inside
strings, and truncate mid-object when they hit max_tokens. Light repair
(fences + backslashes) is safe to apply always; full repair (closing
unterminated containers) silently produces incomplete data, so the
reliability layer applies it only after truncation re-calls are exhausted.
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

_VALID_SIMPLE_ESCAPES = {'"', "\\", "/", "b", "f", "n", "r", "t"}


def strip_code_fences(content: str) -> str:
    """Remove a surrounding markdown code fence (```json ... ```)."""
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [ln for ln in lines[1:] if ln.strip() != "```"]
        cleaned = "\n".join(lines)
    return cleaned


def extract_json_payload(content: str) -> str:
    """Extract the most likely JSON object/array from a completion."""
    cleaned = strip_code_fences(content)
    start_positions = [idx for idx in (cleaned.find("{"), cleaned.find("[")) if idx != -1]
    if not start_positions:
        return cleaned
    start = min(start_positions)
    extracted = extract_json_span(cleaned[start:])
    return extracted if extracted else cleaned[start:]


def extract_json_span(text: str) -> str | None:
    """Return a complete or clearly truncated JSON object/array span."""
    stack: list[str] = []
    in_string = False
    escape = False
    for idx, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if not stack:
                return None
            opening = stack.pop()
            if (opening, char) not in {("{", "}"), ("[", "]")}:
                return None
            if not stack:
                return text[: idx + 1]
    if stack:
        return text
    return None


def repair_truncated_json(cleaned: str) -> str:
    """Close unterminated containers when generation ended mid-object."""
    stack: list[str] = []
    in_string = False
    escape = False
    for char in cleaned:
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]" and stack and (stack[-1], char) in {("{", "}"), ("[", "]")}:
            stack.pop()
    if in_string:
        cleaned += '"'
    closers = {"{": "}", "[": "]"}
    return cleaned + "".join(closers[char] for char in reversed(stack))


def _has_hex_escape(text: str, start: int) -> bool:
    if start + 4 > len(text):
        return False
    return all(char in "0123456789abcdefABCDEF" for char in text[start : start + 4])


def escape_invalid_json_backslashes(cleaned: str) -> str:
    """Escape raw LaTeX-style backslashes that local models emit in JSON strings."""
    out: list[str] = []
    in_string = False
    escape = False
    idx = 0
    while idx < len(cleaned):
        char = cleaned[idx]
        if in_string:
            if escape:
                if char in _VALID_SIMPLE_ESCAPES or (
                    char == "u" and _has_hex_escape(cleaned, idx + 1)
                ):
                    out.append(char)
                else:
                    out.append("\\")
                    out.append(char)
                escape = False
            elif char == "\\":
                out.append(char)
                escape = True
            elif char == '"':
                out.append(char)
                in_string = False
            else:
                out.append(char)
            idx += 1
            continue

        out.append(char)
        if char == '"':
            in_string = True
        idx += 1

    if escape:
        out.append("\\")
    return "".join(out)


def validate_with_light_repair[T: BaseModel](response_model: type[T], content: str) -> T:
    """Validate after cheap, semantically safe repairs (fences, backslashes).

    Raises the original :class:`pydantic.ValidationError` if no candidate
    validates.
    """
    cleaned = extract_json_payload(content)
    try:
        return response_model.model_validate_json(cleaned)
    except ValidationError as exc:
        escaped = escape_invalid_json_backslashes(cleaned)
        if escaped != cleaned:
            try:
                return response_model.model_validate_json(escaped)
            except ValidationError:
                pass
        raise exc


def validate_with_full_repair[T: BaseModel](response_model: type[T], content: str) -> T:
    """Validate with truncation repair (closing unterminated containers).

    Last resort: a "repaired" object is structurally valid but may be
    semantically incomplete. Raises the original validation error if no
    candidate validates.
    """
    cleaned = extract_json_payload(content)
    try:
        return response_model.model_validate_json(cleaned)
    except ValidationError as exc:
        escaped = escape_invalid_json_backslashes(cleaned)
        candidates = [
            escaped,
            repair_truncated_json(cleaned),
            repair_truncated_json(escaped),
        ]
        for candidate in candidates:
            if candidate == cleaned:
                continue
            try:
                return response_model.model_validate_json(candidate)
            except ValidationError:
                pass
        raise exc
