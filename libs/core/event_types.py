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


class AnalysisEvents(StrEnum):
    """Phase 2 analysis-pipeline event types."""

    session_started = "analysis.session_started"
    paper_ingested = "analysis.paper_ingested"
    paper_chunked = "analysis.paper_chunked"
    graph_extracted = "analysis.graph_extracted"
    coverage_computed = "analysis.coverage_computed"
    review_generated = "analysis.review_generated"
    evidence_extracted = "analysis.evidence_extracted"
    session_completed = "analysis.session_completed"
    session_failed = "analysis.session_failed"


class IdeationEvents(StrEnum):
    """Phase 3 hypothesis-pipeline event types."""

    session_started = "ideation.session_started"
    hypotheses_generated = "ideation.hypotheses_generated"
    hypotheses_critiqued = "ideation.hypotheses_critiqued"
    hypotheses_ranked = "ideation.hypotheses_ranked"
    session_completed = "ideation.session_completed"
    session_failed = "ideation.session_failed"


class ProtocolEvents(StrEnum):
    """Phase 3 protocol-compilation event types."""

    compilation_started = "protocol.compilation_started"
    spec_compiled = "protocol.spec_compiled"
    spec_rejected = "protocol.spec_rejected"
    compilation_completed = "protocol.compilation_completed"
    compilation_failed = "protocol.compilation_failed"


class ExecutionEvents(StrEnum):
    """Phase 3 execution-runtime event types."""

    workspace_created = "execution.workspace_created"
    image_built = "execution.image_built"
    container_started = "execution.container_started"
    run_progress = "execution.run_progress"
    run_completed = "execution.run_completed"
    run_failed = "execution.run_failed"
    run_cancelled = "execution.run_cancelled"
    run_paused = "execution.run_paused"
    artifacts_captured = "execution.artifacts_captured"


class VerificationEvents(StrEnum):
    """Phase 3 verification event types."""

    check_started = "verification.check_started"
    check_completed = "verification.check_completed"
    postmortem_generated = "verification.postmortem_generated"


class RemediationEvents(StrEnum):
    """Phase 4 remediation event types."""

    remediation_started = "remediation.started"
    retry_created = "remediation.retry_created"
    strategy_escalated = "remediation.strategy_escalated"
    skipped = "remediation.skipped"
    exhausted = "remediation.exhausted"


class SignalEvents(StrEnum):
    """Phase 4 signal and frontier event types."""

    signal_classified = "signal.classified"
    frontier_created = "signal.frontier_created"
    frontier_updated = "signal.frontier_updated"
    recommendation_produced = "signal.recommendation_produced"


class AutonomyEvents(StrEnum):
    """Phase 5 autonomous-loop event types."""

    loop_started = "autonomy.loop_started"
    loop_decision_made = "autonomy.loop_decision_made"
    budget_updated = "autonomy.budget_updated"
    budget_exceeded = "autonomy.budget_exceeded"
    gate_triggered = "autonomy.gate_triggered"
    gate_resumed = "autonomy.gate_resumed"
    hypothesis_status_changed = "autonomy.hypothesis_status_changed"
    hypothesis_selected = "autonomy.hypothesis_selected"
    repetition_detected = "autonomy.repetition_detected"
    context_summarized = "autonomy.context_summarized"
    loop_completed = "autonomy.loop_completed"
    loop_stopped_manual = "autonomy.loop_stopped_manual"
