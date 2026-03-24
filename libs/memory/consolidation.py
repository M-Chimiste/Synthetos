"""Cross-charter pattern consolidation: gather, cluster, extract, upsert, decay."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jinja2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.adapters.embeddings.base import EmbeddingAdapter
from libs.adapters.llm.gateway import ModelGateway
from libs.core.ids import generate_public_id
from libs.core.policy import MemoryPolicyConfig
from libs.storage.models import (
    CanonicalPatternModel,
    ExperimentSpecModel,
    FailurePostmortemModel,
    RunRecordModel,
    VerificationReportModel,
)

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts" / "memory" / "v1"
_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(PROMPTS_DIR)),
    undefined=jinja2.StrictUndefined,
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PostmortemCluster:
    failure_class: str
    members: list[FailurePostmortemModel]
    charter_ids: set[int] = field(default_factory=set)


@dataclass
class SuccessCluster:
    method_summary: str
    members: list[RunRecordModel]
    specs: list[ExperimentSpecModel]
    charter_ids: set[int] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Union-Find for clustering
# ---------------------------------------------------------------------------


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def groups(self) -> dict[int, list[int]]:
        clusters: dict[int, list[int]] = defaultdict(list)
        for i in range(len(self.parent)):
            clusters[self.find(i)].append(i)
        return clusters


# ---------------------------------------------------------------------------
# 1. Gathering
# ---------------------------------------------------------------------------


def gather_cross_charter_postmortems(
    session: Session,
    *,
    since: datetime | None = None,
) -> list[FailurePostmortemModel]:
    """Fetch all postmortems across all charters, optionally since a cutoff."""
    stmt = select(FailurePostmortemModel).order_by(FailurePostmortemModel.created_at.desc())
    if since is not None:
        stmt = stmt.where(FailurePostmortemModel.created_at >= since)
    return list(session.scalars(stmt).all())


def gather_cross_charter_successful_runs(
    session: Session,
    *,
    since: datetime | None = None,
) -> list[RunRecordModel]:
    """Fetch runs with positive verification outcomes across all charters."""
    stmt = (
        select(RunRecordModel)
        .join(VerificationReportModel, VerificationReportModel.run_record_id == RunRecordModel.id)
        .where(VerificationReportModel.verification_outcome.in_(["confirmed", "tentative"]))
        .order_by(RunRecordModel.created_at.desc())
    )
    if since is not None:
        stmt = stmt.where(RunRecordModel.created_at >= since)
    return list(session.scalars(stmt).all())


# ---------------------------------------------------------------------------
# 2. Clustering
# ---------------------------------------------------------------------------


def _cosine_similarity_matrix(embeddings: np.ndarray) -> np.ndarray:
    """Pairwise cosine similarity for a matrix of row-vectors."""
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-10)  # avoid division by zero
    normed = embeddings / norms
    return normed @ normed.T


def cluster_postmortems_by_failure(
    postmortems: list[FailurePostmortemModel],
    embedder: EmbeddingAdapter,
    policy: MemoryPolicyConfig,
) -> list[PostmortemCluster]:
    """Two-pass clustering: group by failure_class, then sub-cluster by semantic similarity."""
    by_class: dict[str, list[FailurePostmortemModel]] = defaultdict(list)
    for pm in postmortems:
        by_class[pm.failure_class].append(pm)

    clusters: list[PostmortemCluster] = []
    for failure_class, group in by_class.items():
        if len(group) < policy.min_cluster_size:
            continue

        texts = [
            f"{pm.root_cause_summary or ''} {' '.join(pm.contributing_factors or [])}"
            for pm in group
        ]
        vecs = np.array(embedder.embed_documents(texts))
        sim = _cosine_similarity_matrix(vecs)

        uf = _UnionFind(len(group))
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if sim[i, j] >= policy.similarity_threshold:
                    uf.union(i, j)

        for indices in uf.groups().values():
            if len(indices) < policy.min_cluster_size:
                continue
            members = [group[i] for i in indices]
            charter_ids = {pm.cycle.charter_id for pm in members if pm.cycle is not None}
            if len(charter_ids) < policy.min_charters_for_pattern:
                continue
            clusters.append(PostmortemCluster(
                failure_class=failure_class,
                members=members,
                charter_ids=charter_ids,
            ))

    return clusters


def cluster_successful_runs_by_method(
    runs: list[RunRecordModel],
    specs: dict[int, ExperimentSpecModel],
    embedder: EmbeddingAdapter,
    policy: MemoryPolicyConfig,
) -> list[SuccessCluster]:
    """Cluster successful runs by method_description similarity."""
    paired: list[tuple[RunRecordModel, ExperimentSpecModel]] = []
    for run in runs:
        spec = specs.get(run.experiment_spec_id)
        if spec is not None:
            paired.append((run, spec))

    if len(paired) < policy.min_cluster_size:
        return []

    texts = [spec.method_description or spec.title for _, spec in paired]
    vecs = np.array(embedder.embed_documents(texts))
    sim = _cosine_similarity_matrix(vecs)

    uf = _UnionFind(len(paired))
    for i in range(len(paired)):
        for j in range(i + 1, len(paired)):
            if sim[i, j] >= policy.similarity_threshold:
                uf.union(i, j)

    clusters: list[SuccessCluster] = []
    for indices in uf.groups().values():
        if len(indices) < policy.min_cluster_size:
            continue
        members = [paired[i][0] for i in indices]
        member_specs = [paired[i][1] for i in indices]
        charter_ids = set()
        for run in members:
            if run.cycle is not None:
                charter_ids.add(run.cycle.charter_id)
        if len(charter_ids) < policy.min_charters_for_pattern:
            continue
        clusters.append(SuccessCluster(
            method_summary=texts[indices[0]],
            members=members,
            specs=member_specs,
            charter_ids=charter_ids,
        ))

    return clusters


# ---------------------------------------------------------------------------
# 3. LLM extraction
# ---------------------------------------------------------------------------


def get_existing_categories(session: Session) -> list[str]:
    """Return distinct category values from existing canonical patterns."""
    stmt = (
        select(CanonicalPatternModel.category)
        .where(CanonicalPatternModel.category != "")
        .distinct()
        .order_by(CanonicalPatternModel.category)
    )
    return list(session.scalars(stmt).all())


def _build_postmortem_context(
    pm: FailurePostmortemModel,
    charter_public_ids: dict[int, str],
) -> dict[str, Any]:
    charter_pid = charter_public_ids.get(
        pm.cycle.charter_id if pm.cycle else 0, "unknown",
    )
    return {
        "charter_public_id": charter_pid,
        "root_cause_summary": pm.root_cause_summary or "",
        "contributing_factors": pm.contributing_factors or [],
        "remediation_suggestions": pm.remediation_suggestions or [],
        "failure_stage": pm.failure_stage or "",
    }


def extract_pattern_from_failure_cluster(
    cluster: PostmortemCluster,
    gateway: ModelGateway,
    existing_categories: list[str],
    charter_public_ids: dict[int, str],
) -> dict[str, Any]:
    """Render consolidation prompt, call LLM, return extracted pattern dict."""
    template = _jinja_env.get_template("consolidate_failure_pattern.md")
    rendered = template.render(
        failure_class=cluster.failure_class,
        cluster_size=len(cluster.members),
        charter_count=len(cluster.charter_ids),
        postmortems=[
            _build_postmortem_context(pm, charter_public_ids) for pm in cluster.members
        ],
        existing_categories=existing_categories,
    )

    result = gateway.call_structured(
        role="synthesizer",
        messages=[{"role": "user", "content": rendered}],
        temperature=0.2,
        max_tokens=2048,
    )
    if isinstance(result, list):
        result = result[0]
    result["pattern_type"] = "failure_pattern"
    return result


def extract_pattern_from_success_cluster(
    cluster: SuccessCluster,
    gateway: ModelGateway,
    existing_categories: list[str],
    charter_public_ids: dict[int, str],
    verification_outcomes: dict[int, str],
    directional_signals: dict[int, str],
) -> dict[str, Any]:
    """Render consolidation prompt, call LLM, return extracted pattern dict."""
    template = _jinja_env.get_template("consolidate_method_pattern.md")

    run_contexts = []
    for run, spec in zip(cluster.members, cluster.specs, strict=True):
        charter_pid = charter_public_ids.get(
            run.cycle.charter_id if run.cycle else 0, "unknown",
        )
        metrics = run.metrics_summary or {}
        primary_name = next(iter(metrics), "unknown")
        primary_value = metrics.get(primary_name, "N/A")
        run_contexts.append({
            "charter_public_id": charter_pid,
            "method_description": spec.method_description or spec.title,
            "primary_metric_name": primary_name,
            "primary_metric_value": primary_value,
            "verification_outcome": verification_outcomes.get(run.id, "unknown"),
            "directional_signal": directional_signals.get(run.id, "unknown"),
            "controls": spec.controls,
        })

    rendered = template.render(
        cluster_size=len(cluster.members),
        charter_count=len(cluster.charter_ids),
        method_summary=cluster.method_summary,
        runs=run_contexts,
        existing_categories=existing_categories,
    )

    result = gateway.call_structured(
        role="synthesizer",
        messages=[{"role": "user", "content": rendered}],
        temperature=0.2,
        max_tokens=2048,
    )
    if isinstance(result, list):
        result = result[0]
    result["pattern_type"] = "method_pattern"
    return result


# ---------------------------------------------------------------------------
# 4. Upsert
# ---------------------------------------------------------------------------


def _build_evidence_refs(
    members: list[FailurePostmortemModel] | list[RunRecordModel],
    ref_type: str,
    charter_public_ids: dict[int, str],
) -> list[dict[str, Any]]:
    refs = []
    now_iso = datetime.now(UTC).isoformat()
    for m in members:
        charter_cid = getattr(m.cycle, "charter_id", 0) if m.cycle else 0
        refs.append({
            "charter_public_id": charter_public_ids.get(charter_cid, "unknown"),
            "ref_type": ref_type,
            "public_id": m.public_id,
            "summary": getattr(m, "root_cause_summary", None) or getattr(m, "title", ""),
            "added_at": now_iso,
        })
    return refs


def upsert_canonical_pattern(
    session: Session,
    extracted: dict[str, Any],
    evidence_refs: list[dict[str, Any]],
    embedder: EmbeddingAdapter,
) -> CanonicalPatternModel:
    """Create or update a canonical pattern from LLM-extracted data."""
    title = extracted["title"]
    pattern_type = extracted["pattern_type"]

    existing = session.scalars(
        select(CanonicalPatternModel)
        .where(CanonicalPatternModel.title == title)
        .where(CanonicalPatternModel.pattern_type == pattern_type)
        .limit(1)
    ).first()

    search_text = f"{title}\n\n{extracted.get('description', '')}"
    embedding = embedder.embed_query(search_text)
    now = datetime.now(UTC)

    if existing is not None:
        # Merge evidence refs (avoid duplicates by public_id)
        known_pids = {r["public_id"] for r in (existing.evidence_refs or [])}
        new_refs = [r for r in evidence_refs if r["public_id"] not in known_pids]
        existing.evidence_refs = (existing.evidence_refs or []) + new_refs
        existing.evidence_count = len(existing.evidence_refs)
        existing.description = extracted.get("description", existing.description)
        existing.trigger_conditions = extracted.get(
            "trigger_conditions", existing.trigger_conditions,
        )
        existing.proven_actions = extracted.get("proven_actions", existing.proven_actions)
        existing.disproven_actions = extracted.get("disproven_actions", existing.disproven_actions)
        existing.staleness_context = extracted.get("staleness_context", existing.staleness_context)
        existing.category = extracted.get("category", existing.category)
        existing.search_text = search_text
        existing.embedding = embedding
        existing.embedding_updated_at = now
        existing.last_validated_at = now
        return existing

    pattern = CanonicalPatternModel(
        public_id=generate_public_id("pat"),
        pattern_type=pattern_type,
        polarity=extracted.get("polarity", "negative"),
        title=title,
        description=extracted.get("description", ""),
        category=extracted.get("category", ""),
        trigger_conditions=extracted.get("trigger_conditions", []),
        proven_actions=extracted.get("proven_actions", []),
        disproven_actions=extracted.get("disproven_actions", []),
        evidence_refs=evidence_refs,
        evidence_count=len(evidence_refs),
        confidence_score=1.0,
        staleness_context=extracted.get("staleness_context", {}),
        status="active",
        last_validated_at=now,
        search_text=search_text,
        embedding=embedding,
        embedding_updated_at=now,
    )
    session.add(pattern)
    return pattern


# ---------------------------------------------------------------------------
# 5. Staleness & decay
# ---------------------------------------------------------------------------


def apply_staleness_decay(
    session: Session,
    policy: MemoryPolicyConfig,
) -> int:
    """Decay confidence for stale patterns. Returns count of decayed patterns."""
    cutoff = datetime.now(UTC) - timedelta(days=policy.decay_interval_days)
    stmt = (
        select(CanonicalPatternModel)
        .where(CanonicalPatternModel.status == "active")
        .where(
            (CanonicalPatternModel.last_validated_at < cutoff)
            | (CanonicalPatternModel.last_validated_at.is_(None))
        )
    )
    stale = list(session.scalars(stmt).all())
    decayed = 0
    for pattern in stale:
        pattern.confidence_score *= policy.decay_factor
        if pattern.confidence_score < policy.revalidation_threshold:
            pattern.status = "needs_revalidation"
        decayed += 1
    return decayed


def check_staleness_context(
    pattern: CanonicalPatternModel,
    current_context: dict[str, Any],
) -> bool:
    """Return True if the pattern's env assumptions still match current context."""
    ctx = pattern.staleness_context or {}
    if not ctx:
        return True  # No assumptions → always applicable
    for key, expected in ctx.items():
        if key in current_context and current_context[key] != expected:
            return False
    return True
