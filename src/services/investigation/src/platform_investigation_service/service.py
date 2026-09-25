"""Layer-4 Investigation Application Service.

Orchestrates a single-request cross-system investigation cycle composing:
1. Plan creation via InvestigationOrchestratorPort
2. Per-request collector binding to immutable typed criteria across 4 domain sources:
   - 1. SUPEROFFICE_CRM (ticket + audit trail)
   - 2. MSSQL_DIAGNOSTICS (cluster health, deadlocks, slow queries, ticket DB records, blocking)
   - 3. APPLICATION_LOGS (sanitized log excerpts)
   - 4. KNOWLEDGE_BASE (known issues, solution workarounds, runbooks)
3. Sequential evidence collection via EvidenceAggregatorEngine
4. Chronological timeline generation via IncidentCorrelationEngine
5. Grounded deterministic hypothesis evaluation via HypothesisEvaluatorEngine
6. Diagnostic step recording via advance_step()
7. Assembly of immutable InvestigationResult

Import policy: ONLY platform-investigation, platform-core, and local ports/models.
NO server runtime, adapter, or infrastructure imports.
"""

from platform_core.errors import DomainValidationError
from platform_investigation.aggregator import EvidenceAggregatorEngine
from platform_investigation.evaluator import HypothesisEvaluatorEngine
from platform_investigation.interfaces import HypothesisEvaluator, IncidentCorrelator
from platform_investigation.models import Hypothesis
from platform_investigation.timeline import IncidentCorrelationEngine
from platform_investigation_service.collectors.diagnostics_collector import (
    DiagnosticsEvidenceCollector,
)
from platform_investigation_service.collectors.knowledge_collector import (
    KnowledgeEvidenceCollector,
)
from platform_investigation_service.collectors.logs_collector import (
    DiagnosticLogsEvidenceCollector,
)
from platform_investigation_service.collectors.superoffice_collector import (
    SuperOfficeEvidenceCollector,
)
from platform_investigation_service.models import (
    InvestigationRequest,
    InvestigationResult,
)
from platform_investigation_service.ports import (
    DiagnosticsServicePort,
    InvestigationOrchestratorPort,
    KnowledgeServicePort,
    LogsServicePort,
    SuperOfficeServicePort,
)
from platform_observability.logging import get_logger

logger = get_logger(__name__)


class InvestigationApplicationService:
    """Layer-4 application service composing generic investigation runtimes
    with domain-specific evidence collectors.

    Single-request orchestration:
    - Creates a bounded investigation plan
    - Binds per-request collectors in deterministic registration order
    - Aggregates evidence (sequential, deterministic via EvidenceAggregatorEngine)
    - Builds chronological timeline and correlation groups
    - Evaluates investigation hypothesis against grounded evidence inventory
    - Records exactly one diagnostic step on the plan
    - Returns immutable InvestigationResult
    """

    def __init__(  # noqa: PLR0917
        self,
        orchestrator: InvestigationOrchestratorPort,
        superoffice_service: SuperOfficeServicePort | None = None,
        diagnostics_service: DiagnosticsServicePort | None = None,
        knowledge_service: KnowledgeServicePort | None = None,
        logs_service: LogsServicePort | None = None,
        correlator: IncidentCorrelator | None = None,
        evaluator: HypothesisEvaluator | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._superoffice_service = superoffice_service
        self._diagnostics_service = diagnostics_service
        self._knowledge_service = knowledge_service
        self._logs_service = logs_service or (
            diagnostics_service if isinstance(diagnostics_service, LogsServicePort) else None
        )
        self._correlator = correlator or IncidentCorrelationEngine()
        self._evaluator = evaluator or HypothesisEvaluatorEngine()

    async def investigate(self, request: InvestigationRequest) -> InvestigationResult:
        """Execute a single-request investigation cycle across all 4 domain sources.

        Pipeline:
        1. Validate InvestigationRequest
        2. create_plan(initial_hypothesis=request.initial_hypothesis, max_steps=request.max_steps)
        3. Bind per-request collectors to typed criteria in deterministic order
        4. Sequential EvidenceAggregatorEngine aggregation
        5. IncidentCorrelationEngine timeline generation
        6. Deterministic HypothesisEvaluatorEngine evaluation
        7. advance_step(...)
        8. Return InvestigationResult
        """
        self._validate_request(request)

        logger.info(
            "Investigation cycle started",
            has_ticket_id=request.ticket_id is not None,
            has_diagnostics_selection=request.diagnostics_selection is not None,
            has_knowledge_selection=request.knowledge_selection is not None,
            has_logs_selection=request.logs_selection is not None,
        )

        # 1. Create plan
        plan = await self._orchestrator.create_plan(
            initial_hypothesis=request.initial_hypothesis,
            max_steps=request.max_steps,
        )
        investigation_id = plan.investigation_id

        # 2. Bind collectors per-request in deterministic registration order:
        # 1. SUPEROFFICE_CRM
        # 2. MSSQL_DIAGNOSTICS
        # 3. APPLICATION_LOGS
        # 4. KNOWLEDGE_BASE
        so_collector = SuperOfficeEvidenceCollector(
            service=self._superoffice_service,
            ticket_id=request.ticket_id,
            selection=request.so_selection,
        )
        diag_collector = DiagnosticsEvidenceCollector(
            service=self._diagnostics_service,
            selection=request.diagnostics_selection,
            ticket_id=request.ticket_id,
        )
        logs_collector = DiagnosticLogsEvidenceCollector(
            service=self._logs_service,
            selection=request.logs_selection,
            query_context=request.initial_hypothesis,
        )
        kb_collector = KnowledgeEvidenceCollector(
            service=self._knowledge_service,
            selection=request.knowledge_selection,
            query_context=request.initial_hypothesis,
        )

        aggregator = EvidenceAggregatorEngine(
            collectors=(so_collector, diag_collector, logs_collector, kb_collector)
        )

        # 3. Sequential evidence collection
        aggregation = await aggregator.aggregate(
            investigation_id=investigation_id,
            correlation_key=request.correlation_key,
        )

        # 4. Timeline generation
        timeline = self._correlator.build_timeline(aggregation)

        # 5. Deterministic hypothesis evaluation against collected evidence
        hypothesis_evaluation = None
        if self._evaluator is not None and len(aggregation.evidence) > 0:
            supporting_ids = tuple(
                ev.evidence_id
                for ev in aggregation.evidence
                if any(t in ev.tags for t in ("deadlock", "slow_query", "known_issue"))
                or (ev.data.get("severity") in ("ERROR", "CRITICAL"))
            )
            candidate_hypo = Hypothesis(
                description=request.initial_hypothesis,
                supporting_evidence_ids=supporting_ids,
                refuting_evidence_ids=(),
            )
            hypothesis_evaluation = self._evaluator.evaluate(candidate_hypo, aggregation)

        # 6. Advance exactly one diagnostic step
        severity = "INFO" if aggregation.successful_sources_count > 0 else "WARN"
        action_taken = "Multi-source diagnostic evidence collection and correlation"
        summary = (
            f"Collected {len(aggregation.evidence)} evidence items; "
            f"{aggregation.successful_sources_count} sources successful."
        )
        collected_evidence_ids = tuple(e.evidence_id for e in aggregation.evidence)

        updated_plan = await self._orchestrator.advance_step(
            plan_id=investigation_id,
            action_taken=action_taken,
            summary=summary,
            severity=severity,
            correlation_keys=(request.correlation_key,),
            collected_evidence_ids=collected_evidence_ids,
        )

        logger.info(
            "Investigation cycle completed",
            evidence_count=len(aggregation.evidence),
            source_count=aggregation.total_sources,
            successful_source_count=aggregation.successful_sources_count,
            step_number=updated_plan.current_step_count,
            hypothesis_outcome=(
                hypothesis_evaluation.outcome.value if hypothesis_evaluation else None
            ),
        )

        # 7. Assemble and return immutable result
        return InvestigationResult(
            investigation_id=investigation_id,
            plan=updated_plan,
            aggregation=aggregation,
            timeline=timeline,
            hypothesis_evaluation=hypothesis_evaluation,
        )

    def _validate_request(self, request: InvestigationRequest) -> None:
        """Validate investigation request invariants."""
        if not request.correlation_key or not request.correlation_key.strip():
            raise DomainValidationError(
                "correlation_key cannot be empty.",
                field_name="correlation_key",
            )
        if not request.initial_hypothesis or not request.initial_hypothesis.strip():
            raise DomainValidationError(
                "initial_hypothesis cannot be empty.",
                field_name="initial_hypothesis",
            )
