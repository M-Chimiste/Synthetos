from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator, UserDefinedType


class _PostgresVector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int):
        self.dimensions = dimensions

    def get_col_spec(self, **_kw: Any) -> str:
        return f"vector({self.dimensions})"

    def bind_processor(self, dialect):
        def process(value: Any) -> str | None:
            if value is None:
                return None
            if isinstance(value, str):
                return value
            return "[" + ",".join(f"{float(item):.12g}" for item in value) + "]"

        return process

    def result_processor(self, dialect, coltype):
        def process(value: Any) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, list):
                return [float(item) for item in value]
            text = str(value).strip()
            if not text:
                return None
            if text.startswith("[") and text.endswith("]"):
                payload = text[1:-1].strip()
                if not payload:
                    return []
                return [float(item) for item in payload.split(",")]
            return None

        return process


class EmbeddingVector(TypeDecorator):
    """Store vectors natively in Postgres and as JSON text elsewhere."""

    impl = Text
    cache_ok = True

    def __init__(self, dimensions: int):
        super().__init__()
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PostgresVector(self.dimensions))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            if isinstance(value, str):
                return value
            return "[" + ",".join(f"{float(item):.12g}" for item in value) + "]"
        if isinstance(value, str):
            return value
        return json.dumps([float(item) for item in value])

    def process_result_value(self, value: Any, dialect) -> list[float] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return [float(item) for item in value]
        text = str(value).strip()
        if not text:
            return None
        if dialect.name == "postgresql":
            if text.startswith("[") and text.endswith("]"):
                payload = text[1:-1].strip()
                if not payload:
                    return []
                return [float(item) for item in payload.split(",")]
            return None
        return [float(item) for item in json.loads(text)]
