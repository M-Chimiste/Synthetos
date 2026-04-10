"""Canonical domain event-type strings, namespaced by phase.

The ``domain_events.event_type`` column accepts arbitrary strings, but
operators and the SSE consumer in the web app filter on prefixes
(e.g. ``discovery.*``).  Centralizing the strings here avoids drift.
"""

from __future__ import annotations

from enum import StrEnum


class DiscoveryEvents(StrEnum):
    """Phase 1 discovery-pipeline event types."""

    intake_completed = "discovery.intake_completed"
    search_started = "discovery.search_started"
    papers_discovered = "discovery.papers_discovered"
    sources_deduped = "discovery.sources_deduped"
    rerank_started = "discovery.rerank_started"
    rerank_completed = "discovery.rerank_completed"
    rerank_skipped = "discovery.rerank_skipped"
    paper_metadata_analyzed = "discovery.paper_metadata_analyzed"
    view_built = "discovery.view_built"
    session_finalized = "discovery.session_finalized"
    session_failed = "discovery.session_failed"
    triage_overridden = "discovery.triage_overridden"
    evaluation_recorded = "discovery.evaluation_recorded"
