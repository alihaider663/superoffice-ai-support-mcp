"""Platform investigation and diagnostic orchestration protocols."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from platform_investigation.models import (
    DiagnosticEvidence,
    EvidenceAggregationResult,
    EvidenceSourceType,
    Hypothesis,
    HypothesisEvaluationResult,
    InvestigationPlan,
    InvestigationTimeline,
    LogInvestigationResult,
    SourceCollectionResult,
)


@runtime_checkable
class EvidenceCollector(Protocol):
    """Protocol for collecting structured diagnostic evidence artifacts."""

    async def collect_evidence(
        self,
        investigation_id: str,
        correlation_key: str,
    ) -> Sequence[DiagnosticEvidence]:
        """Collect atomic diagnostic evidence items related to a correlation key."""
        ...


@runtime_checkable
class OutcomeAwareEvidenceCollector(Protocol):
    """Protocol for evidence collectors that report typed source execution outcomes."""

    @property
    def source_type(self) -> EvidenceSourceType:
        """System origin identifier for this collector."""
        ...

    async def collect(
        self,
        investigation_id: str,
        correlation_key: str,
    ) -> SourceCollectionResult:
        """Collect diagnostic evidence and return a typed source collection outcome."""
        ...


@runtime_checkable
class DiagnosticLogCollector(Protocol):
    """Protocol for automated log investigation across application log stores."""

    async def investigate_logs(
        self,
        correlation_id: str | None = None,
        error_pattern: str | None = None,
        time_window_minutes: int = 15,
    ) -> LogInvestigationResult:
        """Analyze and summarize logs related to an incident or error pattern."""
        ...


@runtime_checkable
class EvidenceAggregator(Protocol):
    """Protocol for aggregating evidence across multiple outcome-aware collectors."""

    async def aggregate(
        self,
        investigation_id: str,
        correlation_key: str,
    ) -> EvidenceAggregationResult:
        """Aggregate evidence across all registered outcome-aware collectors."""
        ...


@runtime_checkable
class IncidentCorrelator(Protocol):
    """Protocol for deterministic correlation and chronological timeline projection."""

    def build_timeline(
        self,
        aggregation_result: EvidenceAggregationResult,
    ) -> InvestigationTimeline:
        """Build a deterministic timeline and correlation groups from evidence."""
        ...


@runtime_checkable
class HypothesisEvaluator(Protocol):
    """Protocol for deterministic hypothesis evaluation against aggregated evidence."""

    def evaluate(
        self,
        hypothesis: Hypothesis,
        evidence: EvidenceAggregationResult,
    ) -> HypothesisEvaluationResult:
        """Evaluate a single hypothesis against explicit evidence bindings."""
        ...


@runtime_checkable
class InvestigationOrchestrator(Protocol):
    """Protocol for managing bounded investigation state machines."""

    async def create_plan(self, initial_hypothesis: str) -> InvestigationPlan:
        """Create a new bounded diagnostic investigation plan."""
        ...

    async def advance_step(
        self,
        plan_id: str,
        hypothesis: Hypothesis | None = None,
    ) -> InvestigationPlan:
        """Advance the diagnostic state machine, checking step bounds."""
        ...

    async def conclude_investigation(
        self,
        plan_id: str,
        final_hypothesis_id: str,
    ) -> InvestigationPlan:
        """Conclude an investigation with a validated root cause hypothesis."""
        ...
