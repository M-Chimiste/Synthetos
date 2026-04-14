"""loop_decide operator -- the core autonomous-loop decision point.

Consumes a RunRecommendation and decides whether to continue, vary,
pivot, or stop the loop. Manages budget tracking, gate evaluation,
hypothesis lifecycle, and repetition detection.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from uuid_utils import uuid7

from libs.autonomy.budget import (
    check_budget,
    check_per_hypothesis_budget,
    increment_budget,
    load_or_create_budget,
)
from libs.autonomy.context_summary import (
    generate_summary,
    should_generate_summary,
    write_summary,
)
from libs.autonomy.gates import GateContext, evaluate_gates, preview_next_spec
from libs.autonomy.hypothesis_lifecycle import update_hypothesis_status
from libs.autonomy.policy import AutonomyPolicy
from libs.autonomy.repetition import detect_repetition
from libs.core.clock import utcnow
from libs.core.event_types import AutonomyEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.core.services.job_service import create_job
from libs.core.types import CycleStatus, JobStatus
from libs.patterns.embedding import embed_text
from libs.patterns.injection import InjectionPolicy, inject_patterns
from libs.storage.base import get_sync_session_factory
from libs.storage.models.autonomy import LoopDecision
from libs.storage.models.experiment import ExperimentSpec, HypothesisCard, RunRecord
from libs.storage.models.jobs import Job
from libs.storage.models.remediation import (
    DirectionalSignal,
    MetricFrontier,
    RunRecommendation,
)
from libs.storage.models.research import ResearchCycle

log = get_logger("autonomy.loop_decide")


def loop_decide_operator(op_input: OperatorInput) -> OperatorResult:
    """Core loop decision operator."""
    factory = get_sync_session_factory()
    payload = op_input.payload

    prepared_run_id_raw = payload.get("prepared_run_record_id")
    if prepared_run_id_raw is not None:
        from libs.execution.operators._common import enqueue_next

        prepared_run_id = UUID(str(prepared_run_id_raw))
        with factory() as db:
            prepared_run = db.get(RunRecord, prepared_run_id)
            if prepared_run is None:
                return OperatorResult(
                    success=False,
                    error=f"prepared run record {prepared_run_id} not found",
                )

            enqueue_next(
                db,
                cycle_id=prepared_run.cycle_id,
                next_job_type="execution_setup",
                run_record_id=prepared_run.id,
            )
            db.commit()

        return OperatorResult(
            success=True,
            summary=f"Gate approved; enqueued execution_setup for prepared run {prepared_run_id}",
            state_patch={"cycle_status": CycleStatus.running.value},
        )

    rec_id_raw = payload.get("recommendation_id")
    run_id_raw = payload.get("run_record_id")
    if rec_id_raw is None or run_id_raw is None:
        return OperatorResult(
            success=False,
            error="loop_decide payload missing recommendation_id or run_record_id",
        )

    rec_id = UUID(str(rec_id_raw))
    run_id = UUID(str(run_id_raw))

    with factory() as db:
        # 1. Load recommendation, run, cycle, policy
        rec = db.execute(
            select(RunRecommendation).where(RunRecommendation.id == rec_id)
        ).scalar_one_or_none()
        if rec is None:
            return OperatorResult(success=False, error=f"recommendation {rec_id} not found")

        run = db.execute(
            select(RunRecord).where(RunRecord.id == run_id)
        ).scalar_one_or_none()
        if run is None:
            return OperatorResult(success=False, error=f"run record {run_id} not found")

        spec = db.execute(
            select(ExperimentSpec).where(ExperimentSpec.id == run.experiment_spec_id)
        ).scalar_one_or_none()

        cycle = db.get(ResearchCycle, run.cycle_id)
        if cycle is None:
            return OperatorResult(success=False, error="cycle not found")

        policy = AutonomyPolicy.model_validate(
            (cycle.config or {}).get("autonomy", {})
        )

        # Phase 6: retrieve signal_trajectory + retrieval_heuristic patterns to
        # bias loop decisions. For now we surface them in the audit trail
        # (via pattern.applied events emitted by inject_patterns); deeper
        # biasing of continue/vary/pivot decisions is left as future tightening.
        pattern_injection_policy = InjectionPolicy.from_cycle_config(cycle.config)
        _loop_patterns = inject_patterns(
            db,
            charter_id=run.charter_id,
            current_cycle_id=run.cycle_id,
            types=["signal_trajectory", "retrieval_heuristic"],
            policy=pattern_injection_policy,
            problem_profile_embedding=embed_text(
                "\n".join(
                    [
                        getattr(spec, "title", "") if spec else "",
                        getattr(spec, "description", "") if spec else "",
                        rec.recommendation_type,
                        rec.reasoning,
                    ]
                )
            ),
            operator_name="loop_decide",
        )

        # 2. Load/create budget and check for gate-resume before mutating counters.
        budget = load_or_create_budget(db, run.cycle_id)
        hypothesis_card_id = spec.hypothesis_card_id if spec else None
        existing_gate_decision = db.execute(
            select(LoopDecision).where(
                LoopDecision.run_record_id == run_id,
                LoopDecision.decision == "stop_gate",
            )
        ).scalar_one_or_none()

        existing_decisions = db.execute(
            select(func.count())
            .select_from(LoopDecision)
            .where(LoopDecision.cycle_id == run.cycle_id)
        ).scalar_one()
        iteration_number = (
            existing_gate_decision.iteration_number
            if existing_gate_decision is not None
            else existing_decisions + 1
        )

        if existing_gate_decision is None and hypothesis_card_id:
            increment_budget(db, budget, hypothesis_card_id)
            emit_event_sync(
                db,
                event_type=AutonomyEvents.budget_updated.value,
                charter_id=run.charter_id,
                cycle_id=run.cycle_id,
                payload={
                    "run_record_id": str(run_id),
                    "total_runs": budget.total_runs,
                    "wall_clock_elapsed_s": budget.wall_clock_elapsed_s,
                    "hypothesis_card_id": str(hypothesis_card_id),
                },
            )

        # Initialize variables used across both gate-resume and normal paths
        card: HypothesisCard | None = None
        signal_row: DirectionalSignal | None = None
        frontier: MetricFrontier | None = None
        context_summary_path = (
            existing_gate_decision.context_summary_path
            if existing_gate_decision
            else None
        )

        # 3. Check for gate-resume (re-run after pause)
        if existing_gate_decision is not None:
            # Gate was approved -- skip gate evaluation, proceed with recommendation
            log.info("gate_resumed", run_id=str(run_id), iteration=iteration_number)
            emit_event_sync(
                db,
                event_type=AutonomyEvents.gate_resumed.value,
                charter_id=run.charter_id,
                cycle_id=run.cycle_id,
                payload={"run_record_id": str(run_id), "iteration": iteration_number},
            )
        else:
            # 4. Check budget limits
            budget_result = check_budget(policy, budget)
            if budget_result.exceeded:
                return _stop(
                    db, run, rec, budget, iteration_number,
                    decision="stop_budget",
                    reasoning=budget_result.detail,
                    hypothesis_card_id=hypothesis_card_id,
                )

            if hypothesis_card_id:
                per_hyp = check_per_hypothesis_budget(
                    policy, budget, hypothesis_card_id
                )
                if per_hyp.exceeded:
                    return _stop(
                        db, run, rec, budget, iteration_number,
                        decision="stop_budget",
                        reasoning=per_hyp.detail,
                        hypothesis_card_id=hypothesis_card_id,
                    )

            # 5. Evaluate checkpoint gates
            signal_row = db.execute(
                select(DirectionalSignal).where(
                    DirectionalSignal.run_record_id == run_id
                )
            ).scalar_one_or_none()

            frontier = None
            if hypothesis_card_id:
                frontier = db.execute(
                    select(MetricFrontier).where(
                        MetricFrontier.charter_id == run.charter_id,
                        MetricFrontier.hypothesis_card_id == hypothesis_card_id,
                    )
                ).scalar_one_or_none()

            # Compute gate context
            last_gate_decision = db.execute(
                select(LoopDecision)
                .where(LoopDecision.cycle_id == run.cycle_id)
                .where(LoopDecision.decision == "stop_gate")
                .order_by(LoopDecision.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            last_gate_total_runs = 0
            if last_gate_decision is not None:
                last_gate_total_runs = int(
                    (last_gate_decision.budget_snapshot or {}).get("total_runs", 0)
                )
            runs_since_last_gate = max(0, budget.total_runs - last_gate_total_runs)

            # Check if hypothesis would be validated
            card = None
            if hypothesis_card_id:
                card = db.get(HypothesisCard, hypothesis_card_id)

            is_result_promotion = False
            if card and spec:
                from libs.autonomy.hypothesis_lifecycle import compute_lifecycle_status

                potential_status = compute_lifecycle_status(
                    card.status,
                    signal_row.signal if signal_row else None,
                    frontier,
                    rec.recommendation_type,
                    spec,
                )
                is_result_promotion = potential_status == "validated"

            gate_ctx = GateContext(
                runs_since_last_gate=runs_since_last_gate,
                wall_clock_elapsed_s=budget.wall_clock_elapsed_s,
                current_hardware_profile=spec.hardware_profile if spec else None,
                next_hardware_profile=spec.hardware_profile if spec else None,
                is_result_promotion=is_result_promotion,
            )
            gate_result = evaluate_gates(policy, budget, gate_ctx)

            if gate_result.should_pause:
                return _pause_for_gate(
                    db, op_input.job_id, run, rec, budget, iteration_number,
                    gate_name=gate_result.gate_name or "unknown",
                    reason=gate_result.reason,
                    hypothesis_card_id=hypothesis_card_id,
                )

        # 6. Context summarization (if at boundary)
        if context_summary_path is None and should_generate_summary(
            budget.total_runs,
            policy.summary_interval,
        ):
            summary = generate_summary(
                db, run.cycle_id, run.charter_id, iteration_number
            )
            context_summary_path = write_summary(summary, run.cycle_id)
            emit_event_sync(
                db,
                event_type=AutonomyEvents.context_summarized.value,
                charter_id=run.charter_id,
                cycle_id=run.cycle_id,
                payload={
                    "iteration": iteration_number,
                    "path": context_summary_path,
                },
            )

        # 7. Update hypothesis lifecycle
        if card is None and hypothesis_card_id:
            card = db.get(HypothesisCard, hypothesis_card_id)
        if signal_row is None:
            signal_row = db.execute(
                select(DirectionalSignal).where(
                    DirectionalSignal.run_record_id == run_id
                )
            ).scalar_one_or_none()
        if frontier is None and hypothesis_card_id:
            frontier = db.execute(
                select(MetricFrontier).where(
                    MetricFrontier.charter_id == run.charter_id,
                    MetricFrontier.hypothesis_card_id == hypothesis_card_id,
                )
            ).scalar_one_or_none()

        if card:
            old_status = card.status
            new_status = update_hypothesis_status(
                db, card,
                signal=signal_row.signal if signal_row else None,
                frontier=frontier,
                recommendation_type=rec.recommendation_type,
                spec=spec,
            )
            if new_status != old_status:
                emit_event_sync(
                    db,
                    event_type=AutonomyEvents.hypothesis_status_changed.value,
                    charter_id=run.charter_id,
                    cycle_id=run.cycle_id,
                    payload={
                        "card_id": str(card.id),
                        "from_status": old_status,
                        "to_status": new_status,
                    },
                )

        # 8. Act on recommendation
        recommendation_type = rec.recommendation_type

        if recommendation_type == "halt":
            return _stop(
                db, run, rec, budget, iteration_number,
                decision="stop_halt",
                reasoning=rec.reasoning,
                hypothesis_card_id=hypothesis_card_id,
                context_summary_path=context_summary_path,
            )

        if recommendation_type == "continue_current" and spec:
            # Check repetition
            rep = detect_repetition(db, run.cycle_id, spec)
            if rep.is_duplicate:
                log.info("repetition_detected", type="exact", spec_id=str(spec.id))
                emit_event_sync(
                    db,
                    event_type=AutonomyEvents.repetition_detected.value,
                    charter_id=run.charter_id,
                    cycle_id=run.cycle_id,
                    payload={"spec_id": str(spec.id), "match_type": "exact"},
                )
                # Escalate to parameter_variation
                recommendation_type = "parameter_variation"

        if recommendation_type == "continue_current" and spec:
            preview = preview_next_spec(spec)
            gate_result = evaluate_gates(
                policy,
                budget,
                GateContext(
                    runs_since_last_gate=0,
                    wall_clock_elapsed_s=budget.wall_clock_elapsed_s,
                    current_hardware_profile=spec.hardware_profile if spec else None,
                    next_hardware_profile=preview.hardware_profile,
                    has_network_access=preview.has_network_access,
                ),
            )
            if gate_result.should_pause and gate_result.gate_name in (
                "before_hardware_escalation",
                "before_network_execution",
            ):
                return _pause_for_gate(
                    db, op_input.job_id, run, rec, budget, iteration_number,
                    gate_name=gate_result.gate_name or "unknown",
                    reason=gate_result.reason,
                    hypothesis_card_id=hypothesis_card_id,
                    context_summary_path=context_summary_path,
                )
            # Rerun same spec
            return _continue_current(
                db, run, rec, spec, budget, iteration_number,
                hypothesis_card_id=hypothesis_card_id,
                context_summary_path=context_summary_path,
            )

        if recommendation_type == "parameter_variation" and spec:
            return _vary_parameters(
                db, run, rec, spec, budget, iteration_number,
                hypothesis_card_id=hypothesis_card_id,
                context_summary_path=context_summary_path,
                signal=signal_row.signal if signal_row else None,
                frontier=frontier,
            )

        if recommendation_type == "hypothesis_pivot":
            return _pivot_hypothesis(
                db, op_input.job_id, run, rec, spec, budget, iteration_number,
                hypothesis_card_id=hypothesis_card_id,
                context_summary_path=context_summary_path,
                policy=policy,
            )

        # Fallback: treat as parameter_variation
        if spec:
            return _vary_parameters(
                db, run, rec, spec, budget, iteration_number,
                hypothesis_card_id=hypothesis_card_id,
                context_summary_path=context_summary_path,
                signal=signal_row.signal if signal_row else None,
                frontier=frontier,
            )

        return _stop(
            db, run, rec, budget, iteration_number,
            decision="stop_halt",
            reasoning="No viable spec or recommendation path.",
            hypothesis_card_id=hypothesis_card_id,
            context_summary_path=context_summary_path,
        )


# ---------------------------------------------------------------------------
# Decision implementations
# ---------------------------------------------------------------------------


def _continue_current(
    db, run, rec, spec, budget, iteration_number, *,
    hypothesis_card_id, context_summary_path,
) -> OperatorResult:
    """Rerun the same spec with a new RunRecord."""
    max_run_num = db.execute(
        select(func.coalesce(func.max(RunRecord.run_number), 0))
        .where(RunRecord.experiment_spec_id == spec.id)
    ).scalar_one()

    new_run = RunRecord(
        id=uuid7(),
        experiment_spec_id=spec.id,
        charter_id=run.charter_id,
        cycle_id=run.cycle_id,
        run_number=max_run_num + 1,
        status="pending",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(new_run)

    from libs.execution.operators._common import enqueue_next

    enqueue_next(
        db,
        cycle_id=run.cycle_id,
        next_job_type="execution_setup",
        run_record_id=new_run.id,
    )

    _persist_decision(
        db, run, rec, budget, iteration_number,
        decision="continue_current",
        next_action="rerun_spec",
        hypothesis_card_id=hypothesis_card_id,
        context_summary_path=context_summary_path,
        reasoning=f"Continuing with {spec.title}; rerunning same spec.",
    )

    emit_event_sync(
        db,
        event_type=AutonomyEvents.loop_decision_made.value,
        charter_id=run.charter_id,
        cycle_id=run.cycle_id,
        payload={
            "iteration": iteration_number,
            "decision": "continue_current",
            "next_run_id": str(new_run.id),
        },
    )
    db.commit()

    return OperatorResult(
        success=True,
        summary=f"Loop iteration {iteration_number}: continue_current -> rerun spec",
        state_patch={"cycle_status": CycleStatus.running.value},
    )


def _vary_parameters(
    db, run, rec, spec, budget, iteration_number, *,
    hypothesis_card_id, context_summary_path, signal, frontier,
) -> OperatorResult:
    """Recompile spec with variation context."""
    # Count how many variations have been tried for this hypothesis
    from libs.storage.models.experiment import HypothesisSession

    hs = db.execute(
        select(HypothesisSession).where(
            HypothesisSession.cycle_id == run.cycle_id
        ).limit(1)
    ).scalar_one_or_none()

    if hs is None:
        return OperatorResult(
            success=False, error="no hypothesis session found for cycle"
        )

    variation_count = db.execute(
        select(func.count())
        .select_from(ExperimentSpec)
        .where(ExperimentSpec.hypothesis_card_id == hypothesis_card_id)
        .where(ExperimentSpec.cycle_id == run.cycle_id)
    ).scalar_one()

    variation_context = {
        "prior_spec_id": str(spec.id),
        "prior_metrics": run.metrics_output,
        "signal": signal,
        "frontier_best": frontier.best_metric_value if frontier else None,
        "recommendation_action": rec.action,
        "variation_number": variation_count + 1,
    }

    # Load context summary if available
    if context_summary_path:
        import json
        from pathlib import Path

        summary_path = Path(context_summary_path)
        if summary_path.exists():
            try:
                summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
                variation_context["context_summary"] = {
                    "key_findings": summary_data.get("key_findings", ""),
                    "repeated_approaches": summary_data.get("repeated_approaches", []),
                    "frontier_progression": summary_data.get("frontier_progression", []),
                }
            except (json.JSONDecodeError, OSError):
                pass

    compile_payload = {
        "hypothesis_session_id": str(hs.id),
        "hypothesis_card_ids": [str(hypothesis_card_id)],
        "variation_context": variation_context,
        "from_loop": True,
        "loop_context": {
            "run_record_id": str(run.id),
            "recommendation_id": str(rec.id),
            "hypothesis_card_id": str(hypothesis_card_id) if hypothesis_card_id else None,
            "context_summary_path": context_summary_path,
            "current_hardware_profile": spec.hardware_profile if spec else None,
        },
    }
    if spec.hardware_profile:
        compile_payload["hardware_profile"] = spec.hardware_profile
    if spec.base_image:
        compile_payload["base_image"] = spec.base_image

    create_job(
        db,
        cycle_id=run.cycle_id,
        job_type="protocol_compile",
        payload=compile_payload,
        priority=10,
    )

    _persist_decision(
        db, run, rec, budget, iteration_number,
        decision="vary_parameters",
        next_action="recompile_spec",
        hypothesis_card_id=hypothesis_card_id,
        context_summary_path=context_summary_path,
        reasoning=f"Varying parameters for {spec.title}; variation #{variation_count + 1}.",
    )

    emit_event_sync(
        db,
        event_type=AutonomyEvents.loop_decision_made.value,
        charter_id=run.charter_id,
        cycle_id=run.cycle_id,
        payload={
            "iteration": iteration_number,
            "decision": "vary_parameters",
            "variation_number": variation_count + 1,
        },
    )
    db.commit()

    return OperatorResult(
        success=True,
        summary=(
            f"Loop iteration {iteration_number}: vary_parameters -> "
            f"recompile spec (variation #{variation_count + 1})"
        ),
        state_patch={"cycle_status": CycleStatus.running.value},
    )


def _pivot_hypothesis(
    db, job_id, run, rec, spec, budget, iteration_number, *,
    hypothesis_card_id, context_summary_path, policy,
) -> OperatorResult:
    """Deprioritize current hypothesis and switch to the next viable one."""
    # Deprioritize current
    if hypothesis_card_id:
        current_card = db.get(HypothesisCard, hypothesis_card_id)
        if current_card and current_card.status not in ("deprioritized", "rejected"):
            current_card.status = "deprioritized"
            current_card.updated_at = utcnow()

    # Find next viable card
    next_card = db.execute(
        select(HypothesisCard)
        .where(HypothesisCard.cycle_id == run.cycle_id)
        .where(HypothesisCard.status.in_(["candidate", "compiled", "deferred"]))
        .order_by(HypothesisCard.rank.asc().nulls_last())
        .limit(1)
    ).scalar_one_or_none()

    if next_card is None:
        return _stop(
            db, run, rec, budget, iteration_number,
            decision="stop_exhausted",
            reasoning="No remaining viable hypotheses for pivot.",
            hypothesis_card_id=hypothesis_card_id,
            context_summary_path=context_summary_path,
        )

    emit_event_sync(
        db,
        event_type=AutonomyEvents.hypothesis_selected.value,
        charter_id=run.charter_id,
        cycle_id=run.cycle_id,
        payload={
            "card_id": str(next_card.id),
            "title": next_card.title,
            "reason": "pivot",
        },
    )

    next_hypothesis_card_id = next_card.id

    if next_card.status == "compiled":
        # Find an existing validated spec for this card
        existing_spec = db.execute(
            select(ExperimentSpec)
            .where(ExperimentSpec.hypothesis_card_id == next_card.id)
            .where(ExperimentSpec.status == "validated")
            .order_by(ExperimentSpec.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        if existing_spec:
            preview = preview_next_spec(existing_spec)
            gate_result = evaluate_gates(
                policy,
                budget,
                GateContext(
                    runs_since_last_gate=0,
                    wall_clock_elapsed_s=budget.wall_clock_elapsed_s,
                    current_hardware_profile=spec.hardware_profile if spec else None,
                    next_hardware_profile=preview.hardware_profile,
                    has_network_access=preview.has_network_access,
                ),
            )
            if gate_result.should_pause and gate_result.gate_name in (
                "before_hardware_escalation",
                "before_network_execution",
            ):
                return _pause_for_gate(
                    db, job_id, run, rec, budget, iteration_number,
                    gate_name=gate_result.gate_name or "unknown",
                    reason=gate_result.reason,
                    hypothesis_card_id=hypothesis_card_id,
                    context_summary_path=context_summary_path,
                )
            # Create RunRecord and enqueue execution_setup
            max_run_num = db.execute(
                select(func.coalesce(func.max(RunRecord.run_number), 0))
                .where(RunRecord.experiment_spec_id == existing_spec.id)
            ).scalar_one()

            new_run = RunRecord(
                id=uuid7(),
                experiment_spec_id=existing_spec.id,
                charter_id=run.charter_id,
                cycle_id=run.cycle_id,
                run_number=max_run_num + 1,
                status="pending",
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.add(new_run)

            from libs.execution.operators._common import enqueue_next

            enqueue_next(
                db,
                cycle_id=run.cycle_id,
                next_job_type="execution_setup",
                run_record_id=new_run.id,
            )

            _persist_decision(
                db, run, rec, budget, iteration_number,
                decision="pivot_hypothesis",
                next_action="rerun_spec",
                hypothesis_card_id=hypothesis_card_id,
                next_hypothesis_card_id=next_hypothesis_card_id,
                context_summary_path=context_summary_path,
                reasoning=f"Pivoting to {next_card.title} (already compiled).",
            )

            emit_event_sync(
                db,
                event_type=AutonomyEvents.loop_decision_made.value,
                charter_id=run.charter_id,
                cycle_id=run.cycle_id,
                payload={
                    "iteration": iteration_number,
                    "decision": "pivot_hypothesis",
                    "next_card_id": str(next_card.id),
                },
            )
            db.commit()

            return OperatorResult(
                success=True,
                summary=(
                    f"Loop iteration {iteration_number}: pivot_hypothesis -> "
                    f"{next_card.title} (existing spec)"
                ),
                state_patch={"cycle_status": CycleStatus.running.value},
            )

    # Need to compile a new spec for this card
    from libs.storage.models.experiment import HypothesisSession

    hs = db.execute(
        select(HypothesisSession).where(
            HypothesisSession.cycle_id == run.cycle_id
        ).limit(1)
    ).scalar_one_or_none()

    if hs is None:
        return _stop(
            db, run, rec, budget, iteration_number,
            decision="stop_exhausted",
            reasoning="No hypothesis session found for compilation.",
            hypothesis_card_id=hypothesis_card_id,
            context_summary_path=context_summary_path,
        )

    compile_payload = {
        "hypothesis_session_id": str(hs.id),
        "hypothesis_card_ids": [str(next_card.id)],
        "from_loop": True,
        "loop_context": {
            "run_record_id": str(run.id),
            "recommendation_id": str(rec.id),
            "hypothesis_card_id": str(hypothesis_card_id) if hypothesis_card_id else None,
            "context_summary_path": context_summary_path,
            "current_hardware_profile": spec.hardware_profile if spec else None,
        },
    }

    create_job(
        db,
        cycle_id=run.cycle_id,
        job_type="protocol_compile",
        payload=compile_payload,
        priority=10,
    )

    _persist_decision(
        db, run, rec, budget, iteration_number,
        decision="pivot_hypothesis",
        next_action="compile_new_hypothesis",
        hypothesis_card_id=hypothesis_card_id,
        next_hypothesis_card_id=next_hypothesis_card_id,
        context_summary_path=context_summary_path,
        reasoning=f"Pivoting to {next_card.title} (needs compilation).",
    )

    emit_event_sync(
        db,
        event_type=AutonomyEvents.loop_decision_made.value,
        charter_id=run.charter_id,
        cycle_id=run.cycle_id,
        payload={
            "iteration": iteration_number,
            "decision": "pivot_hypothesis",
            "next_card_id": str(next_card.id),
            "needs_compile": True,
        },
    )
    db.commit()

    return OperatorResult(
        success=True,
        summary=(
            f"Loop iteration {iteration_number}: pivot_hypothesis -> "
            f"{next_card.title} (compiling)"
        ),
        state_patch={"cycle_status": CycleStatus.running.value},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stop(
    db, run, rec, budget, iteration_number, *,
    decision, reasoning, hypothesis_card_id=None, context_summary_path=None,
) -> OperatorResult:
    """Stop the loop and enqueue completion report."""
    if decision == "stop_budget":
        emit_event_sync(
            db,
            event_type=AutonomyEvents.budget_exceeded.value,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            payload={
                "run_record_id": str(run.id),
                "reason": reasoning,
                "total_runs": budget.total_runs,
                "wall_clock_elapsed_s": budget.wall_clock_elapsed_s,
            },
        )
    _persist_decision(
        db, run, rec, budget, iteration_number,
        decision=decision,
        reasoning=reasoning,
        hypothesis_card_id=hypothesis_card_id,
        context_summary_path=context_summary_path,
    )

    create_job(
        db,
        cycle_id=run.cycle_id,
        job_type="loop_report",
        payload={"cycle_id": str(run.cycle_id)},
        priority=5,
    )

    emit_event_sync(
        db,
        event_type=AutonomyEvents.loop_completed.value,
        charter_id=run.charter_id,
        cycle_id=run.cycle_id,
        payload={
            "iteration": iteration_number,
            "decision": decision,
            "reasoning": reasoning,
        },
    )
    db.commit()

    return OperatorResult(
        success=True,
        summary=f"Loop stopped at iteration {iteration_number}: {decision}",
        state_patch={"cycle_status": CycleStatus.reporting.value},
    )


def _pause_for_gate(
    db, job_id, run, rec, budget, iteration_number, *,
    gate_name, reason, hypothesis_card_id=None, context_summary_path=None,
) -> OperatorResult:
    """Pause the loop at a checkpoint gate."""
    # Set job status to paused directly
    if job_id is not None:
        db.execute(
            update(Job).where(Job.id == job_id).values(status=JobStatus.paused)
        )
        db.flush()

    _persist_decision(
        db, run, rec, budget, iteration_number,
        decision="stop_gate",
        gate_triggered=gate_name,
        reasoning=reason,
        hypothesis_card_id=hypothesis_card_id,
        context_summary_path=context_summary_path,
    )

    emit_event_sync(
        db,
        event_type=AutonomyEvents.gate_triggered.value,
        charter_id=run.charter_id,
        cycle_id=run.cycle_id,
        payload={
            "iteration": iteration_number,
            "gate_name": gate_name,
            "reason": reason,
        },
    )
    db.commit()

    # Return success with no state_patch -- cycle stays in loop_deciding
    return OperatorResult(
        success=True,
        summary=f"Loop paused at gate '{gate_name}' (iteration {iteration_number})",
    )


def _persist_decision(
    db, run, rec, budget, iteration_number, *,
    decision, reasoning,
    hypothesis_card_id=None,
    next_hypothesis_card_id=None,
    next_action=None,
    gate_triggered=None,
    context_summary_path=None,
) -> LoopDecision:
    """Persist a LoopDecision row."""
    row = LoopDecision(
        id=uuid7(),
        cycle_id=run.cycle_id,
        charter_id=run.charter_id,
        run_record_id=run.id,
        recommendation_id=rec.id,
        iteration_number=iteration_number,
        decision=decision,
        gate_triggered=gate_triggered,
        budget_snapshot={
            "total_runs": budget.total_runs,
            "wall_clock_elapsed_s": budget.wall_clock_elapsed_s,
            "runs_per_hypothesis": budget.runs_per_hypothesis,
        },
        hypothesis_card_id=hypothesis_card_id,
        next_hypothesis_card_id=next_hypothesis_card_id,
        next_action=next_action,
        context_summary_path=context_summary_path,
        reasoning=reasoning,
        created_at=utcnow(),
    )
    db.add(row)
    db.flush()
    return row
