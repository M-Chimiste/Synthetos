"""Storage layer package init.

Registers a psycopg3 adapter for ``uuid_utils.UUID`` at import time. The
project uses ``uuid_utils.uuid7()`` to mint UUIDv7 primary keys (see
``libs/core/services/charter_service.py`` and friends), but
``uuid_utils.UUID`` is a Rust-backed class that does not subclass
stdlib ``uuid.UUID``, so psycopg3's default UUID dumper does not match.
Without this adapter the worker's periodic decay enqueue (and any other
sync write that flows through psycopg with a freshly minted UUID PK)
fails with ``ProgrammingError: cannot adapt type 'UUID'``.

The two stdlib UUID dumpers (``UUIDDumper`` text + ``UUIDBinaryDumper``
binary) read ``obj.hex`` and ``obj.bytes`` respectively, both of which
``uuid_utils.UUID`` exposes, so the existing dumpers Just Work once
mapped to the new class.
"""

from __future__ import annotations

import psycopg
import uuid_utils
from psycopg.types.uuid import UUIDBinaryDumper, UUIDDumper

psycopg.adapters.register_dumper(uuid_utils.UUID, UUIDDumper)
psycopg.adapters.register_dumper(uuid_utils.UUID, UUIDBinaryDumper)
