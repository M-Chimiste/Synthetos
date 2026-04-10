"""Cross-source dedupe key generation and merge logic.

Phase 1 dedupe strategy (in priority order):

1. ``doi`` -- normalized to lowercase, stripped of ``https://doi.org/`` prefix.
2. canonical arXiv id (version stripped) when source is ``arxiv*``.
3. ``sha1(lower(title) + first_author_surname)`` as a final fallback.

When two hits collide on a key, prefer the row that already carries an
embedding (i.e. the internal corpus row), then merge missing scalar
fields from the other row.
"""

from __future__ import annotations

import hashlib
import re

from libs.adapters.sources.base import SourceHit

_ARXIV_VERSION_RE = re.compile(r"v\d+$")
_DOI_PREFIX_RE = re.compile(r"^https?://(dx\.)?doi\.org/", re.IGNORECASE)


def _normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    cleaned = _DOI_PREFIX_RE.sub("", doi.strip()).lower()
    return cleaned or None


def _normalize_arxiv_id(arxiv_id: str | None) -> str | None:
    if not arxiv_id:
        return None
    cleaned = arxiv_id.strip().lower()
    cleaned = cleaned.removeprefix("arxiv:")
    cleaned = _ARXIV_VERSION_RE.sub("", cleaned)
    return cleaned or None


def _surname_of(author: str) -> str:
    """Best-effort surname extraction.

    Handles both ``"Lastname, First"`` and ``"First Last"`` styles.
    """
    author = author.strip()
    if "," in author:
        return author.split(",", 1)[0].strip().lower()
    parts = author.split()
    return parts[-1].strip().lower() if parts else ""


def dedupe_key(hit: SourceHit) -> str:
    """Compute a stable cross-source dedupe key for a hit."""
    doi = _normalize_doi(hit.doi)
    if doi:
        return f"doi:{doi}"

    if hit.source.startswith("arxiv") or hit.source == "internal_corpus":
        arxiv_id = _normalize_arxiv_id(hit.external_id)
        if arxiv_id:
            return f"arxiv:{arxiv_id}"

    title = (hit.title or "").strip().lower()
    first_author_surname = _surname_of(hit.authors[0]) if hit.authors else ""
    digest = hashlib.sha1(
        f"{title}|{first_author_surname}".encode(),
        usedforsecurity=False,
    ).hexdigest()
    return f"title:{digest}"


def merge_hits(primary: SourceHit, secondary: SourceHit) -> SourceHit:
    """Merge two hits with the same dedupe key.

    ``primary`` wins on every field; ``secondary`` only fills in missing
    scalar values.  Embeddings are taken from whichever side has one,
    preferring ``primary``.
    """
    data = primary.model_dump()
    secondary_data = secondary.model_dump()

    for field, value in secondary_data.items():
        if data.get(field) in (None, "", [], {}):
            data[field] = value

    # Embedding preference: keep whichever exists, primary first.
    if primary.embedding is None and secondary.embedding is not None:
        data["embedding"] = secondary.embedding

    return SourceHit.model_validate(data)


def dedupe_hits(hits: list[SourceHit]) -> tuple[list[SourceHit], int]:
    """Deduplicate a list of hits.

    Returns ``(deduped_hits, dropped_count)``. Iteration order matches the
    input so the highest-confidence source (e.g. internal_corpus) should
    appear first.
    """
    seen: dict[str, SourceHit] = {}
    dropped = 0
    for hit in hits:
        key = dedupe_key(hit)
        existing = seen.get(key)
        if existing is None:
            seen[key] = hit
        else:
            seen[key] = merge_hits(existing, hit)
            dropped += 1
    return list(seen.values()), dropped
