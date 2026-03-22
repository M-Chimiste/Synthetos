"""Shared JSON extraction and repair utilities for LLM responses."""

from __future__ import annotations

import json
import re

import structlog
from json_repair import repair_json

log = structlog.get_logger(__name__)

# Pattern to strip markdown code fences: ```json ... ``` or ``` ... ```
_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


def extract_json_from_text(text: str) -> str | None:
    """Strip markdown fences and surrounding prose, return raw JSON substring.

    Looks for the outermost ``{ }`` or ``[ ]`` pair after stripping fences.
    Returns *None* if no JSON-like structure is found.
    """
    # Strip markdown code fences first
    fence_match = _FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()

    # Try to find outermost JSON structure — whichever bracket appears first
    obj_start = text.find("{")
    arr_start = text.find("[")

    # Determine which appears first (prefer the earlier one)
    candidates: list[tuple[int, str, str]] = []
    if obj_start >= 0:
        obj_end = text.rfind("}")
        if obj_end > obj_start:
            candidates.append((obj_start, "{", "}"))
    if arr_start >= 0:
        arr_end = text.rfind("]")
        if arr_end > arr_start:
            candidates.append((arr_start, "[", "]"))

    if not candidates:
        return None

    # Pick the one that starts earliest (covers the most outer structure)
    candidates.sort(key=lambda c: c[0])
    start_pos, open_char, close_char = candidates[0]
    end_pos = text.rfind(close_char)
    return text[start_pos : end_pos + 1]


def parse_json_lenient(text: str) -> dict | list:
    """Parse JSON from LLM output with multi-level fallback.

    Strategy:
    1. ``json.loads()`` on raw text (fast path for clean JSON)
    2. Extract JSON from prose/fences, then ``json.loads()``
    3. ``json_repair.repair_json()`` to fix common LLM errors
       (trailing commas, single quotes, unquoted keys, etc.)
    4. Raise ``ValueError`` with details if all attempts fail

    Returns the parsed dict or list.
    """
    text = text.strip()
    if not text:
        raise ValueError("Empty text — nothing to parse")

    # 1. Fast path: try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, (dict, list)):
            return result
    except json.JSONDecodeError:
        pass

    # 2. Extract from markdown fences / surrounding prose
    extracted = extract_json_from_text(text)
    if extracted:
        try:
            result = json.loads(extracted)
            if isinstance(result, (dict, list)):
                return result
        except json.JSONDecodeError:
            pass

        # 3. Try json-repair on the extracted substring
        try:
            repaired = repair_json(extracted, return_objects=True)
            if isinstance(repaired, (dict, list)):
                log.debug("json_repaired", original_len=len(extracted))
                return repaired
        except Exception:
            pass

    # 3b. Try json-repair on the full text as last resort
    try:
        repaired = repair_json(text, return_objects=True)
        if isinstance(repaired, (dict, list)):
            log.debug("json_repaired_full_text", original_len=len(text))
            return repaired
    except Exception:
        pass

    raise ValueError(
        f"Failed to parse JSON from LLM response ({len(text)} chars). "
        f"Preview: {text[:200]!r}"
    )
