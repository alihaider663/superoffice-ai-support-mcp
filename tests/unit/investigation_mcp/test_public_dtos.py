"""Unit tests for Phase 4.2 public investigation wire DTOs and schema contracts."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from investigation_mcp.contracts.dtos import (
    DatabaseHealthObservationDTO,
    DeadlockInvestigationInputDTO,
    DeadlockObservationDTO,
    DiagnosticEvidenceWireDTO,
    InvestigateIncidentRequestDTO,
    InvestigateIncidentResponseDTO,
    InvestigationDiagnosticsInputDTO,
    InvestigationSourceOutcomeWireDTO,
    SlowQueryInvestigationInputDTO,
    SlowQueryObservationDTO,
    TicketObservationDTO,
)


@pytest.mark.unit
class TestInvestigateIncidentRequestDTO:
    """Tests for public investigation request contract and boundary constraints."""

    def test_valid_request_with_ticket_only(self):
        req = InvestigateIncidentRequestDTO(
            initial_hypothesis="Test incident hypothesis",
            ticket_id=123,
        )
        assert req.initial_hypothesis == "Test incident hypothesis"
        assert req.ticket_id == 123
        assert req.diagnostics is None

    def test_valid_request_with_diagnostics_only(self):
        req = InvestigateIncidentRequestDTO(
            initial_hypothesis="Database deadlocks observed",
            diagnostics=InvestigationDiagnosticsInputDTO(include_database_health=True),
        )
        assert req.ticket_id is None
        assert req.diagnostics is not None
        assert req.diagnostics.include_database_health is True

    def test_initial_hypothesis_required(self):
        with pytest.raises(ValidationError) as exc:
            InvestigateIncidentRequestDTO(ticket_id=1)  # type: ignore[call-arg]
        assert "initial_hypothesis" in str(exc.value)

    def test_initial_hypothesis_whitespace_padding_rejected(self):
        with pytest.raises(ValidationError):
            InvestigateIncidentRequestDTO(
                initial_hypothesis="  Padded hypothesis  ",
                ticket_id=1,
            )

    def test_initial_hypothesis_empty_rejected(self):
        with pytest.raises(ValidationError):
            InvestigateIncidentRequestDTO(
                initial_hypothesis="",
                ticket_id=1,
            )

    def test_initial_hypothesis_too_long_rejected(self):
        with pytest.raises(ValidationError):
            InvestigateIncidentRequestDTO(
                initial_hypothesis="a" * 257,
                ticket_id=1,
            )

    def test_ticket_id_less_than_one_rejected(self):
        with pytest.raises(ValidationError):
            InvestigateIncidentRequestDTO(
                initial_hypothesis="Valid hypothesis",
                ticket_id=0,
            )

    def test_zero_selection_ticket_none_and_diagnostics_none_rejected(self):
        with pytest.raises(ValidationError) as exc:
            InvestigateIncidentRequestDTO(
                initial_hypothesis="Valid hypothesis",
                ticket_id=None,
                diagnostics=None,
            )
        assert "At least one investigation target" in str(exc.value)

    def test_zero_selection_ticket_none_and_empty_diagnostics_rejected(self):
        with pytest.raises(ValidationError) as exc:
            InvestigateIncidentRequestDTO(
                initial_hypothesis="Valid hypothesis",
                ticket_id=None,
                diagnostics=InvestigationDiagnosticsInputDTO(),
            )
        assert "At least one investigation target" in str(exc.value)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            InvestigateIncidentRequestDTO(
                initial_hypothesis="Valid hypothesis",
                ticket_id=1,
                correlation_key="should-be-forbidden",  # type: ignore[call-arg]
            )


@pytest.mark.unit
class TestDiagnosticsCriteriaDTOs:
    """Tests for Deadlock and Slow Query public criteria and D02 bounds."""

    def test_deadlock_criteria_d02_limits(self):
        # Limit 1..50 valid
        dto = DeadlockInvestigationInputDTO(limit=50)
        assert dto.limit == 50

        dto_min = DeadlockInvestigationInputDTO(limit=1)
        assert dto_min.limit == 1

        # Limit > 50 rejected by D02
        with pytest.raises(ValidationError):
            DeadlockInvestigationInputDTO(limit=51)

        # Limit < 1 rejected
        with pytest.raises(ValidationError):
            DeadlockInvestigationInputDTO(limit=0)

    def test_slow_query_criteria_d02_limits(self):
        dto = SlowQueryInvestigationInputDTO(limit=50, min_duration_ms=1000)
        assert dto.limit == 50

        with pytest.raises(ValidationError):
            SlowQueryInvestigationInputDTO(limit=51)

        with pytest.raises(ValidationError):
            SlowQueryInvestigationInputDTO(limit=0)

        with pytest.raises(ValidationError):
            SlowQueryInvestigationInputDTO(min_duration_ms=0)

    def test_timezone_aware_required_naive_rejected(self):
        naive_dt = datetime(2026, 9, 1, 10, 0, 0)
        with pytest.raises(ValidationError) as exc:
            DeadlockInvestigationInputDTO(start_time=naive_dt)
        assert "explicit timezone offset" in str(exc.value)

        with pytest.raises(ValidationError) as exc:
            SlowQueryInvestigationInputDTO(end_time=naive_dt)
        assert "explicit timezone offset" in str(exc.value)

    def test_timezone_aware_normalized_to_utc(self):
        tz_plus_2 = timezone(timedelta(hours=2))
        aware_dt = datetime(2026, 9, 1, 12, 0, 0, tzinfo=tz_plus_2)
        dto = DeadlockInvestigationInputDTO(start_time=aware_dt)
        assert dto.start_time is not None
        assert dto.start_time.tzinfo == UTC
        assert dto.start_time.hour == 10

    def test_start_time_after_end_time_rejected(self):
        t1 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC)
        with pytest.raises(ValidationError) as exc:
            DeadlockInvestigationInputDTO(start_time=t1, end_time=t2)
        assert "start_time cannot be after end_time" in str(exc.value)


@pytest.mark.unit
class TestPublicObservationDTOs:
    """Tests for typed discriminated observation union and strict allowlists."""

    def test_ticket_observation_fields(self):
        obs = TicketObservationDTO(
            ticket_id=42,
            title="Database Connection Error",
            status="Open",
            category="Database",
            priority="High",
            sanitized_description="Server threw 504 timeout",
            sanitized_customer_reference="CUST-123",
        )
        assert obs.observation_type == "ticket"
        assert obs.ticket_id == 42
        assert obs.title == "Database Connection Error"
        assert obs.status == "Open"
        assert obs.sanitized_description == "Server threw 504 timeout"
        assert obs.sanitized_customer_reference == "CUST-123"

        # Extra fields forbidden
        with pytest.raises(ValidationError):
            TicketObservationDTO(
                ticket_id=42,
                status="Open",
                category="Database",
                priority="High",
                forbidden_extra_field="leak",  # type: ignore[call-arg]
            )

    def test_database_health_observation_fields(self):
        obs = DatabaseHealthObservationDTO(
            is_healthy=True,
            active_connections=12,
            latency_ms=1.5,
        )
        assert obs.observation_type == "database_health"
        assert obs.is_healthy is True

        with pytest.raises(ValidationError):
            DatabaseHealthObservationDTO(
                is_healthy=True,
                active_connections=12,
                latency_ms=1.5,
                status_summary="ONLINE",  # type: ignore[call-arg]
            )

    def test_deadlock_observation_fields(self):
        obs = DeadlockObservationDTO(
            deadlock_id="dl-1",
            victim_session_id=10,
            participating_session_count=2,
        )
        assert obs.observation_type == "deadlock"

        with pytest.raises(ValidationError):
            DeadlockObservationDTO(
                deadlock_id="dl-1",
                victim_session_id=10,
                participating_session_count=2,
                summary="leaked summary",  # type: ignore[call-arg]
            )

    def test_slow_query_observation_fields(self):
        obs = SlowQueryObservationDTO(
            query_hash="0xABC",
            duration_ms=2500,
            cpu_time_ms=1200,
            logical_reads=50000,
            execution_count=10,
        )
        assert obs.observation_type == "slow_query"

        with pytest.raises(ValidationError):
            SlowQueryObservationDTO(
                query_hash="0xABC",
                duration_ms=2500,
                cpu_time_ms=1200,
                logical_reads=50000,
                execution_count=10,
                sql_text="SELECT * FROM table",  # type: ignore[call-arg]
            )

    def test_evidence_wire_dto_single_discriminator(self):
        obs = TicketObservationDTO(
            ticket_id=10,
            status="Open",
            category="Billing",
            priority="Normal",
        )
        now = datetime.now(UTC)
        wire = DiagnosticEvidenceWireDTO(
            source="superoffice_crm",
            timestamp=now,
            data=obs,
        )
        assert wire.source == "superoffice_crm"
        assert wire.timestamp == now
        assert wire.data.observation_type == "ticket"
        # No wrapper observation_type exists
        assert not hasattr(wire, "observation_type")


@pytest.mark.unit
class TestSourceOutcomeDTO:
    """Tests for InvestigationSourceOutcomeWireDTO validation invariants."""

    def test_success_outcome_requires_no_error(self):
        outcome = InvestigationSourceOutcomeWireDTO(
            source="superoffice_crm",
            status="SUCCESS",
            error_code=None,
            error_message=None,
        )
        assert outcome.status == "SUCCESS"

        with pytest.raises(ValidationError):
            InvestigationSourceOutcomeWireDTO(
                source="superoffice_crm",
                status="SUCCESS",
                error_code="SUPEROFFICE_UNAVAILABLE",
                error_message="Error",
            )

    def test_non_success_outcome_requires_error_code_and_message(self):
        outcome = InvestigationSourceOutcomeWireDTO(
            source="application_logs",
            status="BLOCKED",
            error_code="DIAGNOSTIC_LOGS_BLOCKED",
            error_message="Application logging source is currently blocked.",
        )
        assert outcome.status == "BLOCKED"

        with pytest.raises(ValidationError):
            InvestigationSourceOutcomeWireDTO(
                source="application_logs",
                status="BLOCKED",
                error_code=None,
                error_message=None,
            )

    def test_non_success_all_statuses_require_error_code_and_message(self):
        for status, src in [
            ("BLOCKED", "application_logs"),
            ("NOT_CONFIGURED", "knowledge_base"),
            ("FAILED", "superoffice_crm"),
            ("UNAVAILABLE", "mssql_diagnostics"),
        ]:
            with pytest.raises(ValidationError) as exc:
                InvestigationSourceOutcomeWireDTO(
                    source=src,  # type: ignore[arg-type]
                    status=status,  # type: ignore[arg-type]
                    error_code=None,
                    error_message="Message without code",
                )
            assert "error_code and error_message are required when status is not SUCCESS" in str(
                exc.value
            )

            with pytest.raises(ValidationError) as exc:
                InvestigationSourceOutcomeWireDTO(
                    source=src,  # type: ignore[arg-type]
                    status=status,  # type: ignore[arg-type]
                    error_code="SOURCE_EXECUTION_FAILED",
                    error_message=None,
                )
            assert "error_code and error_message are required when status is not SUCCESS" in str(
                exc.value
            )

    def test_response_dto_contains_only_approved_fields(self):
        resp = InvestigateIncidentResponseDTO(
            source_outcomes=(
                InvestigationSourceOutcomeWireDTO(
                    source="superoffice_crm",
                    status="SUCCESS",
                ),
            ),
            evidence=(),
        )
        dump = resp.model_dump()
        assert set(dump.keys()) == {"source_outcomes", "evidence"}

    def test_slow_query_time_window_validation(self):
        t1 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC)
        with pytest.raises(ValidationError) as exc:
            SlowQueryInvestigationInputDTO(start_time=t1, end_time=t2)
        assert "start_time cannot be after end_time" in str(exc.value)

    def test_criteria_none_timestamps_preserved(self):
        d = DeadlockInvestigationInputDTO(start_time=None, end_time=None)
        assert d.start_time is None
        assert d.end_time is None

        s = SlowQueryInvestigationInputDTO(start_time=None, end_time=None)
        assert s.start_time is None
        assert s.end_time is None
