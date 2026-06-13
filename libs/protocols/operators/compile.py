"""protocol_compile operator -- compiles selected hypotheses into executable
ExperimentSpec rows, validates completeness, and transitions the cycle
to protocol_ready.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from uuid_utils import uuid7

from libs.adapters.llm.router import ModelRouter
from libs.autonomy.budget import load_or_create_budget
from libs.autonomy.gates import GateContext, evaluate_gates, preview_next_spec
from libs.autonomy.policy import AutonomyPolicy
from libs.core.clock import utcnow
from libs.core.container_images import (
    BLACKWELL_PYTORCH_IMAGE,
    DEFAULT_CPU_IMAGE,
    default_base_image_for_hardware,
    dependencies_satisfied_by_base_image,
    gpu_requested,
    package_name,
)
from libs.core.errors import OperationCancelled, OperatorTimeout
from libs.core.event_types import AutonomyEvents, ProtocolEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.core.types import CycleStatus, JobStatus
from libs.discovery.skill_support import join_skill_prompts, load_skill_prompt
from libs.prompts import render_prompt
from libs.protocols.validation import validate_spec
from libs.schemas.model_gateway import ModelRole
from libs.skills.lineage import record_model_call, record_skill_usage
from libs.storage.base import get_sync_session_factory
from libs.storage.models.autonomy import LoopDecision
from libs.storage.models.experiment import (
    ExperimentSpec,
    HypothesisCard,
    HypothesisSession,
    RunRecord,
)
from libs.storage.models.jobs import Job
from libs.storage.models.research import ResearchCharter, ResearchCycle

log = get_logger("protocols.compile")

# ---------------------------------------------------------------------------
# LLM-facing stage models. The compile is decomposed per hypothesis into
# (1) plan -> (2) code -> (3 optional) custom build recipe: a single
# small-model call can produce one flat plan or one script reliably, where the
# old "N complete specs with code and Dockerfiles in one response" could not.
# ---------------------------------------------------------------------------


class MetricSpec(BaseModel):
    name: str = Field(description="snake_case metric key written to /artifacts/metrics.json")
    direction: Literal["maximize", "minimize"]
    threshold: float | None = Field(default=None, description="Pass/fail cutoff; null if none")


class BaselineSpec(BaseModel):
    description: str = Field(description="What the no-hypothesis baseline is and why")
    expected_metrics: dict[str, float] = Field(
        default_factory=dict, description="metric_name -> expected baseline value"
    )


class ControlSetting(BaseModel):
    name: str
    value: float | int | str


class ExpectedArtifact(BaseModel):
    name: str = Field(description="Filename under /artifacts, e.g. metrics.json")
    required: bool = True


class StopCondition(BaseModel):
    description: str = Field(description="e.g. 'stop after 200 training steps'")


class ExperimentPlan(BaseModel):
    """Stage 1 output: flat experiment design. No code, no Dockerfile."""

    title: str = Field(max_length=500)
    description: str
    baseline: BaselineSpec
    controls: list[ControlSetting] = Field(default_factory=list)
    metrics: list[MetricSpec] = Field(min_length=1)
    expected_artifacts: list[ExpectedArtifact] = Field(default_factory=list)
    stop_conditions: list[StopCondition] = Field(min_length=1)
    dependencies: list[str] = Field(
        default_factory=list, description="pip package names the code will import"
    )
    approach_summary: str = Field(
        description="3-5 sentence implementation sketch handed to the code generator"
    )


class CodeFile(BaseModel):
    path: str = Field(description="Relative path, e.g. run_experiment.py")
    content: str


class CodePlanOutput(BaseModel):
    """Stage 2 output. A typed file list (not dict[str, str]): dynamic dict
    keys interact badly with json_schema-constrained decoding on llama.cpp."""

    entry_point: str = "run_experiment.py"
    files: list[CodeFile] = Field(min_length=1)


class BuildRecipeOutput(BaseModel):
    """Stage 3 output (rare; the default pip-install recipe needs no LLM)."""

    dockerfile_content: str


class _CompiledSpec(BaseModel):
    """Internal interchange container, assembled from the stage outputs.

    Field shapes are unchanged from the original single-call schema -- every
    downstream consumer (validate_spec, ExperimentSpec JSONB columns, setup,
    verification, repetition fingerprinting) sees identical dicts.
    """

    title: str = Field(max_length=500)
    description: str
    baseline: dict[str, Any]
    controls: list[dict[str, Any]] = Field(default_factory=list)
    metrics: list[dict[str, Any]]
    expected_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    stop_conditions: list[dict[str, Any]] = Field(default_factory=list)
    code_plan: dict[str, Any]
    base_image: str | None = None
    build_recipe: dict[str, Any] | None = None
    # 0-based position of the source hypothesis; None for legacy/test
    # constructions, which fall back to zip-order matching.
    hypothesis_index: int | None = None


class _SpecSet(BaseModel):
    specs: list[_CompiledSpec]


def _hardware_hint(hardware_profile: dict[str, Any] | None, base_image: str | None) -> str:
    hw_hint = ""
    if hardware_profile:
        hw_hint = f"\nHardware profile: {hardware_profile}"
        if gpu_requested(hardware_profile) and not base_image:
            hw_hint += f"\nRecommended GPU base image: {BLACKWELL_PYTORCH_IMAGE}"
    if base_image:
        hw_hint += f"\nBase image: {base_image}"
    return hw_hint


def _variation_hint(variation_context: dict[str, Any] | None) -> str:
    if not variation_context:
        return ""
    hint = (
        "\n\nPrevious attempt results:\n"
        f"- Signal: {variation_context.get('signal', 'unknown')}\n"
        f"- Best frontier value: {variation_context.get('frontier_best', 'N/A')}\n"
        f"- Recommendation: {variation_context.get('recommendation_action', '')}\n"
        f"- This is variation #{variation_context.get('variation_number', 1)}.\n"
        "\nDesign a NEW experiment that addresses the stall/regression by "
        "varying hyperparameters, architecture choices, or training strategy. "
        "Do NOT repeat the same configuration."
    )
    prior_metrics = variation_context.get("prior_metrics")
    if prior_metrics:
        hint += f"\n- Metrics achieved: {prior_metrics}"
    context_summary = variation_context.get("context_summary")
    if context_summary:
        key_findings = context_summary.get("key_findings", "")
        if key_findings:
            hint += f"\n- Loop findings: {key_findings}"
        repeated = context_summary.get("repeated_approaches", [])
        if repeated:
            hint += "\n- Repeated approaches: " + "; ".join(repeated)
    return hint


def _fixture_required_artifacts(fixture_expected: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalize fixture expected.required_artifacts into spec artifact dicts."""
    if not fixture_expected:
        return []
    raw_artifacts = fixture_expected.get("required_artifacts") or []
    if not isinstance(raw_artifacts, list):
        return []

    artifacts: list[dict[str, Any]] = []
    for raw in raw_artifacts:
        if isinstance(raw, str):
            name = raw.strip()
            if name:
                artifacts.append({"name": name, "required": True})
            continue
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("path") or "").strip()
        if not name:
            continue
        artifact = dict(raw)
        artifact["name"] = name.rsplit("/", 1)[-1]
        artifact["required"] = bool(raw.get("required", True))
        artifacts.append(artifact)
    return artifacts


def _artifact_key(artifact: dict[str, Any]) -> str:
    name = str(artifact.get("name") or artifact.get("path") or "").strip()
    return name.rsplit("/", 1)[-1]


def _merge_expected_artifacts(
    *artifact_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge plan-authored artifacts with fixture-required artifacts by filename."""
    merged: dict[str, dict[str, Any]] = {}
    for group in artifact_groups:
        for raw_artifact in group:
            if not isinstance(raw_artifact, dict):
                continue
            key = _artifact_key(raw_artifact)
            if not key:
                continue
            artifact = dict(raw_artifact)
            artifact["name"] = key
            artifact["required"] = bool(raw_artifact.get("required", True))
            existing = merged.get(key)
            if existing is None:
                merged[key] = artifact
            else:
                existing["required"] = bool(existing.get("required", True)) or bool(
                    artifact.get("required", True)
                )
                for optional_key in ("path", "type"):
                    if optional_key not in existing and optional_key in artifact:
                        existing[optional_key] = artifact[optional_key]
    return list(merged.values())


def _format_expected_artifacts(artifacts: list[dict[str, Any]]) -> str:
    if not artifacts:
        return "- metrics.json (required: True)"
    lines = []
    for artifact in artifacts:
        name = str(artifact.get("name") or artifact.get("path") or "").strip()
        required = bool(artifact.get("required", True))
        lines.append(f"- {name} (required: {required})")
    return "\n".join(lines)


def _fixture_expectation_hint(fixture_expected: dict[str, Any] | None) -> str:
    if not fixture_expected:
        return ""
    required_artifacts = _fixture_required_artifacts(fixture_expected)
    reference_sources = fixture_expected.get("reference_sources") or []
    lines = ["Pilot fixture expectations:"]
    if required_artifacts:
        lines.append("Required /artifacts files:")
        lines.extend(f"- {artifact['name']}" for artifact in required_artifacts)
    if isinstance(reference_sources, list) and reference_sources:
        lines.append("Reference sources that should inform the experiment:")
        lines.extend(f"- {source}" for source in reference_sources)
    lines.append(
        "Copy every required artifact into expected_artifacts and design code that writes them."
    )
    return "\n".join(lines)


async def _compile_one_spec(
    router: ModelRouter,
    *,
    hypothesis: dict[str, Any],
    hypothesis_index: int,
    problem_statement: str,
    hardware_profile: dict[str, Any] | None,
    base_image: str | None,
    skill_prompt: str | None,
    variation_context: dict[str, Any] | None,
    fixture_expected: dict[str, Any] | None,
) -> _CompiledSpec:
    """Run the plan -> code chain for one hypothesis and assemble the spec.

    The build recipe is synthesized deterministically from dependencies in
    ``_normalize_compiled_spec`` -- no third LLM call on the happy path.
    """
    hw_hint = _hardware_hint(hardware_profile, base_image)

    # Stage 1: plan
    plan_system = render_prompt("protocols.compile_plan")
    plan_system = join_skill_prompts(plan_system, skill_prompt) or plan_system
    plan_user = (
        f"Problem: {problem_statement}\n\n"
        f"Hypothesis: {hypothesis['title']}\n"
        f"Statement: {hypothesis['statement']}\n"
        f"Rationale: {hypothesis['rationale']}\n"
        f"Scores - novelty: {hypothesis.get('novelty_score')}, "
        f"feasibility: {hypothesis.get('feasibility_score')}, "
        f"impact: {hypothesis.get('impact_score')}"
        f"{hw_hint}\n\n"
        f"{_fixture_expectation_hint(fixture_expected)}\n\n"
        "Design the experiment plan for this hypothesis."
        f"{_variation_hint(variation_context)}"
    )
    plan = await router.complete_structured(
        role=ModelRole.protocol_drafting,
        messages=[
            {"role": "system", "content": plan_system},
            {"role": "user", "content": plan_user},
        ],
        response_model=ExperimentPlan,
        temperature=0.3,
    )

    # Stage 2: code (the coding role -- typically the code-tuned local model)
    code_system = render_prompt("protocols.compile_code")
    code_system = join_skill_prompts(code_system, skill_prompt) or code_system
    metrics_text = "\n".join(
        f"- {m.name} ({m.direction}"
        + (f", threshold {m.threshold}" if m.threshold is not None else "")
        + ")"
        for m in plan.metrics
    )
    expected_artifacts = _merge_expected_artifacts(
        [a.model_dump() for a in plan.expected_artifacts],
        _fixture_required_artifacts(fixture_expected),
    )
    artifacts_text = _format_expected_artifacts(expected_artifacts)
    stop_text = "\n".join(f"- {s.description}" for s in plan.stop_conditions)
    code_user = (
        f"Experiment: {plan.title}\n"
        f"Description: {plan.description}\n\n"
        f"Implementation approach:\n{plan.approach_summary}\n\n"
        f"Metrics to report in /artifacts/metrics.json:\n{metrics_text}\n\n"
        f"Expected artifacts:\n{artifacts_text}\n\n"
        f"Stop conditions:\n{stop_text}\n\n"
        f"Allowed dependencies: {plan.dependencies or ['(stdlib, torch, numpy only)']}"
        f"{hw_hint}\n\n"
        "Write the complete experiment code."
    )
    code = await router.complete_structured(
        role=ModelRole.coding,
        messages=[
            {"role": "system", "content": code_system},
            {"role": "user", "content": code_user},
        ],
        response_model=CodePlanOutput,
        temperature=0.2,
    )

    return _CompiledSpec(
        title=plan.title,
        description=plan.description,
        baseline=plan.baseline.model_dump(),
        controls=[c.model_dump() for c in plan.controls],
        metrics=[m.model_dump() for m in plan.metrics],
        expected_artifacts=expected_artifacts,
        stop_conditions=[s.model_dump() for s in plan.stop_conditions],
        code_plan={
            "entry_point": code.entry_point,
            "files": {f.path: f.content for f in code.files},
            "dependencies": plan.dependencies,
            "expected_artifacts": expected_artifacts,
        },
        base_image=base_image,
        build_recipe=None,  # synthesized deterministically in normalization
        hypothesis_index=hypothesis_index,
    )


async def compile_build_recipe(
    router: ModelRouter,
    *,
    base_image: str,
    code_plan: dict[str, Any],
    skill_prompt: str | None = None,
) -> BuildRecipeOutput:
    """Stage 3: LLM-authored custom Dockerfile.

    Not part of the happy path (the deterministic pip-install recipe covers
    it); available for remediation/custom-build flows.
    """
    system = render_prompt("protocols.compile_build", base_image=base_image)
    system = join_skill_prompts(system, skill_prompt) or system
    files = code_plan.get("files") or {}
    user = (
        f"Code files: {sorted(files)}\n"
        f"Entry point: {code_plan.get('entry_point')}\n"
        f"Dependencies: {code_plan.get('dependencies') or []}\n\n"
        "Write the Dockerfile."
    )
    return await router.complete_structured(
        role=ModelRole.coding,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_model=BuildRecipeOutput,
        temperature=0.2,
    )


async def _compile_specs(
    hypotheses: list[dict[str, Any]],
    problem_statement: str,
    hardware_profile: dict[str, Any] | None,
    base_image: str | None,
    skill_prompt: str | None,
    variation_context: dict[str, Any] | None = None,
    fixture_expected: dict[str, Any] | None = None,
) -> tuple[_SpecSet, dict[str, Any]]:
    """Compile hypotheses into executable experiment specs, one chain per card.

    Per-card compilation makes failures partial: a hypothesis whose chain
    fails is logged and skipped instead of failing the whole job. Specs carry
    ``hypothesis_index`` so the caller never relies on output order.
    """
    router = ModelRouter()
    try:
        specs: list[_CompiledSpec] = []
        for i, hypothesis in enumerate(hypotheses):
            try:
                spec = await _compile_one_spec(
                    router,
                    hypothesis=hypothesis,
                    hypothesis_index=i,
                    problem_statement=problem_statement,
                    hardware_profile=hardware_profile,
                    base_image=base_image,
                    skill_prompt=skill_prompt,
                    variation_context=variation_context,
                    fixture_expected=fixture_expected,
                )
                specs.append(spec)
            except (OperationCancelled, OperatorTimeout):
                raise
            except Exception:
                log.warning(
                    "hypothesis_compile_failed",
                    hypothesis_index=i,
                    hypothesis_title=str(hypothesis.get("title", ""))[:120],
                    exc_info=True,
                )
        if not specs:
            raise RuntimeError("all hypothesis compile chains failed")
        return _SpecSet(specs=specs), router.get_role_config(ModelRole.protocol_drafting)
    finally:
        await router.close()


def protocol_compile_operator(op_input: OperatorInput) -> OperatorResult:
    factory = get_sync_session_factory()
    payload = op_input.payload

    # Protocol compile uses hypothesis_session_id or hypothesis_card_ids from payload
    hypothesis_session_id_raw = payload.get("hypothesis_session_id")
    if hypothesis_session_id_raw is None:
        return OperatorResult(success=False, error="missing hypothesis_session_id in payload")

    from uuid import UUID

    hypothesis_session_id = UUID(str(hypothesis_session_id_raw))
    hardware_profile = payload.get("hardware_profile")
    base_image = payload.get("base_image")
    explicit_card_ids = payload.get("hypothesis_card_ids")
    variation_context = payload.get("variation_context")
    from_loop = payload.get("from_loop", False)
    loop_context = payload.get("loop_context") or {}

    with factory() as db:
        hs = db.get(HypothesisSession, hypothesis_session_id)
        if hs is None:
            return OperatorResult(success=False, error="hypothesis session not found")

        charter = db.get(ResearchCharter, hs.charter_id)
        problem_statement = charter.problem_statement if charter else ""
        cycle = db.get(ResearchCycle, hs.cycle_id)
        cycle_config = (cycle.config or {}) if cycle else {}
        cycle_autonomy = cycle_config.get("autonomy", {})
        cycle_pilot = cycle_config.get("pilot", {})
        fixture_expected = (
            cycle_pilot.get("expected", {})
            if isinstance(cycle_pilot, dict)
            else {}
        )
        cycle_protocol = cycle_autonomy.get("protocol") or {}
        if hardware_profile is None:
            hardware_profile = cycle_protocol.get("hardware_profile") or cycle_autonomy.get(
                "compute_cap"
            )
        if base_image is None:
            base_image = cycle_protocol.get("base_image")

        # Select hypotheses: explicit IDs or top-ranked
        if explicit_card_ids:
            card_uuids = [UUID(str(cid)) for cid in explicit_card_ids]
            cards = (
                db.execute(
                    select(HypothesisCard)
                    .where(HypothesisCard.id.in_(card_uuids))
                    .where(HypothesisCard.hypothesis_session_id == hypothesis_session_id)
                    .where(HypothesisCard.cycle_id == hs.cycle_id)
                    .where(HypothesisCard.charter_id == hs.charter_id)
                )
                .scalars()
                .all()
            )
            if len(cards) != len(card_uuids):
                return OperatorResult(
                    success=False,
                    error=(
                        "one or more hypothesis_card_ids are out of scope for this "
                        "hypothesis session, cycle, or charter"
                    ),
                )
        else:
            # Default: top-ranked candidates. At 2 LLM calls per card on slow
            # local inference, the cap bounds compile wall-time; the loop path
            # only ever executes the first spec, so it compiles exactly one.
            max_specs = 1 if from_loop else int(cycle_protocol.get("max_specs_per_compile", 2))
            cards = (
                db.execute(
                    select(HypothesisCard)
                    .where(HypothesisCard.hypothesis_session_id == hypothesis_session_id)
                    .where(HypothesisCard.status.in_(["candidate", "selected"]))
                    .order_by(HypothesisCard.rank.asc().nulls_last())
                    .limit(max_specs)
                )
                .scalars()
                .all()
            )

        if not cards:
            return OperatorResult(success=False, error="no hypotheses available to compile")

        # Mark selected
        for card in cards:
            if card.status == "candidate":
                card.status = "selected"
                card.updated_at = utcnow()

        hypotheses_for_llm = [
            {
                "title": c.title,
                "statement": c.statement,
                "rationale": c.rationale,
                "novelty_score": c.novelty_score,
                "feasibility_score": c.feasibility_score,
                "impact_score": c.impact_score,
            }
            for c in cards
        ]

        planning_skill = load_skill_prompt(
            db,
            skill_id="ideation.experiment_planning",
            operator_type=op_input.job_type,
        )
        coding_skill = load_skill_prompt(
            db,
            skill_id="coding.experiment_coding",
            operator_type=op_input.job_type,
        )
        combined_skill_prompt = join_skill_prompts(planning_skill.prompt, coding_skill.prompt)
        if planning_skill.prompt:
            record_skill_usage(
                db,
                skill_id="ideation.experiment_planning",
                cycle_id=hs.cycle_id,
                operator_type=op_input.job_type,
                job_id=op_input.job_id,
            )
        if coding_skill.prompt:
            record_skill_usage(
                db,
                skill_id="coding.experiment_coding",
                cycle_id=hs.cycle_id,
                operator_type=op_input.job_type,
                job_id=op_input.job_id,
            )

        # Call LLM
        try:
            spec_set, role_cfg = asyncio.run(
                _compile_specs(
                    hypotheses_for_llm,
                    problem_statement,
                    hardware_profile,
                    base_image,
                    combined_skill_prompt,
                    variation_context=variation_context,
                    fixture_expected=fixture_expected,
                )
            )
        except Exception as exc:
            return OperatorResult(success=False, error=f"protocol compilation failed: {exc}")
        record_model_call(
            db,
            cycle_id=hs.cycle_id,
            job_id=op_input.job_id,
            role=ModelRole.protocol_drafting.value,
            provider=str(role_cfg.get("provider", "unknown")),
            model_id=str(role_cfg.get("model", "unknown")),
        )

        # Validate and persist specs. Specs carry hypothesis_index when the
        # per-card chain produced them (some cards may have failed and been
        # skipped); legacy/test SpecSets without indices match by zip order.
        compiled_ids = []
        rejected_count = 0

        if all(s.hypothesis_index is not None for s in spec_set.specs):
            card_spec_pairs = [
                (cards[s.hypothesis_index], s)
                for s in spec_set.specs
                if s.hypothesis_index is not None and s.hypothesis_index < len(cards)
            ]
        else:
            card_spec_pairs = list(zip(cards, spec_set.specs, strict=False))

        for card, compiled in card_spec_pairs:
            spec_data = compiled.model_dump()
            spec_data = _normalize_compiled_spec(
                spec_data,
                fallback_base_image=base_image,
                hardware_profile=hardware_profile,
            )
            validation = validate_spec(spec_data)

            spec = ExperimentSpec(
                id=uuid7(),
                hypothesis_card_id=card.id,
                charter_id=hs.charter_id,
                cycle_id=hs.cycle_id,
                title=compiled.title,
                description=compiled.description,
                baseline=compiled.baseline,
                controls=compiled.controls,
                metrics=compiled.metrics,
                expected_artifacts=compiled.expected_artifacts,
                stop_conditions=compiled.stop_conditions,
                code_plan=compiled.code_plan,
                hardware_profile=hardware_profile,
                base_image=spec_data.get("base_image"),
                build_recipe=spec_data.get("build_recipe"),
                created_at=utcnow(),
                updated_at=utcnow(),
            )

            if validation.valid:
                spec.status = "validated"
                card.status = "compiled"
                compiled_ids.append(spec.id)
                emit_event_sync(
                    db,
                    event_type=ProtocolEvents.spec_compiled.value,
                    charter_id=hs.charter_id,
                    cycle_id=hs.cycle_id,
                    payload={
                        "spec_id": str(spec.id),
                        "hypothesis_card_id": str(card.id),
                        "title": spec.title,
                    },
                )
            else:
                spec.status = "rejected"
                spec.rejection_reason = "; ".join(validation.errors)
                rejected_count += 1
                emit_event_sync(
                    db,
                    event_type=ProtocolEvents.spec_rejected.value,
                    charter_id=hs.charter_id,
                    cycle_id=hs.cycle_id,
                    payload={
                        "spec_id": str(spec.id),
                        "hypothesis_card_id": str(card.id),
                        "errors": validation.errors,
                    },
                )

            card.updated_at = utcnow()
            db.add(spec)

        emit_event_sync(
            db,
            event_type=ProtocolEvents.compilation_completed.value,
            charter_id=hs.charter_id,
            cycle_id=hs.cycle_id,
            payload={
                "compiled_count": len(compiled_ids),
                "rejected_count": rejected_count,
            },
        )
        db.commit()

    if not compiled_ids:
        return OperatorResult(
            success=False,
            error=f"all {rejected_count} specs were rejected as under-specified",
        )

    # Phase 5: when invoked from the autonomous loop, create a RunRecord
    # and enqueue execution_setup directly instead of transitioning state.
    if from_loop:
        from libs.execution.operators._common import enqueue_next

        first_spec_id = compiled_ids[0]
        state_patch: dict[str, str] = {}
        with factory() as db:
            spec_row = db.get(ExperimentSpec, first_spec_id)
            if spec_row is None:
                return OperatorResult(success=False, error="compiled spec not found")

            # Count existing runs for this spec to determine run_number
            from sqlalchemy import func as sa_func

            max_run_num = db.execute(
                select(sa_func.coalesce(sa_func.max(RunRecord.run_number), 0)).where(
                    RunRecord.experiment_spec_id == first_spec_id
                )
            ).scalar_one()

            new_run = RunRecord(
                id=uuid7(),
                experiment_spec_id=first_spec_id,
                charter_id=spec_row.charter_id,
                cycle_id=spec_row.cycle_id,
                run_number=max_run_num + 1,
                status="pending",
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.add(new_run)

            cycle = db.get(ResearchCycle, spec_row.cycle_id)
            if cycle and cycle.status == CycleStatus.portfolio_ready.value:
                state_patch = {"cycle_status": CycleStatus.protocol_ready.value}
            policy = AutonomyPolicy.model_validate(
                (cycle.config or {}).get("autonomy", {}) if cycle else {}
            )
            budget = load_or_create_budget(db, spec_row.cycle_id)
            preview = preview_next_spec(spec_row)
            gate_result = evaluate_gates(
                policy,
                budget,
                GateContext(
                    runs_since_last_gate=0,
                    wall_clock_elapsed_s=budget.wall_clock_elapsed_s,
                    current_hardware_profile=loop_context.get("current_hardware_profile"),
                    next_hardware_profile=preview.hardware_profile,
                    has_network_access=preview.has_network_access,
                ),
            )

            if gate_result.should_pause and gate_result.gate_name in (
                "before_hardware_escalation",
                "before_network_execution",
            ):
                paused_job = Job(
                    id=uuid7(),
                    cycle_id=spec_row.cycle_id,
                    job_type="loop_decide",
                    status=JobStatus.paused,
                    payload={"prepared_run_record_id": str(new_run.id)},
                    priority=10,
                    created_at=utcnow(),
                )
                db.add(paused_job)
                _persist_loop_gate(
                    db,
                    cycle=cycle,
                    new_spec=spec_row,
                    budget=budget,
                    loop_context=loop_context,
                    gate_name=gate_result.gate_name or "unknown",
                    reason=gate_result.reason,
                )
                emit_event_sync(
                    db,
                    event_type=AutonomyEvents.gate_triggered.value,
                    charter_id=spec_row.charter_id,
                    cycle_id=spec_row.cycle_id,
                    payload={
                        "gate_name": gate_result.gate_name,
                        "reason": gate_result.reason,
                        "prepared_run_record_id": str(new_run.id),
                        "spec_id": str(spec_row.id),
                    },
                )
                db.commit()
                return OperatorResult(
                    success=True,
                    summary=(
                        f"Compiled {len(compiled_ids)} specs from loop "
                        f"({rejected_count} rejected); paused before execution_setup "
                        f"at gate {gate_result.gate_name}"
                    ),
                    state_patch={"cycle_status": CycleStatus.loop_deciding.value},
                )

            enqueue_next(
                db,
                cycle_id=spec_row.cycle_id,
                next_job_type="execution_setup",
                run_record_id=new_run.id,
            )
            db.commit()

        return OperatorResult(
            success=True,
            summary=(
                f"Compiled {len(compiled_ids)} specs from loop "
                f"({rejected_count} rejected); enqueued execution_setup"
            ),
            state_patch=state_patch,
        )

    result = OperatorResult(
        success=True,
        summary=(
            f"Compiled {len(compiled_ids)} specs "
            f"({rejected_count} rejected); cycle -> protocol_ready"
        ),
        state_patch={"cycle_status": CycleStatus.protocol_ready.value},
    )
    result.add_event(
        ProtocolEvents.compilation_completed.value,
        {
            "compiled_count": len(compiled_ids),
            "rejected_count": rejected_count,
        },
    )
    return result


def _persist_loop_gate(
    db,
    *,
    cycle: ResearchCycle | None,
    new_spec: ExperimentSpec,
    budget,
    loop_context: dict[str, Any],
    gate_name: str,
    reason: str,
) -> None:
    run_record_id = loop_context.get("run_record_id")
    recommendation_id = loop_context.get("recommendation_id")
    if not run_record_id or not recommendation_id or cycle is None:
        return

    from uuid import UUID

    iteration_number = (
        db.execute(
            select(func.count())
            .select_from(LoopDecision)
            .where(LoopDecision.cycle_id == new_spec.cycle_id)
        ).scalar_one()
        + 1
    )

    decision = LoopDecision(
        id=uuid7(),
        cycle_id=new_spec.cycle_id,
        charter_id=new_spec.charter_id,
        run_record_id=UUID(str(run_record_id)),
        recommendation_id=UUID(str(recommendation_id)),
        iteration_number=iteration_number,
        decision="stop_gate",
        gate_triggered=gate_name,
        budget_snapshot={
            "total_runs": budget.total_runs,
            "wall_clock_elapsed_s": budget.wall_clock_elapsed_s,
            "runs_per_hypothesis": budget.runs_per_hypothesis,
        },
        hypothesis_card_id=UUID(str(loop_context["hypothesis_card_id"]))
        if loop_context.get("hypothesis_card_id")
        else None,
        next_hypothesis_card_id=new_spec.hypothesis_card_id,
        next_action="execution_setup",
        context_summary_path=loop_context.get("context_summary_path"),
        reasoning=reason,
        created_at=utcnow(),
    )
    db.add(decision)


def _normalize_compiled_spec(
    spec_data: dict[str, Any],
    *,
    fallback_base_image: str | None,
    hardware_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply executor-aware guardrails to LLM-authored protocol specs."""
    normalized = dict(spec_data)
    effective_base = normalized.get("base_image") or fallback_base_image
    if gpu_requested(hardware_profile) and effective_base in {None, "", DEFAULT_CPU_IMAGE}:
        effective_base = default_base_image_for_hardware(hardware_profile)
    normalized["base_image"] = effective_base

    code_plan = normalized.get("code_plan")
    dependencies = code_plan.get("dependencies") if isinstance(code_plan, dict) else None
    if dependencies and not dependencies_satisfied_by_base_image(
        dependencies,
        effective_base,
    ):
        build_recipe = normalized.get("build_recipe")
        dockerfile = ""
        if isinstance(build_recipe, dict):
            dockerfile = str(build_recipe.get("dockerfile_content") or "")
        if not dockerfile.strip():
            base = effective_base or default_base_image_for_hardware(hardware_profile)
            normalized["base_image"] = base
            normalized["build_recipe"] = {
                "dockerfile_content": _default_dependency_dockerfile(
                    base,
                    dependencies,
                )
            }

    if not dependencies_satisfied_by_base_image(dependencies or [], effective_base):
        return normalized

    build_recipe = normalized.get("build_recipe")
    if not isinstance(build_recipe, dict):
        return normalized

    dockerfile = str(build_recipe.get("dockerfile_content") or "")
    if _dockerfile_only_installs_preloaded_packages(dockerfile):
        normalized["build_recipe"] = None
    return normalized


def _default_dependency_dockerfile(base_image: str, dependencies: Any) -> str:
    packages = [
        str(dep).strip() for dep in dependencies if isinstance(dep, str) and str(dep).strip()
    ]
    if not packages:
        return f"FROM {base_image}\n"
    return f"FROM {base_image}\nRUN pip install --no-cache-dir " + " ".join(packages) + "\n"


def _dockerfile_only_installs_preloaded_packages(dockerfile: str) -> bool:
    """Return true for no-op Dockerfiles that only reinstall torch/numpy."""
    meaningful_lines = [
        line.strip()
        for line in dockerfile.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not meaningful_lines:
        return False

    saw_pip_install = False
    for line in meaningful_lines:
        lower = line.lower()
        if lower.startswith("from ") and (
            "synthetos:latest" in lower or "pytorch/pytorch:" in lower
        ):
            continue
        if lower.startswith("run ") and "pip install" in lower:
            saw_pip_install = True
            packages = _extract_pip_install_packages(lower)
            if not dependencies_satisfied_by_base_image(
                list(packages),
                "pytorch/pytorch:preloaded",
            ):
                return False
            continue
        return False
    return saw_pip_install


def _extract_pip_install_packages(line: str) -> set[str]:
    tokens = line.replace("&&", " ").replace("\\", " ").split()
    try:
        install_idx = tokens.index("install")
    except ValueError:
        return set()

    packages: set[str] = set()
    for token in tokens[install_idx + 1 :]:
        if token.startswith("-"):
            continue
        if token in {"python", "-m", "pip", "install"}:
            continue
        packages.add(package_name(token))
    return packages
