"""Pure Layer-1 mappers between public MCP wire contracts and internal service models."""

import uuid
from datetime import UTC

from diag_mcp.contracts.dtos import DeadlockCriteriaDTO, SlowQueryCriteriaDTO
from investigation_mcp.contracts.dtos import (
    DatabaseHealthObservationDTO,
    DeadlockInvestigationInputDTO,
    DeadlockObservationDTO,
    DiagnosticEvidenceWireDTO,
    InvestigateIncidentRequestDTO,
    InvestigateIncidentResponseDTO,
    InvestigationDiagnosticsInputDTO,
    InvestigationSourceOutcomeWireDTO,
    PublicEvidenceSource,
    PublicSourceErrorCode,
    PublicSourceStatus,
    PublicSourceType,
    SlowQueryInvestigationInputDTO,
    SlowQueryObservationDTO,
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

        return InvestigationRequest(
            correlation_key=correlation_key,
            initial_hypothesis=public_dto.initial_hypothesis,
            ticket_id=public_dto.ticket_id,
            diagnostics_selection=diagnostics_selection,
            max_steps=None,
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

        return InvestigateIncidentResponseDTO(
            source_outcomes=public_outcomes,
            evidence=public_evidence,
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

        # For non-success, map to approved public code and fixed safe message
        if outcome.error_code not in ERROR_CODE_MAP:
            raise InvalidSourceErrorCodeError(
                "Encountered unmapped internal source outcome error code"
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
            # Step 1: Validate timestamp awareness (fail closed on naive)
            if evidence.timestamp.tzinfo is None:
                raise InvalidEvidenceTimestampError(
                    "Internal diagnostic evidence contains an offset-naive timestamp"
                )

            # Step 2: Normalize to UTC
            utc_timestamp = evidence.timestamp.astimezone(UTC)

            # Step 3: Exact discriminator matching on source_type and tags
            public_source, observation_dto = InvestigationResponseMapper._map_observation(evidence)

            mapped_items.append(
                DiagnosticEvidenceWireDTO(
                    source=public_source,
                    timestamp=utc_timestamp,
                    data=observation_dto,
                )
            )

        # Step 4: Python stable sort on normalized UTC timestamp
        mapped_items.sort(key=lambda item: item.timestamp)

        return tuple(mapped_items)

    @staticmethod
    def _map_observation(
        evidence: DiagnosticEvidence,
    ) -> tuple[
        PublicEvidenceSource,
        TicketObservationDTO
        | DatabaseHealthObservationDTO
        | DeadlockObservationDTO
        | SlowQueryObservationDTO,
    ]:
        data = evidence.data

        # 1. SuperOffice ticket
        if evidence.source_type == EvidenceSourceType.SUPEROFFICE_CRM and evidence.tags == (
            "crm",
            "ticket",
            "superoffice",
        ):
            ticket_dto = TicketObservationDTO(
                ticket_id=data["ticket_id"],
                status=data["status"],
                category=data["category"],
                priority=data["priority"],
            )
            return "superoffice_crm", ticket_dto

        # 2. Database health
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

        # 3. Deadlock
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

        # 4. Slow query
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

        # Any mismatch, extra tags, missing tags, or unknown source fails closed
        raise InvalidEvidenceObservationError(
            "Evidence observation discriminator failed exact tag and source matching"
        )
