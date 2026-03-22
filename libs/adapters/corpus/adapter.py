"""Internal corpus adapter for local research documents.

Searches markdown and text files under a configured corpus directory
for keyword matches. Returns results as RawPaperRecord for a unified
downstream pipeline.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import structlog

from libs.adapters.literature import LiteratureSourceAdapter, RawPaperRecord, SourceQuery

log = structlog.get_logger(__name__)

SEARCHABLE_EXTENSIONS = {".md", ".txt", ".rst"}


class CorpusAdapterConfig:
    def __init__(self, corpus_dir: Path):
        self.corpus_dir = corpus_dir


class InternalCorpusAdapter(LiteratureSourceAdapter):
    """Adapter that searches a local directory of research documents."""

    def __init__(self, config: CorpusAdapterConfig):
        self.config = config

    def search(self, query: SourceQuery) -> list[RawPaperRecord]:
        corpus_dir = self.config.corpus_dir
        if not corpus_dir.is_dir():
            log.info("internal_corpus_dir_missing", path=str(corpus_dir))
            return []

        keywords_lower = [k.lower() for k in query.keywords]
        records: list[RawPaperRecord] = []

        for path in corpus_dir.rglob("*"):
            if path.suffix not in SEARCHABLE_EXTENSIONS:
                continue
            if not path.is_file():
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            if keywords_lower and not any(kw in content.lower() for kw in keywords_lower):
                continue

            # Use first line as title, rest as abstract
            lines = content.strip().splitlines()
            title = lines[0].lstrip("# ").strip() if lines else path.stem
            abstract = "\n".join(lines[1:200]).strip() if len(lines) > 1 else None

            doc_id = hashlib.sha256(str(path).encode()).hexdigest()[:16]

            records.append(
                RawPaperRecord(
                    external_id=f"corpus:{doc_id}",
                    title=title,
                    abstract=abstract,
                    authors=[],
                    categories=["internal"],
                    source_type="internal_corpus",
                    source_url=str(path),
                    metadata_extra={"file_path": str(path)},
                )
            )

            if query.max_results and len(records) >= query.max_results:
                break

        log.info("internal_corpus_search_complete", result_count=len(records))
        return records
