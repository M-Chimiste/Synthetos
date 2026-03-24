"""Autonomous experiment loop: step coordinator and completion report."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.adapters.llm.gateway import ModelGateway
from libs.core.budget import check_budget
from libs.core.config import AppConfig
from libs.core.operators import (
    NextAction,
    OperatorReport,
    OperatorResult,
    StatePatch,
)
from libs.core.policy import Actor, load_autonomy_policy
from libs.core.state_machine import CycleStatus
from libs.ideation.hypothesis_lifecycle import (
    pick_next_hypothesis,
    transition_hypothesis,
)
from libs.orchestration.autonomous_payload import merge_autonomous_payload
from libs.orchestration.loop_decision import (
    LoopDecision,
    LoopDecisionResult,
    decide_next_step,
)
from libs.orchestration.repetition import (
    RepetitionCheck,
    check_result_repetition,
)
from libs.schemas.domain import SuccessCriteria
from libs.storage.models import (
    ExperimentSpecModel,
    HypothesisCardModel,
    JobModel,
    MetricFrontierModel,
    ResearchCharterModel,
    ResearchCycleModel,
    RunRecordModel,
    VerificationReportModel,
)
from libs.storage.services import append_event

log = structlog.get_logger(__name__)


# ------------------------------------------------------------------
# Autonomous loop step operator
# ------------------------------------------------------------------


def autonomous_loop_step_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    """One iteration of the autonomous experiment loop.

    Reads the result of the last run (if any), makes a decision, and
    enqueues the next action (run, pivot, regenerate, or complete).
    """
    payload = merge_autonomous_payload(job.payload)
    iteration = payload["autonomous_loop_iteration"]
    last_run_pid = payload.get("last_run_public_id")
    last_hyp_pid = payload.get("last_hypothesis_public_id")
    selected_hyp_pid = payload.get("selected_hypothesis_public_id") or last_hyp_pid
    regeneration_attempted = payload.get("regeneration_attempted", False)

    charter = session.get(ResearchCharterModel, cycle.charter_id)
    raw_policy = _load_raw_policy(config)
    autonomy_policy = load_autonomy_policy(raw_policy)
    verification_policy = raw_policy.get("verification", {})
    min_outcome_for_promotion = str(
        verification_policy.get("min_outcome_for_promotion", "tentative")
    )

    # -- Load last run context if available --
    directional_signal: str | None = None
    verification_outcome: str | None = None
    tradeoff_resolution: dict[str, Any] | None = None
    last_run: RunRecordModel | None = None
    if last_run_pid:
        last_run = session.scalar(
            select(RunRecordModel).where(
                RunRecordModel.public_id == last_run_pid,
            )
        )
        if last_run:
            verification_outcome = last_run.verification_outcome
            vr = session.scalar(
                select(VerificationReportModel).where(
                    VerificationReportModel.run_record_id == last_run.id,
                ).order_by(VerificationReportModel.created_at.desc())
            )
            if vr:
                directional_signal = vr.directional_signal
                reconciliation = (vr.directional_signal_detail or {}).get("reconciliation", {})
                if isinstance(reconciliation, dict):
                    tradeoff_resolution = reconciliation.get("tradeoff_resolution")

    # -- Resolve current hypothesis --
    current_hyp: HypothesisCardModel | None = None
    if selected_hyp_pid:
        current_hyp = session.scalar(
            select(HypothesisCardModel).where(
                HypothesisCardModel.public_id == selected_hyp_pid,
            )
        )

    # -- Budget check --
    budget_status = check_budget(
        cycle,
        hypothesis_public_id=current_hyp.public_id if current_hyp else selected_hyp_pid,
    )

    # -- Repetition check --
    repetition = RepetitionCheck(is_repetition=False)
    if current_hyp and last_run:
        sc = _parse_success_criteria(charter)
        repetition = check_result_repetition(
            session,
            cycle_id=cycle.id,
            hypothesis_id=current_hyp.id,
            primary_metric=sc.primary_metric if sc else "accuracy",
            noise_threshold_pct=(
                (sc.significance_threshold * 100) if sc else 1.0
            ),
        )

    # -- Count runs for current hypothesis --
    hyp_run_count = (cycle.budget_runs_per_hypothesis or {}).get(
        (current_hyp.public_id if current_hyp else selected_hyp_pid) or "", 0,
    )

    # -- Check success criteria --
    success_met = _check_success_criteria(
        charter,
        last_run,
        current_hyp,
        session,
        min_outcome_for_promotion=min_outcome_for_promotion,
    )

    # -- Check for portfolio alternatives --
    alt_hyp = pick_next_hypothesis(
        session,
        cycle_id=cycle.id,
        charter_id=charter.id if charter else None,
        exclude_hypothesis_id=(
            current_hyp.id if current_hyp else None
        ),
    )

    # -- Decision --
    decision = decide_next_step(
        autonomy_policy=autonomy_policy,
        budget_status=budget_status,
        directional_signal=directional_signal,
        verification_outcome=verification_outcome,
        repetition_check=repetition,
        hypothesis_run_count=hyp_run_count,
        max_runs_per_hypothesis=cycle.budget_max_runs_per_hypothesis,
        portfolio_has_alternatives=alt_hyp is not None,
        regeneration_attempted=regeneration_attempted,
        success_criteria_met=success_met,
        tradeoff_resolution=tradeoff_resolution,
        has_last_run=last_run is not None,
    )

    if current_hyp:
        _apply_loop_transition(
            session=session,
            hypothesis=current_hyp,
            decision=decision,
            directional_signal=directional_signal,
            verification_outcome=verification_outcome,
            tradeoff_resolution=tradeoff_resolution,
            success_met=success_met,
            hypothesis_run_count=hyp_run_count,
            max_runs_per_hypothesis=cycle.budget_max_runs_per_hypothesis,
        )

    # -- Record decision as domain event --
    append_event(
        session,
        actor=actor,
        event_type="autonomous_loop_decision",
        payload={
            "iteration": iteration,
            "decision": decision.decision.value,
            "reason": decision.reason,
            "hypothesis_public_id": current_hyp.public_id if current_hyp else selected_hyp_pid,
            "directional_signal": directional_signal,
            "verification_outcome": verification_outcome,
            "budget_within": budget_status.within_budget,
        },
        cycle_id=cycle.id,
        job_id=job.id,
    )

    # -- Execute decision --
    next_actions: list[NextAction] = []
    report_lines = [
        f"# Autonomous Loop — Iteration {iteration}",
        "",
        f"**Decision:** {decision.decision.value}",
        f"**Reason:** {decision.reason}",
        f"**Signal:** {directional_signal or 'N/A'}",
        f"**Budget remaining runs:** {budget_status.remaining_runs}",
        "",
    ]

    if decision.decision in {
        LoopDecision.BUDGET_EXHAUSTED,
        LoopDecision.SUCCESS_CRITERIA_MET,
        LoopDecision.ESCALATE,
    }:
        # Terminal — enqueue completion report
        next_actions.append(NextAction(
            action="autonomous_loop_completion",
            payload=merge_autonomous_payload(
                {
                    "cycle_public_id": cycle.public_id,
                    "total_iterations": iteration,
                    "termination_reason": decision.reason,
                },
                autonomous_loop_iteration=iteration,
                selected_hypothesis_public_id=(
                    current_hyp.public_id if current_hyp else selected_hyp_pid
                ),
                last_hypothesis_public_id=(
                    current_hyp.public_id if current_hyp else last_hyp_pid
                ),
                last_run_public_id=last_run_pid,
                regeneration_attempted=regeneration_attempted,
            ),
        ))
    elif decision.decision == LoopDecision.REGENERATE_PORTFOLIO:
        # Re-run literature intake pipeline
        source_scope = charter.source_scope if charter else {}
        next_actions.append(NextAction(
            action="source_retrieval",
            payload=merge_autonomous_payload(
                {
                    "cycle_public_id": cycle.public_id,
                    "source_scope": source_scope,
                },
                autonomous_loop_iteration=iteration,
                autonomous_regeneration=True,
                selected_hypothesis_public_id=None,
                parameter_variation_hints=[],
                variation_mode=False,
            ),
        ))
    elif decision.decision == LoopDecision.PIVOT_HYPOTHESIS:
        # Transition current hypothesis and pick next
        target_hyp = alt_hyp
        if target_hyp:
            if target_hyp.status in {"approved", "compiled"}:
                transition_hypothesis(
                    session, target_hyp, "active",
                    reason="Selected by autonomous loop pivot",
                )
            next_actions.extend(
                _enqueue_experiment_for_hypothesis(
                    session=session,
                    config=config,
                    actor=actor,
                    cycle=cycle,
                    hypothesis=target_hyp,
                    iteration=iteration,
                    base_payload=payload,
                    parameter_variation_hints=[],
                    variation_mode=False,
                )
            )
            report_lines.append(
                f"**Pivoted to:** {target_hyp.title} "
                f"({target_hyp.public_id})",
            )
    else:
        # CONTINUE_SAME or VARY_PARAMETERS
        hyp = current_hyp
        if hyp is None:
            # First iteration — pick top hypothesis
            hyp = pick_next_hypothesis(
                session,
                cycle_id=cycle.id,
                charter_id=charter.id if charter else None,
            )
        if hyp is None:
            # No hypotheses available at all
            next_actions.append(NextAction(
                action="autonomous_loop_completion",
                payload={
                    "cycle_public_id": cycle.public_id,
                    "total_iterations": iteration,
                    "termination_reason": "No hypotheses available",
                },
            ))
        else:
            if hyp.status in {"approved", "compiled"}:
                transition_hypothesis(
                    session, hyp, "active",
                    reason="Selected by autonomous loop",
                )
            next_actions.extend(
                _enqueue_experiment_for_hypothesis(
                    session=session,
                    config=config,
                    actor=actor,
                    cycle=cycle,
                    hypothesis=hyp,
                    iteration=iteration,
                    base_payload=payload,
                    parameter_variation_hints=decision.parameter_variation_hints or [],
                    variation_mode=decision.decision == LoopDecision.VARY_PARAMETERS,
                )
            )

    # Update cycle resume payload with loop state
    cycle.resume_payload = {
        "autonomous_loop": {
            "iteration": iteration,
            "last_decision": decision.decision.value,
            "last_reason": decision.reason,
            "selected_hypothesis_public_id": (
                current_hyp.public_id if current_hyp else selected_hyp_pid
            ),
        },
    }

    target_state = (
        CycleStatus.READY
        if not next_actions
        else CycleStatus.QUEUED
    )

    return OperatorResult(
        state_patch=StatePatch(
            target_state=target_state,
            reason=f"Autonomous loop iteration {iteration}: "
            f"{decision.decision.value}",
            context={
                "iteration": iteration,
                "decision": decision.decision.value,
            },
        ),
        emitted_events=[
            {
                "event_type": "autonomous_loop_step_completed",
                "payload": {
                    "iteration": iteration,
                    "decision": decision.decision.value,
                },
            },
        ],
        next_actions=next_actions,
        operator_report=OperatorReport(
            title=f"Autonomous Loop Step {iteration}",
            prompt_id="autonomous_loop_step",
            report_type="autonomous_loop_step",
            body_markdown="\n".join(report_lines),
        ),
    )


# ------------------------------------------------------------------
# Completion report operator
# ------------------------------------------------------------------


def autonomous_loop_completion_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    """Generate a completion report for an autonomous experiment loop."""
    payload = merge_autonomous_payload(job.payload)
    total_iterations = payload.get("total_iterations", 0)
    termination_reason = payload.get(
        "termination_reason", "Unknown",
    )

    charter = session.get(ResearchCharterModel, cycle.charter_id)
    success_criteria = _parse_success_criteria(charter)

    # Gather all hypotheses for this cycle
    hypotheses = list(
        session.scalars(
            select(HypothesisCardModel).where(
                HypothesisCardModel.cycle_id == cycle.id,
            ).order_by(HypothesisCardModel.portfolio_rank.asc())
        ).all()
    )

    # Gather all runs for this cycle
    runs = list(
        session.scalars(
            select(RunRecordModel).where(
                RunRecordModel.cycle_id == cycle.id,
            ).order_by(RunRecordModel.created_at.asc())
        ).all()
    )

    # Gather metric frontiers
    frontiers = list(
        session.scalars(
            select(MetricFrontierModel).where(
                MetricFrontierModel.charter_id == charter.id,
            )
        ).all()
    ) if charter else []
    frontier_by_hypothesis = {
        frontier.hypothesis_card_id: frontier for frontier in frontiers
    }

    from libs.storage.models import ReportBundleModel, VerificationReportModel
    from libs.storage.services import create_report

    experiment_reports = list(
        session.scalars(
            select(ReportBundleModel)
            .where(
                ReportBundleModel.cycle_id == cycle.id,
                ReportBundleModel.report_type == "experiment_writeup",
            )
            .order_by(ReportBundleModel.created_at.asc())
        ).all()
    )

    hypotheses_summary: list[dict[str, Any]] = []
    for hyp in hypotheses:
        hyp_specs = list(
            session.scalars(
                select(ExperimentSpecModel.id).where(
                    ExperimentSpecModel.cycle_id == cycle.id,
                    ExperimentSpecModel.hypothesis_card_id == hyp.id,
                )
            ).all()
        )
        hyp_runs = [
            run for run in runs
            if run.experiment_spec_id and run.experiment_spec_id in hyp_specs
        ]
        latest_signal = None
        if hyp_runs:
            latest_report = session.scalar(
                select(VerificationReportModel)
                .where(VerificationReportModel.run_record_id == hyp_runs[-1].id)
                .order_by(VerificationReportModel.created_at.desc())
            )
            latest_signal = latest_report.directional_signal if latest_report else None
        best_metric = None
        if success_criteria:
            numeric_values = [
                float(run.metrics_summary.get(success_criteria.primary_metric))
                for run in hyp_runs
                if isinstance(
                    (run.metrics_summary or {}).get(success_criteria.primary_metric),
                    (int, float),
                )
            ]
            if numeric_values:
                best_metric = (
                    max(numeric_values)
                    if success_criteria.primary_higher_is_better
                    else min(numeric_values)
                )
        frontier = frontier_by_hypothesis.get(hyp.id)
        hypotheses_summary.append({
            "title": hyp.title,
            "status": hyp.status,
            "run_count": len(hyp_runs),
            "best_metric": best_metric if best_metric is not None else (
                frontier.best_value if frontier else None
            ),
            "last_signal": latest_signal,
            "public_id": hyp.public_id,
        })

    writeup_summaries: list[dict[str, Any]] = []
    for report in experiment_reports[-5:]:
        excerpt = ""
        try:
            excerpt = Path(report.artifact_path).read_text(encoding="utf-8")[:1200]
        except OSError:
            excerpt = ""
        writeup_summaries.append({
            "title": report.title,
            "run_record_id": report.run_record_id,
            "hypothesis_card_id": report.hypothesis_card_id,
            "excerpt": excerpt,
        })

    prompt_id = "prompts/reporting/v1/autonomous_completion.md"
    body_markdown = ""
    try:
        from jinja2 import Template

        gateway = ModelGateway.from_config(config)
        template_text = Path(prompt_id).read_text(encoding="utf-8")
        rendered = Template(template_text).render(
            charter_title=charter.title if charter else "N/A",
            problem_statement=charter.problem_statement if charter else "N/A",
            total_iterations=total_iterations,
            total_runs=len(runs),
            termination_reason=termination_reason,
            compute_used_minutes=cycle.budget_used_compute_minutes,
            compute_budget_minutes=cycle.budget_max_compute_minutes,
            runs_used=cycle.budget_used_run_count,
            runs_budget=cycle.budget_max_total_runs,
            hypotheses=hypotheses_summary,
            frontiers=[
                {
                    "metric_name": frontier.metric_name,
                    "best_value": frontier.best_value,
                    "best_run_public_id": frontier.best_run_public_id,
                    "runs_since_improvement": frontier.runs_since_improvement,
                }
                for frontier in frontiers
            ],
            experiment_writeups=writeup_summaries,
        )
        llm_report = gateway.call_chat_completion(
            "reporter",
            [{"role": "user", "content": rendered}],
            temperature=0.3,
            max_tokens=2048,
        )
        body_markdown = llm_report.strip()
    except Exception:
        log.warning("autonomous_completion_report_llm_failed", cycle_public_id=cycle.public_id)

    if not body_markdown:
        report_lines = [
            "# Autonomous Experiment Loop - Completion Report",
            "",
            f"**Charter:** {charter.title if charter else 'N/A'}",
            f"**Problem:** {charter.problem_statement if charter else 'N/A'}",
            f"**Total iterations:** {total_iterations}",
            f"**Total runs:** {len(runs)}",
            f"**Termination reason:** {termination_reason}",
            "",
            "## Budget Utilization",
            "",
            f"- Compute used: {cycle.budget_used_compute_minutes:.1f}"
            f" / {cycle.budget_max_compute_minutes or '∞'} minutes",
            f"- Runs used: {cycle.budget_used_run_count}"
            f" / {cycle.budget_max_total_runs or '∞'}",
            f"- Wall-clock budget: {cycle.budget_max_wall_clock_hours or '∞'} hours",
            "",
            "## Hypotheses Explored",
            "",
        ]
        for hyp in hypotheses_summary:
            report_lines.extend([
                f"### {hyp['title']}",
                f"- **Status:** {hyp['status']}",
                f"- **Runs:** {hyp['run_count']}",
                (
                    f"- **Best metric:** "
                    f"{hyp['best_metric'] if hyp['best_metric'] is not None else 'N/A'}"
                ),
                f"- **Last signal:** {hyp['last_signal'] or 'N/A'}",
                "",
            ])
        if frontiers:
            report_lines.extend(["## Metric Frontiers", ""])
            for frontier in frontiers:
                report_lines.append(
                    f"- **{frontier.metric_name}:** {frontier.best_value} "
                    f"(run: {frontier.best_run_public_id}, "
                    f"stall: {frontier.runs_since_improvement})"
                )
            report_lines.append("")
        if writeup_summaries:
            report_lines.extend(["## Experiment Results", ""])
            for writeup in writeup_summaries:
                report_lines.extend([
                    f"### {writeup['title']}",
                    writeup["excerpt"] or "Writeup artifact available but could not be read.",
                    "",
                ])
        body_markdown = "\n".join(report_lines)

    completion_report = create_report(
        session, config,
        cycle=cycle, job=job,
        title="Autonomous Loop Completion Report",
        report_type="autonomous_completion_report",
        body_markdown=body_markdown,
    )

    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.READY,
            reason=f"Autonomous loop completed: {termination_reason}",
            context={
                "total_iterations": total_iterations,
                "termination_reason": termination_reason,
                "report_public_id": completion_report.public_id,
            },
        ),
        emitted_events=[
            {
                "event_type": "autonomous_loop_completed",
                "payload": {
                    "cycle_public_id": cycle.public_id,
                    "total_iterations": total_iterations,
                    "termination_reason": termination_reason,
                    "report_public_id": completion_report.public_id,
                },
            },
        ],
        operator_report=OperatorReport(
            title="Autonomous Loop Completion",
            prompt_id="autonomous_loop_completion",
            report_type="autonomous_completion_report",
            body_markdown=body_markdown,
        ),
    )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _load_raw_policy(config: AppConfig) -> dict[str, Any]:
    """Load raw policy dict from config."""
    import yaml
    policy_path = config.policy_config_path
    if policy_path and policy_path.exists():
        return yaml.safe_load(policy_path.read_text()) or {}
    return {}


def _parse_success_criteria(
    charter: ResearchCharterModel | None,
) -> SuccessCriteria | None:
    """Parse charter success_criteria into typed model."""
    if not charter or not charter.success_criteria:
        return None
    try:
        return SuccessCriteria.model_validate(charter.success_criteria)
    except Exception:
        return None


def _check_success_criteria(
    charter: ResearchCharterModel | None,
    last_run: RunRecordModel | None,
    hypothesis: HypothesisCardModel | None,
    session: Session,
    *,
    min_outcome_for_promotion: str,
) -> bool:
    """Check if the latest run meets the charter's success criteria."""
    sc = _parse_success_criteria(charter)
    if not sc or not last_run:
        return False
    if sc.target_value is None:
        return False
    if _outcome_rank(last_run.verification_outcome) < _outcome_rank(min_outcome_for_promotion):
        return False

    metrics = last_run.metrics_summary or {}
    primary_val = metrics.get(sc.primary_metric)
    if not isinstance(primary_val, (int, float)):
        return False
    if sc.primary_higher_is_better:
        if float(primary_val) < sc.target_value:
            return False
    elif float(primary_val) > sc.target_value:
        return False

    for cm in sc.constraint_metrics:
        cm_val = metrics.get(cm.name)
        if not isinstance(cm_val, (int, float)):
            continue
        if cm.upper_bound is not None and float(cm_val) > cm.upper_bound:
            return False
        if cm.lower_bound is not None and float(cm_val) < cm.lower_bound:
            return False

    return True


def _outcome_rank(outcome: str | None) -> int:
    ordering = {
        "invalid": 0,
        "rejected": 1,
        "tentative": 2,
        "robust": 3,
    }
    return ordering.get(str(outcome or "").lower(), -1)


def _apply_loop_transition(
    *,
    session: Session,
    hypothesis: HypothesisCardModel,
    decision: LoopDecisionResult,
    directional_signal: str | None,
    verification_outcome: str | None,
    tradeoff_resolution: dict[str, Any] | None,
    success_met: bool,
    hypothesis_run_count: int,
    max_runs_per_hypothesis: int | None,
) -> None:
    """Apply lifecycle transitions after the loop decision is made."""

    if success_met:
        if hypothesis.status == "active":
            try:
                transition_hypothesis(
                    session,
                    hypothesis,
                    "promising",
                    reason="Success criteria met",
                )
            except ValueError:
                pass
        if hypothesis.status == "promising":
            try:
                transition_hypothesis(
                    session,
                    hypothesis,
                    "validated",
                    reason="Success criteria met",
                )
            except ValueError:
                pass
        return

    if hypothesis.status == "active" and directional_signal == "breakthrough":
        try:
            transition_hypothesis(
                session,
                hypothesis,
                "promising",
                reason="Breakthrough signal detected",
            )
        except ValueError:
            pass

    if decision.decision != LoopDecision.PIVOT_HYPOTHESIS or hypothesis.status != "active":
        return

    at_cap = (
        max_runs_per_hypothesis is not None
        and hypothesis_run_count >= max_runs_per_hypothesis
    )
    resolution = (tradeoff_resolution or {}).get("resolution")
    if directional_signal == "stalled" and at_cap:
        target_status = "stalled"
        reason = f"Stalled at per-hypothesis cap ({hypothesis_run_count})"
    elif resolution == "reject_tradeoff":
        target_status = "deprioritized"
        reason = "Rejected due to unacceptable metric tradeoff"
    elif directional_signal == "regressing" or verification_outcome in {"invalid", "rejected"}:
        target_status = "deprioritized"
        reason = (
            f"Verification outcome {verification_outcome or directional_signal} "
            "triggered pivot"
        )
    else:
        return

    try:
        transition_hypothesis(session, hypothesis, target_status, reason=reason)
    except ValueError:
        pass


def _enqueue_experiment_for_hypothesis(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    hypothesis: HypothesisCardModel,
    iteration: int,
    base_payload: dict[str, Any] | None,
    parameter_variation_hints: list[dict[str, Any]],
    variation_mode: bool,
) -> list[NextAction]:
    """Find or create an experiment spec and enqueue run_prepare."""
    from libs.schemas.api import RunCreateRequest
    from libs.storage.services import create_run_from_experiment_spec

    loop_payload = merge_autonomous_payload(base_payload)

    if variation_mode:
        return [
            NextAction(
                action="protocol_compilation",
                payload=merge_autonomous_payload(
                    loop_payload,
                    cycle_public_id=cycle.public_id,
                    autonomous_loop_iteration=iteration,
                    selected_hypothesis_public_id=hypothesis.public_id,
                    last_hypothesis_public_id=hypothesis.public_id,
                    parameter_variation_hints=parameter_variation_hints,
                    variation_mode=True,
                ),
            ),
        ]

    # Find the latest valid spec for this hypothesis
    spec = session.scalar(
        select(ExperimentSpecModel).where(
            ExperimentSpecModel.cycle_id == cycle.id,
            ExperimentSpecModel.hypothesis_card_id == hypothesis.id,
            ExperimentSpecModel.status.in_({"valid", "approved"}),
        ).order_by(ExperimentSpecModel.created_at.desc())
    )

    if spec is None:
        # No spec available — need protocol compilation first
        return [
            NextAction(
                action="protocol_compilation",
                payload=merge_autonomous_payload(
                    loop_payload,
                    cycle_public_id=cycle.public_id,
                    autonomous_loop_iteration=iteration,
                    selected_hypothesis_public_id=hypothesis.public_id,
                    last_hypothesis_public_id=hypothesis.public_id,
                    parameter_variation_hints=parameter_variation_hints,
                    variation_mode=False,
                ),
            ),
        ]

    # Create a run from the spec
    try:
        run_payload = RunCreateRequest(
            execution_profile=(
                spec.resource_requirements.get("execution_profile", "cpu-small")
                if spec.resource_requirements
                else "cpu-small"
            ),
        )
        run = create_run_from_experiment_spec(
            session, actor, config, spec.public_id, run_payload,
        )
        return [
            NextAction(
                action="run_prepare",
                payload=merge_autonomous_payload(
                    loop_payload,
                    run_public_id=run.public_id,
                    autonomous_loop_iteration=iteration,
                    selected_hypothesis_public_id=hypothesis.public_id,
                    last_hypothesis_public_id=hypothesis.public_id,
                    last_run_public_id=None,
                    parameter_variation_hints=[],
                    variation_mode=False,
                ),
            ),
        ]
    except Exception as exc:
        log.warning(
            "autonomous_loop_run_creation_failed",
            error=str(exc),
            spec_public_id=spec.public_id,
        )
        return [
            NextAction(
                action="autonomous_loop_completion",
                payload=merge_autonomous_payload(
                    {
                        "cycle_public_id": cycle.public_id,
                        "total_iterations": iteration,
                        "termination_reason": f"Run creation failed: {exc}",
                    },
                    autonomous_loop_iteration=iteration,
                    selected_hypothesis_public_id=hypothesis.public_id,
                    last_hypothesis_public_id=hypothesis.public_id,
                ),
            ),
        ]


def _spec_has_hypothesis(
    session: Session,
    spec_id: int,
    hypothesis_id: int,
) -> bool:
    """Check if an experiment spec is linked to a hypothesis."""
    spec = session.get(ExperimentSpecModel, spec_id)
    return spec is not None and spec.hypothesis_card_id == hypothesis_id
