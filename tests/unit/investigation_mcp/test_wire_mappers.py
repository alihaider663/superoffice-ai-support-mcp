"""Unit tests for Layer-1 mappers: request, discriminator, error mapping, ordering."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from diag_mcp.contracts.dtos import DeadlockCriteriaDTO, SlowQueryCriteriaDTO
from investigation_mcp.contracts.dtos import (
    DatabaseHealthObservationDTO,
    DeadlockInvestigationInputDTO,
    DeadlockObservationDTO,
    InvestigateIncidentRequestDTO,
    InvestigationDiagnosticsInputDTO,
    SlowQueryInvestigationInputDTO,
    SlowQueryObservationDTO,
    TicketObservationDTO,
)
from investigation_mcp.contracts.errors import (
    InvalidEvidenceObservationError,
    InvalidEvidenceTimestampError,
    InvalidSourceErrorCodeError,
)
from investigation_mcp.contracts.mappers import (
    InvestigationRequestMapper,
    InvestigationResponseMapper,
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
)


@pytest.mark.unit
class TestInvestigationRequestMapper:
    """Tests for mapping public request DTO to internal service request."""

    def test_maps_public_request_with_fresh_correlation_key_and_none_max_steps(self):
        public_req = InvestigateIncidentRequestDTO(
            initial_hypothesis="Test deadlock hypothesis",
            ticket_id=42,
            diagnostics=InvestigationDiagnosticsInputDTO(
                include_database_health=True,
                deadlocks=DeadlockInvestigationInputDTO(limit=5),
                slow_queries=SlowQueryInvestigationInputDTO(limit=15, min_duration_ms=2000),
            ),
        )

        internal_req = InvestigationRequestMapper.to_internal_request(public_req)

        assert isinstance(internal_req, InvestigationRequest)
        assert internal_req.correlation_key.startswith("inv-req-")
        assert internal_req.initial_hypothesis == "Test deadlock hypothesis"
        assert internal_req.ticket_id == 42
        assert internal_req.max_steps is None

        diag_sel = internal_req.diagnostics_selection
        assert isinstance(diag_sel, DiagnosticsSelectionDTO)
        assert diag_sel.include_database_health is True
        assert isinstance(diag_sel.deadlock_criteria, DeadlockCriteriaDTO)
        assert diag_sel.deadlock_criteria.limit == 5
        assert isinstance(diag_sel.slow_query_criteria, SlowQueryCriteriaDTO)
        assert diag_sel.slow_query_criteria.limit == 15
        assert diag_sel.slow_query_criteria.min_duration_ms == 2000


@pytest.mark.unit
class TestObservationDiscriminator:
    """Tests for exact source + tag tuple observation discrimination."""

    def test_exact_ticket_tuple_maps_successfully(self):
        now = datetime.now(UTC)
        ev = DiagnosticEvidence(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            title="SuperOffice ticket observation",
            timestamp=now,
            data={"ticket_id": 1, "status": "Open", "category": "DB", "priority": "High"},
            tags=("crm", "ticket", "superoffice"),
        )
        src, obs = InvestigationResponseMapper._map_observation(ev)
        assert src == "superoffice_crm"
        assert isinstance(obs, TicketObservationDTO)
        assert obs.ticket_id == 1

    def test_exact_health_tuple_maps_successfully(self):
        now = datetime.now(UTC)
        ev = DiagnosticEvidence(
            source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
            title="Database health observation",
            timestamp=now,
            data={"is_healthy": True, "active_connections": 10, "latency_ms": 1.2},
            tags=("diagnostics", "database", "health"),
        )
        src, obs = InvestigationResponseMapper._map_observation(ev)
        assert src == "mssql_diagnostics"
        assert isinstance(obs, DatabaseHealthObservationDTO)
        assert obs.is_healthy is True

    def test_exact_deadlock_tuple_maps_successfully(self):
        now = datetime.now(UTC)
        ev = DiagnosticEvidence(
            source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
            title="Database deadlock observation",
            timestamp=now,
            data={
                "deadlock_id": "dl-100",
                "victim_session_id": 5,
                "participating_session_count": 2,
            },
            tags=("diagnostics", "database", "deadlock"),
        )
        src, obs = InvestigationResponseMapper._map_observation(ev)
        assert src == "mssql_diagnostics"
        assert isinstance(obs, DeadlockObservationDTO)
        assert obs.deadlock_id == "dl-100"

    def test_exact_slow_query_tuple_maps_successfully(self):
        now = datetime.now(UTC)
        ev = DiagnosticEvidence(
            source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
            title="Slow query observation",
            timestamp=now,
            data={
                "query_hash": "0x123",
                "duration_ms": 1500,
                "cpu_time_ms": 800,
                "logical_reads": 2000,
                "execution_count": 4,
            },
            tags=("diagnostics", "database", "slow_query"),
        )
        src, obs = InvestigationResponseMapper._map_observation(ev)
        assert src == "mssql_diagnostics"
        assert isinstance(obs, SlowQueryObservationDTO)
        assert obs.query_hash == "0x123"

    def test_extra_tag_fails_closed(self):
        now = datetime.now(UTC)
        ev = DiagnosticEvidence(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            title="SuperOffice ticket observation",
            timestamp=now,
            data={"ticket_id": 1, "status": "Open", "category": "DB", "priority": "High"},
            tags=("crm", "ticket", "superoffice", "extra_tag"),
        )
        with pytest.raises(InvalidEvidenceObservationError):
            InvestigationResponseMapper._map_observation(ev)

    def test_missing_tag_fails_closed(self):
        now = datetime.now(UTC)
        ev = DiagnosticEvidence(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            title="SuperOffice ticket observation",
            timestamp=now,
            data={"ticket_id": 1, "status": "Open", "category": "DB", "priority": "High"},
            tags=("crm", "ticket"),
        )
        with pytest.raises(InvalidEvidenceObservationError):
            InvestigationResponseMapper._map_observation(ev)

    def test_reordered_tags_fails_closed(self):
        now = datetime.now(UTC)
        ev = DiagnosticEvidence(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            title="SuperOffice ticket observation",
            timestamp=now,
            data={"ticket_id": 1, "status": "Open", "category": "DB", "priority": "High"},
            tags=("ticket", "crm", "superoffice"),
        )
        with pytest.raises(InvalidEvidenceObservationError):
            InvestigationResponseMapper._map_observation(ev)

    def test_wrong_source_with_valid_tags_fails_closed(self):
        now = datetime.now(UTC)
        ev = DiagnosticEvidence(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            title="SuperOffice ticket observation",
            timestamp=now,
            data={"is_healthy": True, "active_connections": 10, "latency_ms": 1.2},
            tags=("diagnostics", "database", "health"),
        )
        with pytest.raises(InvalidEvidenceObservationError):
            InvestigationResponseMapper._map_observation(ev)

    def test_empty_tags_fails_closed(self):
        now = datetime.now(UTC)
        ev = DiagnosticEvidence(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            title="SuperOffice ticket observation",
            timestamp=now,
            data={"ticket_id": 1, "status": "Open", "category": "DB", "priority": "High"},
            tags=(),
        )
        with pytest.raises(InvalidEvidenceObservationError):
            InvestigationResponseMapper._map_observation(ev)


@pytest.mark.unit
class TestErrorMappingAndStatusPreservation:
    """Tests for source outcome mapping and safe error code translation."""

    def test_all_approved_error_codes_map_to_fixed_safe_messages(self):
        approved_codes = [
            (
                "DIAGNOSTIC_LOGS_BLOCKED",
                EvidenceSourceType.APPLICATION_LOGS,
                SourceCollectionStatus.BLOCKED,
            ),
            (
                "KNOWLEDGE_BASE_NOT_CONFIGURED",
                EvidenceSourceType.KNOWLEDGE_BASE,
                SourceCollectionStatus.NOT_CONFIGURED,
            ),
            (
                "SUPEROFFICE_SERVICE_UNAVAILABLE",
                EvidenceSourceType.SUPEROFFICE_CRM,
                SourceCollectionStatus.FAILED,
            ),
            (
                "SUPEROFFICE_RETRIEVAL_FAILED",
                EvidenceSourceType.SUPEROFFICE_CRM,
                SourceCollectionStatus.FAILED,
            ),
            (
                "DIAGNOSTICS_SERVICE_UNAVAILABLE",
                EvidenceSourceType.MSSQL_DIAGNOSTICS,
                SourceCollectionStatus.FAILED,
            ),
            (
                "DIAGNOSTICS_RETRIEVAL_FAILED",
                EvidenceSourceType.MSSQL_DIAGNOSTICS,
                SourceCollectionStatus.FAILED,
            ),
            (
                "SOURCE_EXECUTION_FAILED",
                EvidenceSourceType.SUPEROFFICE_CRM,
                SourceCollectionStatus.FAILED,
            ),
        ]

        for internal_code, src, status in approved_codes:
            outcome = SourceCollectionResult(
                source_type=src,
                status=status,
                evidence=(),
                error_code=internal_code,
                error_message="Raw internal message that must never leak",
            )
            wire = InvestigationResponseMapper._map_source_outcome(outcome)
            assert wire.error_code is not None
            assert wire.error_message is not None
            assert "Raw internal message" not in wire.error_message

    def test_unknown_internal_error_code_fails_closed(self):
        outcome = SourceCollectionResult(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            status=SourceCollectionStatus.FAILED,
            evidence=(),
            error_code="UNKNOWN_CUSTOM_ERROR",
            error_message="Internal detail",
        )
        with pytest.raises(InvalidSourceErrorCodeError):
            InvestigationResponseMapper._map_source_outcome(outcome)

    def test_status_preservation_exact(self):
        statuses = [
            (SourceCollectionStatus.SUCCESS, "SUCCESS"),
            (SourceCollectionStatus.FAILED, "FAILED"),
            (SourceCollectionStatus.BLOCKED, "BLOCKED"),
            (SourceCollectionStatus.NOT_CONFIGURED, "NOT_CONFIGURED"),
            (SourceCollectionStatus.UNAVAILABLE, "UNAVAILABLE"),
        ]
        for internal_status, expected_public in statuses:
            code = (
                None
                if internal_status == SourceCollectionStatus.SUCCESS
                else "SOURCE_EXECUTION_FAILED"
            )
            outcome = SourceCollectionResult(
                source_type=EvidenceSourceType.SUPEROFFICE_CRM,
                status=internal_status,
                evidence=(),
                error_code=code,
                error_message="Error" if code else None,
            )
            wire = InvestigationResponseMapper._map_source_outcome(outcome)
            assert wire.status == expected_public


@pytest.mark.unit
class TestTimestampIntegrityAndOrdering:
    """Tests for evidence timestamp awareness validation and stable ordering."""

    def test_naive_internal_timestamp_fails_closed(self):
        naive_dt = datetime(2026, 9, 1, 10, 0, 0)
        ev = DiagnosticEvidence(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            title="SuperOffice ticket observation",
            timestamp=naive_dt,
            data={"ticket_id": 1, "status": "Open", "category": "DB", "priority": "High"},
            tags=("crm", "ticket", "superoffice"),
        )
        with pytest.raises(InvalidEvidenceTimestampError):
            InvestigationResponseMapper._map_evidence_items((ev,))

    def test_aware_offsets_normalized_to_utc(self):
        tz_plus_3 = timezone(timedelta(hours=3))
        aware_dt = datetime(2026, 9, 1, 15, 0, 0, tzinfo=tz_plus_3)
        ev = DiagnosticEvidence(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            title="SuperOffice ticket observation",
            timestamp=aware_dt,
            data={"ticket_id": 1, "status": "Open", "category": "DB", "priority": "High"},
            tags=("crm", "ticket", "superoffice"),
        )
        items = InvestigationResponseMapper._map_evidence_items((ev,))
        assert len(items) == 1
        assert items[0].timestamp.tzinfo == UTC
        assert items[0].timestamp.hour == 12

    def test_stable_chronological_sort_and_tie_preservation(self):
        t1 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)  # Equal instant
        t3 = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC)  # Earlier instant

        ev1 = DiagnosticEvidence(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            title="Ticket",
            timestamp=t1,
            data={"ticket_id": 1, "status": "Open", "category": "DB", "priority": "High"},
            tags=("crm", "ticket", "superoffice"),
        )
        ev2 = DiagnosticEvidence(
            source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
            title="Health",
            timestamp=t2,
            data={"is_healthy": True, "active_connections": 5, "latency_ms": 1.0},
            tags=("diagnostics", "database", "health"),
        )
        ev3 = DiagnosticEvidence(
            source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
            title="Deadlock",
            timestamp=t3,
            data={"deadlock_id": "dl-1", "victim_session_id": 1, "participating_session_count": 2},
            tags=("diagnostics", "database", "deadlock"),
        )

        # In raw aggregation: ev1, ev2, ev3
        mapped = InvestigationResponseMapper._map_evidence_items((ev1, ev2, ev3))

        # Expected: ev3 first (earliest: 9am).
        # ev1 and ev2 both at 10am: ev1 (SuperOffice) must remain before ev2 (Health)
        assert mapped[0].data.observation_type == "deadlock"
        assert mapped[1].data.observation_type == "ticket"
        assert mapped[2].data.observation_type == "database_health"

    def test_map_diagnostics_selection_none_returns_none(self):
        res = InvestigationRequestMapper._map_diagnostics_selection(None)
        assert res is None
