from __future__ import annotations

import secrets


def generate_public_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(8).rstrip('=')}"

