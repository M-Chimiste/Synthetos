"""consolidate_patterns operator -- mines source artifacts into canonical patterns.

Runs on the worker sync path. Idempotent: re-running over the same artifacts
reinforces existing rows via ``(pattern_type, content_key)`` upsert; no
duplicate patterns are created.

Scope:
  * If ``payload["charter_id"]`` is set, only that charter's artifacts are mined.
  * Otherwise all charters are mined (full re-consolidation).
  * If ``payload["pattern_types"]`` is set, only those types are produced.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from libs.core.event_types import PatternEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.patterns import content_key as ck_mod
from libs.patterns.consolidation import (
    AggregatedPattern,
    aggregate,
    extract_failure,
    extract_remediation,
    extract_retrieval_heuristic_from_loop,
    extract_signal_trajectory,
    extract_successful_line,
)
from libs.patterns.embedding import embed_texts, pattern_text
from libs.patterns.upsert import upsert_observations, upsert_pattern
from libs.storage.base import get_sync_session_factory
from libs.storage.models.autonomy import LoopDecision
from libs.storage.models.experiment import FailurePostmortem, HypothesisCard
from libs.storage.models.remediation import (
    DirectionalSignal,
    MetricFrontier,
    RemediationAction,
)
from libs.storage.models.research import ResearchCharter, ResearchCycle

log = get_logger("patterns.consolidate")

DEFAULT_TYPES: tuple[str, ...] = ck_mod.PATTERN_TYPES


def _filter_charter(stmt, model, charter_id: UUID | None):
    if charter_id is None:
        return stmt
    if model is ResearchCharter:
        return stmt.where(ResearchCharter.id == charter_id)
    return stmt.where(model.charter_id == charter_id)


def _problem_domain_for_charter(
    *,
    charter_map: dict[UUID, ResearchCharter],
    cycle_map: dict[UUID, ResearchCycle],
    charter_id: UUID,
    cycle_id: UUID | None,
) -> str:
    if cycle_id is not None:
        cycle = cycle_map.get(cycle_id)
        pilot_cfg = ((cycle.config or {}).get("pilot") or {}) if cycle else {}
        domain = pilot_cfg.get("domain")
        if domain:
            return str(domain)

    charter = charter_map.get(charter_id)
    source_scope = (charter.source_scope or {}) if charter else {}
    domain = source_scope.get("domain")
    if domain:
        return str(domain)
    return "unspecified"


def consolidate_patterns_operator(op_input: OperatorInput) -> OperatorResult:
    payload: dict[str, Any] = op_input.payload or {}
    charter_scope_raw = payload.get("charter_id")
    charter_scope: UUID | None = (
        UUID(str(charter_scope_raw)) if charter_scope_raw else None
    )
    requested_types = set(payload.get("pattern_types") or DEFAULT_TYPES)
    unknown = requested_types - set(DEFAULT_TYPES)
    if unknown:
        return OperatorResult(
            success=False, error=f"unknown pattern_types: {sorted(unknown)}"
        )

    factory = get_sync_session_factory()
    candidates = []
    counts_by_type: dict[str, int] = {}

    with factory() as db:
        emit_event_sync(
            db,
            event_type=PatternEvents.consolidation_started.value,
            charter_id=charter_scope,
            cycle_id=op_input.cycle_id,
            payload={
                "charter_scope": str(charter_scope) if charter_scope else "all",
                "pattern_types": sorted(requested_types),
            },
        )
        db.commit()

        # ------------------------------------------------------------------
        # Load hypothesis cards upfront for method-family derivation.
        # ------------------------------------------------------------------
        hypothesis_map: dict[UUID, HypothesisCard] = {}
        hypothesis_rows = db.execute(
            _filter_charter(select(HypothesisCard), HypothesisCard, charter_scope)
        ).scalars().all()
        for h in hypothesis_rows:
            hypothesis_map[h.id] = h
        charter_rows = db.execute(
            _filter_charter(select(ResearchCharter), ResearchCharter, charter_scope)
        ).scalars().all()
        charter_map = {charter.id: charter for charter in charter_rows}
        cycle_rows = db.execute(
            _filter_charter(select(ResearchCycle), ResearchCycle, charter_scope)
        ).scalars().all()
        cycle_map = {cycle.id: cycle for cycle in cycle_rows}

        # ------------------------------------------------------------------
        # Failure patterns
        # ------------------------------------------------------------------
        if "failure" in requested_types:
            rows = db.execute(
                _filter_charter(
                    select(FailurePostmortem), FailurePostmortem, charter_scope
                )
            ).scalars().all()
            for pm in rows:
                candidates.append(extract_failure(pm))
            counts_by_type["failure"] = len(rows)

        # ------------------------------------------------------------------
        # Remediation patterns
        # ------------------------------------------------------------------
        if "remediation" in requested_types:
            rows = db.execute(
                _filter_charter(
                    select(RemediationAction), RemediationAction, charter_scope
                )
            ).scalars().all()
            for ra in rows:
                candidates.append(extract_remediation(ra))
            counts_by_type["remediation"] = len(rows)

        # ------------------------------------------------------------------
        # Signal-trajectory patterns (need hypothesis lookup for method_family)
        # ------------------------------------------------------------------
        if "signal_trajectory" in requested_types:
            rows = db.execute(
                _filter_charter(
                    select(DirectionalSignal), DirectionalSignal, charter_scope
                )
            ).scalars().all()
            # Build spec_id -> hypothesis lookup by joining ExperimentSpec.
            from libs.storage.models.experiment import ExperimentSpec

            spec_rows = db.execute(
                _filter_charter(select(ExperimentSpec), ExperimentSpec, charter_scope)
            ).scalars().all()
            spec_to_hypothesis: dict[UUID, HypothesisCard | None] = {
                s.id: hypothesis_map.get(s.hypothesis_card_id) for s in spec_rows
            }
            for sig in rows:
                hyp = spec_to_hypothesis.get(sig.experiment_spec_id)
                candidates.append(extract_signal_trajectory(sig, hypothesis=hyp))
            counts_by_type["signal_trajectory"] = len(rows)

        # ------------------------------------------------------------------
        # Successful-line patterns
        # ------------------------------------------------------------------
        if "successful_line" in requested_types:
            rows = db.execute(
                _filter_charter(
                    select(MetricFrontier), MetricFrontier, charter_scope
                )
            ).scalars().all()
            for frontier in rows:
                if frontier.successful_runs <= 0:
                    continue
                hyp = hypothesis_map.get(frontier.hypothesis_card_id)
                candidates.append(
                    extract_successful_line(
                        frontier,
                        hypothesis=hyp,
                        cycle_id=(hyp.cycle_id if hyp is not None else op_input.cycle_id),
                        problem_domain=_problem_domain_for_charter(
                            charter_map=charter_map,
                            cycle_map=cycle_map,
                            charter_id=frontier.charter_id,
                            cycle_id=(hyp.cycle_id if hyp is not None else op_input.cycle_id),
                        ),
                    )
                )
            counts_by_type["successful_line"] = len(rows)

        # ------------------------------------------------------------------
        # Retrieval-heuristic patterns (from loop decisions)
        # ------------------------------------------------------------------
        if "retrieval_heuristic" in requested_types:
            rows = db.execute(
                _filter_charter(select(LoopDecision), LoopDecision, charter_scope)
            ).scalars().all()
            n = 0
            for d in rows:
                cand = extract_retrieval_heuristic_from_loop(d)
                if cand:
                    candidates.append(cand)
                    n += 1
            counts_by_type["retrieval_heuristic"] = n

        # ------------------------------------------------------------------
        # Aggregate & upsert
        # ------------------------------------------------------------------
        aggregated: list[AggregatedPattern] = aggregate(candidates)

        # Embed new or refreshed patterns.
        texts = [pattern_text(a.title, a.summary) for a in aggregated]
        vectors = embed_texts(texts) if texts else []

        created_count = 0
        reinforced_count = 0
        observations_inserted = 0
        for agg, vec in zip(aggregated, vectors, strict=False):
            pattern, created = upsert_pattern(db, agg)
            if vec is not None:
                pattern.embedding = vec
            observations_inserted += upsert_observations(db, pattern, agg)
            if created:
                created_count += 1
            else:
                reinforced_count += 1

            emit_event_sync(
                db,
                event_type=PatternEvents.consolidated.value,
                charter_id=op_input.charter_id,
                cycle_id=op_input.cycle_id,
                payload={
                    "pattern_id": str(pattern.id),
                    "pattern_type": pattern.pattern_type,
                    "content_key": pattern.content_key,
                    "evidence_count": pattern.evidence_count,
                    "confidence": pattern.confidence,
                    "created": created,
                },
            )

        emit_event_sync(
            db,
            event_type=PatternEvents.consolidation_completed.value,
            charter_id=charter_scope,
            cycle_id=op_input.cycle_id,
            payload={
                "candidates": len(candidates),
                "aggregated": len(aggregated),
                "created": created_count,
                "reinforced": reinforced_count,
                "observations_inserted": observations_inserted,
                "counts_by_source": counts_by_type,
            },
        )
        db.commit()

    summary = (
        f"consolidated {len(aggregated)} patterns "
        f"({created_count} new, {reinforced_count} reinforced); "
        f"{observations_inserted} observations"
    )
    return OperatorResult(
        success=True,
        summary=summary,
        events=[],  # events already emitted via emit_event_sync
    )
