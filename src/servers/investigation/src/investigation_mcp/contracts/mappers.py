"""Pure Layer-1 mappers between public MCP wire contracts and internal service models."""

import uuid
from datetime import UTC
from typing import Any

from diag_mcp.contracts.dtos import DeadlockCriteriaDTO, SlowQueryCriteriaDTO
from investigation_mcp.contracts.dtos import (
    BlockingSessionObservationDTO,
    DatabaseHealthObservationDTO,
    DeadlockInvestigationInputDTO,
    DeadlockObservationDTO,
    DiagnosticEvidenceWireDTO,
    HypothesisEvaluationWireDTO,
    InvestigateIncidentRequestDTO,
    InvestigateIncidentResponseDTO,
    InvestigationDiagnosticsInputDTO,
    InvestigationKnowledgeInputDTO,
    InvestigationLogsInputDTO,
    InvestigationSourceOutcomeWireDTO,
    InvestigationSuperOfficeInputDTO,
    KnowledgeArticleObservationDTO,
    KnownIssueObservationDTO,
    LogExcerptObservationDTO,
    PublicEvidenceSource,
    PublicSourceErrorCode,
    PublicSourceStatus,
    PublicSourceType,
    SlowQueryInvestigationInputDTO,
    SlowQueryObservationDTO,
    TicketAuditObservationDTO,
    TicketDiagnosticObservationDTO,
    TicketObservationDTO,
)
from investigation_mcp.contracts.errors import (
    InvalidEvidenceObservationError,
    InvalidEvidenceTimestampError,
    InvalidSourceErrorCodeError,
)
from platform_investigation.models import (
    DiagnosticEvidence,
    EvidenceSourceType,
    SourceCollectionResult,
    SourceCollectionStatus,
)
from platform_investigation_service.models import (
    DiagnosticsSelectionDTO,
    InvestigationRequest,
    InvestigationResult,
    KnowledgeSelectionDTO,
    LogsSelectionDTO,
    SuperOfficeSelectionDTO,
)

# Canonical source-outcome error mapping table:
# internal_code -> (public_code, public_safe_message)
ERROR_CODE_MAP: dict[str, tuple[PublicSourceErrorCode, str]] = {
    "DIAGNOSTIC_LOGS_BLOCKED": (
        "DIAGNOSTIC_LOGS_BLOCKED",
        "Application logging source is currently blocked.",
    ),
    "KNOWLEDGE_BASE_NOT_CONFIGURED": (
        "KNOWLEDGE_BASE_NOT_CONFIGURED",
        "Knowledge base source is not configured.",
    ),
    "KNOWLEDGE_BASE_RETRIEVAL_FAILED": (
        "SOURCE_EXECUTION_FAILED",
        "Knowledge base source data could not be retrieved.",
    ),
    "SUPEROFFICE_SERVICE_UNAVAILABLE": (
        "SUPEROFFICE_UNAVAILABLE",
        "SuperOffice source is currently unavailable.",
    ),
    "SUPEROFFICE_RETRIEVAL_FAILED": (
        "SUPEROFFICE_RETRIEVAL_FAILED",
        "SuperOffice source data could not be retrieved.",
    ),
    "DIAGNOSTICS_SERVICE_UNAVAILABLE": (
        "DIAGNOSTICS_UNAVAILABLE",
        "Diagnostics source is currently unavailable.",
    ),
    "DIAGNOSTICS_RETRIEVAL_FAILED": (
        "DIAGNOSTICS_RETRIEVAL_FAILED",
        "Diagnostics source data could not be retrieved.",
    ),
    "SOURCE_EXECUTION_FAILED": (
        "SOURCE_EXECUTION_FAILED",
        "An unexpected error occurred during source collection.",
    ),
}

SOURCE_TYPE_MAP: dict[EvidenceSourceType, PublicSourceType] = {
    EvidenceSourceType.SUPEROFFICE_CRM: "superoffice_crm",
    EvidenceSourceType.MSSQL_DIAGNOSTICS: "mssql_diagnostics",
    EvidenceSourceType.APPLICATION_LOGS: "application_logs",
    EvidenceSourceType.KNOWLEDGE_BASE: "knowledge_base",
}

STATUS_MAP: dict[SourceCollectionStatus, PublicSourceStatus] = {
    SourceCollectionStatus.SUCCESS: "SUCCESS",
    SourceCollectionStatus.NOT_CONFIGURED: "NOT_CONFIGURED",
    SourceCollectionStatus.BLOCKED: "BLOCKED",
    SourceCollectionStatus.UNAVAILABLE: "UNAVAILABLE",
    SourceCollectionStatus.FAILED: "FAILED",
}


class InvestigationRequestMapper:
    """Pure Layer-1 request mapper translating public MCP requests into internal models."""

    @staticmethod
    def to_internal_request(public_dto: InvestigateIncidentRequestDTO) -> InvestigationRequest:
        correlation_key = f"inv-req-{uuid.uuid4().hex[:16]}"
        diagnostics_selection = InvestigationRequestMapper._map_diagnostics_selection(
            public_dto.diagnostics
        )
        so_selection = InvestigationRequestMapper._map_so_selection(public_dto.superoffice)
        knowledge_selection = InvestigationRequestMapper._map_knowledge_selection(
            public_dto.knowledge
        )
        logs_selection = InvestigationRequestMapper._map_logs_selection(public_dto.logs)

        return InvestigationRequest(
            correlation_key=correlation_key,
            initial_hypothesis=public_dto.initial_hypothesis,
            ticket_id=public_dto.ticket_id,
            so_selection=so_selection,
            diagnostics_selection=diagnostics_selection,
            knowledge_selection=knowledge_selection,
            logs_selection=logs_selection,
            max_steps=None,
        )

    @staticmethod
    def _map_so_selection(
        dto: InvestigationSuperOfficeInputDTO | None,
    ) -> SuperOfficeSelectionDTO | None:
        if dto is None:
            return None
        return SuperOfficeSelectionDTO(
            include_audit_trail=dto.include_audit_trail,
            audit_trail_limit=dto.audit_trail_limit,
        )

    @staticmethod
    def _map_knowledge_selection(
        dto: InvestigationKnowledgeInputDTO | None,
    ) -> KnowledgeSelectionDTO | None:
        if dto is None:
            return None
        return KnowledgeSelectionDTO(
            include_knowledge_search=dto.include_knowledge_search,
            query_override=dto.query_override,
            limit=dto.limit,
        )

    @staticmethod
    def _map_logs_selection(
        dto: InvestigationLogsInputDTO | None,
    ) -> LogsSelectionDTO | None:
        if dto is None:
            return None
        return LogsSelectionDTO(
            include_logs=dto.include_logs,
            query=dto.query,
            limit=dto.limit,
        )

    @staticmethod
    def _map_diagnostics_selection(
        diagnostics: InvestigationDiagnosticsInputDTO | None,
    ) -> DiagnosticsSelectionDTO | None:
        if diagnostics is None:
            return None

        deadlock_criteria = None
        if diagnostics.deadlocks is not None:
            deadlock_criteria = InvestigationRequestMapper._map_deadlock_criteria(
                diagnostics.deadlocks
            )

        slow_query_criteria = None
        if diagnostics.slow_queries is not None:
            slow_query_criteria = InvestigationRequestMapper._map_slow_query_criteria(
                diagnostics.slow_queries
            )

        return DiagnosticsSelectionDTO(
            include_database_health=diagnostics.include_database_health,
            deadlock_criteria=deadlock_criteria,
            slow_query_criteria=slow_query_criteria,
            include_ticket_diagnostic=diagnostics.include_ticket_diagnostic,
            include_blocking_sessions=diagnostics.include_blocking_sessions,
        )

    @staticmethod
    def _map_deadlock_criteria(dto: DeadlockInvestigationInputDTO) -> DeadlockCriteriaDTO:
        return DeadlockCriteriaDTO(
            start_time=dto.start_time,
            end_time=dto.end_time,
            limit=dto.limit,
        )

    @staticmethod
    def _map_slow_query_criteria(dto: SlowQueryInvestigationInputDTO) -> SlowQueryCriteriaDTO:
        return SlowQueryCriteriaDTO(
            start_time=dto.start_time,
            end_time=dto.end_time,
            min_duration_ms=dto.min_duration_ms,
            limit=dto.limit,
        )


class InvestigationResponseMapper:
    """Pure Layer-1 response mapper translating internal service results to wire contracts."""

    @staticmethod
    def to_public_response(result: InvestigationResult) -> InvestigateIncidentResponseDTO:
        # 1. Map source outcomes
        public_outcomes = tuple(
            InvestigationResponseMapper._map_source_outcome(o)
            for o in result.aggregation.source_outcomes
        )

        # 2. Map evidence items: validate awareness, normalize UTC, map typed data, sort stably
        public_evidence = InvestigationResponseMapper._map_evidence_items(
            result.aggregation.evidence
        )

        # 3. Map hypothesis evaluation if present
        public_evaluation = None
        if result.hypothesis_evaluation is not None:
            public_evaluation = HypothesisEvaluationWireDTO(
                hypothesis_id=result.hypothesis_evaluation.hypothesis_id,
                outcome=result.hypothesis_evaluation.outcome.value.upper(),
            )

        return InvestigateIncidentResponseDTO(
            source_outcomes=public_outcomes,
            evidence=public_evidence,
            hypothesis_evaluation=public_evaluation,
        )

    @staticmethod
    def _map_source_outcome(
        outcome: SourceCollectionResult,
    ) -> InvestigationSourceOutcomeWireDTO:
        public_source = SOURCE_TYPE_MAP[outcome.source_type]
        public_status = STATUS_MAP[outcome.status]

        if outcome.status == SourceCollectionStatus.SUCCESS:
            return InvestigationSourceOutcomeWireDTO(
                source=public_source,
                status=public_status,
                error_code=None,
                error_message=None,
            )

        if outcome.error_code not in ERROR_CODE_MAP:
            raise InvalidSourceErrorCodeError(
                f"Encountered unmapped internal source outcome error code: {outcome.error_code}"
            )

        public_error_code, public_error_message = ERROR_CODE_MAP[outcome.error_code]
        return InvestigationSourceOutcomeWireDTO(
            source=public_source,
            status=public_status,
            error_code=public_error_code,
            error_message=public_error_message,
        )

    @staticmethod
    def _map_evidence_items(
        raw_evidence: tuple[DiagnosticEvidence, ...],
    ) -> tuple[DiagnosticEvidenceWireDTO, ...]:
        mapped_items: list[DiagnosticEvidenceWireDTO] = []

        for evidence in raw_evidence:
            if evidence.timestamp.tzinfo is None:
                raise InvalidEvidenceTimestampError(
                    "Internal diagnostic evidence contains an offset-naive timestamp"
                )

            utc_timestamp = evidence.timestamp.astimezone(UTC)
            public_source, observation_dto = InvestigationResponseMapper._map_observation(evidence)

            mapped_items.append(
                DiagnosticEvidenceWireDTO(
                    source=public_source,
                    timestamp=utc_timestamp,
                    data=observation_dto,
                )
            )

        mapped_items.sort(key=lambda item: item.timestamp)
        return tuple(mapped_items)

    @staticmethod
    def _map_observation(  # noqa: PLR0911
        evidence: DiagnosticEvidence,
    ) -> tuple[PublicEvidenceSource, Any]:
        data = evidence.data

        # 1. SuperOffice ticket
        if evidence.source_type == EvidenceSourceType.SUPEROFFICE_CRM and evidence.tags == (
            "crm",
            "ticket",
            "superoffice",
        ):
            ticket_dto = TicketObservationDTO(
                ticket_id=data["ticket_id"],
                title=data.get("title"),
                status=data["status"],
                category=data["category"],
                priority=data["priority"],
                sanitized_description=data.get("sanitized_description"),
                sanitized_customer_reference=data.get("sanitized_customer_reference"),
            )
            return "superoffice_crm", ticket_dto

        # 2. SuperOffice ticket audit action
        if evidence.source_type == EvidenceSourceType.SUPEROFFICE_CRM and evidence.tags == (
            "crm",
            "ticket",
            "audit_trail",
        ):
            audit_dto = TicketAuditObservationDTO(
                action_id=data["action_id"],
                ticket_id=data["ticket_id"],
                action_code=data.get("action_code"),
                action_name=data["action_name"],
                description=data.get("description", ""),
                actor=data.get("actor"),
                field_changes=data.get("field_changes", []),
            )
            return "superoffice_crm", audit_dto

        # 3. Database health
        if evidence.source_type == EvidenceSourceType.MSSQL_DIAGNOSTICS and evidence.tags == (
            "diagnostics",
            "database",
            "health",
        ):
            health_dto = DatabaseHealthObservationDTO(
                is_healthy=data["is_healthy"],
                active_connections=data["active_connections"],
                latency_ms=data["latency_ms"],
            )
            return "mssql_diagnostics", health_dto

        # 4. Deadlock
        if evidence.source_type == EvidenceSourceType.MSSQL_DIAGNOSTICS and evidence.tags == (
            "diagnostics",
            "database",
            "deadlock",
        ):
            deadlock_dto = DeadlockObservationDTO(
                deadlock_id=data["deadlock_id"],
                victim_session_id=data["victim_session_id"],
                participating_session_count=data["participating_session_count"],
            )
            return "mssql_diagnostics", deadlock_dto

        # 5. Slow query
        if evidence.source_type == EvidenceSourceType.MSSQL_DIAGNOSTICS and evidence.tags == (
            "diagnostics",
            "database",
            "slow_query",
        ):
            slow_query_dto = SlowQueryObservationDTO(
                query_hash=data["query_hash"],
                duration_ms=data["duration_ms"],
                cpu_time_ms=data["cpu_time_ms"],
                logical_reads=data["logical_reads"],
                execution_count=data["execution_count"],
            )
            return "mssql_diagnostics", slow_query_dto

        # 6. Ticket diagnostic record (y_logticket)
        if evidence.source_type == EvidenceSourceType.MSSQL_DIAGNOSTICS and evidence.tags == (
            "diagnostics",
            "database",
            "ticket_diagnostic",
        ):
            td_dto = TicketDiagnosticObservationDTO(
                ticket_id=data["ticket_id"],
                has_db_activity=data["has_db_activity"],
                recent_error_count=data["recent_error_count"],
                last_activity_time=data.get("last_activity_time"),
                diagnostic_summary=data["diagnostic_summary"],
            )
            return "mssql_diagnostics", td_dto

        # 7. Blocking session
        if evidence.source_type == EvidenceSourceType.MSSQL_DIAGNOSTICS and evidence.tags == (
            "diagnostics",
            "database",
            "blocking_session",
        ):
            bs_dto = BlockingSessionObservationDTO(
                blocking_session_id=data["blocking_session_id"],
                blocked_session_id=data["blocked_session_id"],
                wait_duration_ms=data["wait_duration_ms"],
                wait_type=data.get("wait_type", ""),
            )
            return "mssql_diagnostics", bs_dto

        # 8. Log excerpt
        if evidence.source_type == EvidenceSourceType.APPLICATION_LOGS and evidence.tags == (
            "diagnostics",
            "logs",
            "excerpt",
        ):
            log_dto = LogExcerptObservationDTO(
                excerpt_id=data["excerpt_id"],
                service_name=data["service_name"],
                severity=data["severity"],
                sanitized_message=data["sanitized_message"],
                correlation_id=data.get("correlation_id"),
            )
            return "application_logs", log_dto

        # 9. Knowledge known issue
        if evidence.source_type == EvidenceSourceType.KNOWLEDGE_BASE and evidence.tags == (
            "knowledge",
            "known_issue",
        ):
            ki_dto = KnownIssueObservationDTO(
                issue_id=data["issue_id"],
                title=data["title"],
                symptom_summary=data["symptom_summary"],
                root_cause_summary=data["root_cause_summary"],
                workaround=data.get("workaround"),
                permanent_fix_reference=data.get("permanent_fix_reference"),
                affected_products=data.get("affected_products", []),
            )
            return "knowledge_base", ki_dto

        # 10. Knowledge article
        if evidence.source_type == EvidenceSourceType.KNOWLEDGE_BASE and evidence.tags == (
            "knowledge",
            "article",
        ):
            ka_dto = KnowledgeArticleObservationDTO(
                document_id=data["document_id"],
                title=data["title"],
                content_excerpt=data["content_excerpt"],
                category=data["category"],
                relevance_score=data["relevance_score"],
                source_reference=data["source_reference"],
            )
            return "knowledge_base", ka_dto

        # Any mismatch, extra tags, missing tags, or unknown source fails closed
        raise InvalidEvidenceObservationError(
            f"Evidence observation discriminator failed exact tag and source matching: "
            f"source={evidence.source_type}, tags={evidence.tags}"
        )
