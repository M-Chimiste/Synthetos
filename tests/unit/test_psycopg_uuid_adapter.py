"""psycopg3 dumper registration for uuid_utils.UUID."""

from __future__ import annotations

import psycopg
import uuid_utils
from psycopg.adapt import PyFormat, Transformer

# Importing libs.storage triggers the adapter registration as a side effect.
import libs.storage  # noqa: F401


def test_uuid_utils_uuid_has_registered_dumper() -> None:
    """psycopg3 can resolve a dumper for the Rust-backed uuid_utils.UUID
    class. Before this registration, the lookup fell through to the
    fallback path and raised
    ``ProgrammingError: cannot adapt type 'UUID'``.
    """
    u = uuid_utils.uuid7()

    transformer = Transformer()
    dumper = transformer.get_dumper(u, PyFormat.AUTO)
    out = dumper.dump(u)

    assert out is not None
    assert len(out) > 0
    # Either the binary dumper (16 bytes) or the text dumper (32 hex chars).
    assert len(out) in {16, 32}


def test_global_psycopg_adapters_know_uuid_utils() -> None:
    """The registration lives on the global psycopg.adapters map, so any
    new connection picks it up automatically without per-connection
    re-registration."""
    # The adapter is installed by importing libs.storage. After import,
    # psycopg.adapters.get_dumper should resolve uuid_utils.UUID without
    # raising.
    dumper_cls = psycopg.adapters.get_dumper(uuid_utils.UUID, PyFormat.AUTO)
    assert dumper_cls is not None
    assert "UUID" in dumper_cls.__name__
