"""SQLAlchemy model registry.

Import all models here so Alembic can discover them for autogeneration.
"""

from libs.storage.models.analysis import (
    AnalysisSession,
    CoverageDiagnostic,
    EvidenceCard,
    GraphEdge,
    GraphNode,
    IngestedDocument,
    PaperAnalysisPacket,
    PaperChunk,
    PaperReviewArtifact,
)
from libs.storage.models.autonomy import AutonomyBudget, LoopDecision
from libs.storage.models.corpus import ArxivCorpusRecord, CorpusImportRun
from libs.storage.models.discovery import (
    DiscoveryEvaluation,
    DiscoverySession,
    ProblemProfile,
)
from libs.storage.models.events import DomainEvent
from libs.storage.models.experiment import (
    ExperimentSpec,
    FailurePostmortem,
    HypothesisCard,
    HypothesisSession,
    RunRecord,
    RunTelemetry,
    VerificationReport,
)
from libs.storage.models.jobs import Job
from libs.storage.models.lineage import ModelCallRecord
from libs.storage.models.orchestrator import ApiToken, OrchestratorClient
from libs.storage.models.papers import PaperCard
from libs.storage.models.patterns import (
    CanonicalPattern,
    PatternApproval,
    PatternObservation,
    PeriodicJobState,
)
from libs.storage.models.remediation import (
    DirectionalSignal,
    MetricFrontier,
    RemediationAction,
    RunRecommendation,
)
from libs.storage.models.research import ResearchCharter, ResearchCycle
from libs.storage.models.skills import SkillBinding, SkillDefinition

__all__ = [
    "AnalysisSession",
    "ApiToken",
    "ArxivCorpusRecord",
    "AutonomyBudget",
    "CanonicalPattern",
    "CorpusImportRun",
    "CoverageDiagnostic",
    "DirectionalSignal",
    "DiscoveryEvaluation",
    "DiscoverySession",
    "DomainEvent",
    "EvidenceCard",
    "ExperimentSpec",
    "FailurePostmortem",
    "GraphEdge",
    "GraphNode",
    "HypothesisCard",
    "HypothesisSession",
    "IngestedDocument",
    "Job",
    "LoopDecision",
    "MetricFrontier",
    "ModelCallRecord",
    "OrchestratorClient",
    "PaperAnalysisPacket",
    "PaperCard",
    "PaperChunk",
    "PaperReviewArtifact",
    "PatternApproval",
    "PatternObservation",
    "PeriodicJobState",
    "ProblemProfile",
    "RemediationAction",
    "ResearchCharter",
    "ResearchCycle",
    "RunRecommendation",
    "RunRecord",
    "RunTelemetry",
    "SkillBinding",
    "SkillDefinition",
    "VerificationReport",
]
