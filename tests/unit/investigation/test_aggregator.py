"""Unit tests for EvidenceAggregatorEngine and source outcome models."""

import pytest
from pydantic import ValidationError

from platform_core.errors import DomainValidationError
from platform_investigation.aggregator import EvidenceAggregatorEngine
from platform_investigation.errors import (
    DuplicateEvidenceIdError,
    EvidenceProvenanceMismatchError,
)
from platform_investigation.interfaces import (
    DiagnosticLogCollector,
    EvidenceAggregator,
    EvidenceCollector,
    OutcomeAwareEvidenceCollector,
)
from platform_investigation.models import (
    DiagnosticEvidence,
    EvidenceAggregationResult,
    EvidenceSourceType,
    SourceCollectionResult,
    SourceCollectionStatus,
)


class MockOutcomeCollector(OutcomeAwareEvidenceCollector):
    """Deterministic mock outcome-aware collector for offline testing."""

    def __init__(
        self,
        source_type: EvidenceSourceType,
        outcome: SourceCollectionResult | None = None,
        exception_to_raise: Exception | None = None,
    ) -> None:
        self._source_type = source_type
        self._outcome = outcome
        self._exception_to_raise = exception_to_raise
        self.call_history: list[tuple[str, str]] = []

    @property
    def source_type(self) -> EvidenceSourceType:
        return self._source_type

    async def collect(
        self,
        investigation_id: str,
        correlation_key: str,
    ) -> SourceCollectionResult:
        self.call_history.append((investigation_id, correlation_key))
        if self._exception_to_raise is not None:
            raise self._exception_to_raise
        if self._outcome is not None:
            return self._outcome
        return SourceCollectionResult(
            source_type=self._source_type,
            status=SourceCollectionStatus.SUCCESS,
            evidence=(),
        )


def _make_evidence(
    source_type: EvidenceSourceType,
    evidence_id: str = "ev-1",
    title: str = "Test Evidence",
    confidence: float = 0.9,
) -> DiagnosticEvidence:
    return DiagnosticEvidence(
        evidence_id=evidence_id,
        source_type=source_type,
        title=title,
        confidence_score=confidence,
        data={"metric": 42},
        tags=("test",),
    )


# =========================================================================
# Protocol Verification Tests
# =========================================================================


def test_aggregator_implements_protocol() -> None:
    engine = EvidenceAggregatorEngine()
    assert isinstance(engine, EvidenceAggregator)


def test_existing_protocols_preserved() -> None:
    """Verify legacy EvidenceCollector and DiagnosticLogCollector remain valid protocols."""
    assert issubclass(EvidenceCollector, object)
    assert issubclass(DiagnosticLogCollector, object)
    assert issubclass(OutcomeAwareEvidenceCollector, object)


# =========================================================================
# SourceCollectionResult Model Validation Tests
# =========================================================================


def test_source_collection_result_valid_success_with_and_without_evidence() -> None:
    """SUCCESS status is valid with zero or more evidence items and no error metadata."""
    ev = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, evidence_id="ev-so-1")

    # With evidence
    res1 = SourceCollectionResult(
        source_type=EvidenceSourceType.SUPEROFFICE_CRM,
        status=SourceCollectionStatus.SUCCESS,
        evidence=(ev,),
    )
    assert res1.status == SourceCollectionStatus.SUCCESS
    assert len(res1.evidence) == 1
    assert res1.error_code is None
    assert res1.error_message is None

    # Zero evidence
    res2 = SourceCollectionResult(
        source_type=EvidenceSourceType.SUPEROFFICE_CRM,
        status=SourceCollectionStatus.SUCCESS,
        evidence=(),
    )
    assert res2.status == SourceCollectionStatus.SUCCESS
    assert len(res2.evidence) == 0
    assert res2.error_code is None
    assert res2.error_message is None


def test_source_collection_result_success_rejects_error_code_and_message() -> None:
    """SUCCESS status must not contain error_code or error_message."""
    with pytest.raises(ValidationError):
        SourceCollectionResult(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            status=SourceCollectionStatus.SUCCESS,
            evidence=(),
            error_code="UNEXPECTED_ERROR_CODE",
        )

    with pytest.raises(ValidationError):
        SourceCollectionResult(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            status=SourceCollectionStatus.SUCCESS,
            evidence=(),
            error_message="Should not have message on success",
        )


@pytest.mark.parametrize(
    "status",
    [
        SourceCollectionStatus.BLOCKED,
        SourceCollectionStatus.NOT_CONFIGURED,
        SourceCollectionStatus.UNAVAILABLE,
        SourceCollectionStatus.FAILED,
    ],
)
def test_source_collection_result_non_success_requires_empty_evidence(
    status: SourceCollectionStatus,
) -> None:
    """Non-SUCCESS status must have empty evidence tuple."""
    # Valid with empty evidence
    valid_res = SourceCollectionResult(
        source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
        status=status,
        evidence=(),
        error_code="ERR_TEST",
    )
    assert valid_res.status == status
    assert len(valid_res.evidence) == 0

    # Invalid with non-empty evidence
    ev = _make_evidence(EvidenceSourceType.MSSQL_DIAGNOSTICS, evidence_id="ev-db-1")
    with pytest.raises(ValidationError):
        SourceCollectionResult(
            source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
            status=status,
            evidence=(ev,),
            error_code="ERR_TEST",
        )


@pytest.mark.parametrize(
    "status",
    [
        SourceCollectionStatus.BLOCKED,
        SourceCollectionStatus.NOT_CONFIGURED,
        SourceCollectionStatus.UNAVAILABLE,
        SourceCollectionStatus.FAILED,
    ],
)
def test_source_collection_result_non_success_requires_normalized_error_code(
    status: SourceCollectionStatus,
) -> None:
    """Non-SUCCESS status must contain a non-empty normalized error_code."""
    # Missing error_code (None)
    with pytest.raises(ValidationError):
        SourceCollectionResult(
            source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
            status=status,
            evidence=(),
            error_code=None,
        )

    # Blank/empty error_code
    with pytest.raises(ValidationError):
        SourceCollectionResult(
            source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
            status=status,
            evidence=(),
            error_code="   ",
        )


def test_source_collection_result_rejects_mismatched_evidence_source_type() -> None:
    """Result rejects evidence items whose source_type differs from result.source_type."""
    ev_kb = _make_evidence(EvidenceSourceType.KNOWLEDGE_BASE, evidence_id="ev-kb-1")
    with pytest.raises(ValidationError):
        SourceCollectionResult(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            status=SourceCollectionStatus.SUCCESS,
            evidence=(ev_kb,),
        )


# =========================================================================
# EvidenceAggregationResult Computed Properties Tests
# =========================================================================


def test_evidence_aggregation_result_rejects_manual_evidence_field() -> None:
    """Evidence cannot be passed as a stored field; it is authoritatively derived."""
    ev = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-1")
    with pytest.raises(ValidationError):
        EvidenceAggregationResult(
            investigation_id="inv-123",
            correlation_key="ticket:10209",
            evidence=(ev,),  # type: ignore[call-arg]
            source_outcomes=(),
        )


def test_evidence_aggregation_result_properties() -> None:
    """Computed properties correctly reflect source outcomes without mutable drift."""
    ev_so = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-so-1")
    outcomes = (
        SourceCollectionResult(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            status=SourceCollectionStatus.SUCCESS,
            evidence=(ev_so,),
        ),
        SourceCollectionResult(
            source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
            status=SourceCollectionStatus.BLOCKED,
            evidence=(),
            error_code="PHASE_2B_3_BLOCKED_SCHEMA",
        ),
        SourceCollectionResult(
            source_type=EvidenceSourceType.KNOWLEDGE_BASE,
            status=SourceCollectionStatus.NOT_CONFIGURED,
            evidence=(),
            error_code="KNOWLEDGE_BACKEND_NOT_CONFIGURED",
        ),
    )

    agg = EvidenceAggregationResult(
        investigation_id="inv-123",
        correlation_key="ticket:10209",
        source_outcomes=outcomes,
    )

    assert agg.total_sources == 3
    assert agg.successful_sources_count == 1
    assert agg.has_failures is True
    assert agg.has_partial_failures is True
    assert agg.all_sources_failed is False
    assert len(agg.evidence) == 1
    assert agg.evidence[0].evidence_id == "ev-so-1"


def test_evidence_aggregation_result_zero_sources_semantics() -> None:
    """Zero source outcomes evaluates safely without false failure classification."""
    agg = EvidenceAggregationResult(
        investigation_id="inv-empty",
        correlation_key="key-empty",
        source_outcomes=(),
    )

    assert agg.total_sources == 0
    assert agg.successful_sources_count == 0
    assert agg.has_failures is False
    assert agg.has_partial_failures is False
    assert agg.all_sources_failed is False
    assert agg.evidence == ()


def test_evidence_aggregation_result_derives_flattened_evidence_in_order() -> None:
    """Evidence is derived strictly in source registration order and per-collector order."""
    ev1 = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-1")
    ev2 = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-2")
    ev3 = _make_evidence(EvidenceSourceType.MSSQL_DIAGNOSTICS, "ev-3")

    outcomes = (
        SourceCollectionResult(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            status=SourceCollectionStatus.SUCCESS,
            evidence=(ev1, ev2),
        ),
        SourceCollectionResult(
            source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
            status=SourceCollectionStatus.SUCCESS,
            evidence=(ev3,),
        ),
    )

    agg = EvidenceAggregationResult(
        investigation_id="inv-flat",
        correlation_key="key-flat",
        source_outcomes=outcomes,
    )

    assert agg.evidence == (ev1, ev2, ev3)


# =========================================================================
# EvidenceAggregatorEngine Execution Tests
# =========================================================================


@pytest.mark.asyncio
async def test_aggregator_all_sources_succeed() -> None:
    """All registered collectors succeed and combine evidence in deterministic order."""
    ev_so = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-so-1", "Ticket record")
    ev_db = _make_evidence(EvidenceSourceType.MSSQL_DIAGNOSTICS, "ev-db-1", "Deadlock graph")

    col1 = MockOutcomeCollector(
        source_type=EvidenceSourceType.SUPEROFFICE_CRM,
        outcome=SourceCollectionResult(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            status=SourceCollectionStatus.SUCCESS,
            evidence=(ev_so,),
        ),
    )
    col2 = MockOutcomeCollector(
        source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
        outcome=SourceCollectionResult(
            source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
            status=SourceCollectionStatus.SUCCESS,
            evidence=(ev_db,),
        ),
    )

    engine = EvidenceAggregatorEngine(collectors=[col1, col2])
    result = await engine.aggregate(investigation_id="inv-100", correlation_key="req-xyz")

    assert result.investigation_id == "inv-100"
    assert result.correlation_key == "req-xyz"
    assert result.total_sources == 2
    assert result.successful_sources_count == 2
    assert result.has_failures is False
    assert result.has_partial_failures is False
    assert result.all_sources_failed is False
    assert len(result.evidence) == 2
    assert result.evidence[0].evidence_id == "ev-so-1"
    assert result.evidence[1].evidence_id == "ev-db-1"


@pytest.mark.asyncio
async def test_aggregator_sequential_execution_order() -> None:
    """Collectors are executed in strict deterministic registration order."""
    call_order: list[str] = []

    class OrderTrackingCollector(OutcomeAwareEvidenceCollector):
        def __init__(self, name: str, source: EvidenceSourceType) -> None:
            self._name = name
            self._source = source

        @property
        def source_type(self) -> EvidenceSourceType:
            return self._source

        async def collect(self, _inv_id: str, _corr: str) -> SourceCollectionResult:
            call_order.append(self._name)
            return SourceCollectionResult(
                source_type=self._source,
                status=SourceCollectionStatus.SUCCESS,
                evidence=(),
            )

    c1 = OrderTrackingCollector("first", EvidenceSourceType.SUPEROFFICE_CRM)
    c2 = OrderTrackingCollector("second", EvidenceSourceType.MSSQL_DIAGNOSTICS)
    c3 = OrderTrackingCollector("third", EvidenceSourceType.KNOWLEDGE_BASE)

    engine = EvidenceAggregatorEngine([c1, c2, c3])
    await engine.aggregate("inv-1", "corr-1")

    assert call_order == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_aggregator_partial_availability() -> None:
    """Successful source evidence is preserved while blocked/unconfigured sources are captured."""
    ev_so = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-so-1", "Ticket metadata")

    col_so = MockOutcomeCollector(
        source_type=EvidenceSourceType.SUPEROFFICE_CRM,
        outcome=SourceCollectionResult(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            status=SourceCollectionStatus.SUCCESS,
            evidence=(ev_so,),
        ),
    )
    col_db = MockOutcomeCollector(
        source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
        outcome=SourceCollectionResult(
            source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
            status=SourceCollectionStatus.BLOCKED,
            evidence=(),
            error_code="PHASE_2B_3_BLOCKED_SCHEMA",
            error_message="Schema unverified",
        ),
    )
    col_kb = MockOutcomeCollector(
        source_type=EvidenceSourceType.KNOWLEDGE_BASE,
        outcome=SourceCollectionResult(
            source_type=EvidenceSourceType.KNOWLEDGE_BASE,
            status=SourceCollectionStatus.NOT_CONFIGURED,
            evidence=(),
            error_code="KNOWLEDGE_BACKEND_NOT_CONFIGURED",
        ),
    )

    engine = EvidenceAggregatorEngine([col_so, col_db, col_kb])
    result = await engine.aggregate(investigation_id="inv-partial", correlation_key="ticket:55")

    assert result.total_sources == 3
    assert result.successful_sources_count == 1
    assert result.has_failures is True
    assert result.has_partial_failures is True
    assert result.all_sources_failed is False
    assert len(result.evidence) == 1
    assert result.evidence[0].evidence_id == "ev-so-1"

    # Confirm outcomes reflect exact statuses
    statuses = {o.source_type: o.status for o in result.source_outcomes}
    assert statuses[EvidenceSourceType.SUPEROFFICE_CRM] == SourceCollectionStatus.SUCCESS
    assert statuses[EvidenceSourceType.MSSQL_DIAGNOSTICS] == SourceCollectionStatus.BLOCKED
    assert statuses[EvidenceSourceType.KNOWLEDGE_BASE] == SourceCollectionStatus.NOT_CONFIGURED


@pytest.mark.asyncio
async def test_aggregator_all_sources_unavailable_produces_zero_evidence() -> None:
    """When all sources are blocked/unavailable, evidence is empty with zero fake evidence."""
    col1 = MockOutcomeCollector(
        source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
        outcome=SourceCollectionResult(
            source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
            status=SourceCollectionStatus.BLOCKED,
            evidence=(),
            error_code="PHASE_2B_3_BLOCKED_SCHEMA",
        ),
    )
    col2 = MockOutcomeCollector(
        source_type=EvidenceSourceType.KNOWLEDGE_BASE,
        outcome=SourceCollectionResult(
            source_type=EvidenceSourceType.KNOWLEDGE_BASE,
            status=SourceCollectionStatus.UNAVAILABLE,
            evidence=(),
            error_code="OPERATION_TIMEOUT",
        ),
    )

    engine = EvidenceAggregatorEngine([col1, col2])
    result = await engine.aggregate("inv-none", "ticket:0")

    assert result.total_sources == 2
    assert result.successful_sources_count == 0
    assert result.has_failures is True
    assert result.has_partial_failures is False
    assert result.all_sources_failed is True
    assert len(result.evidence) == 0


@pytest.mark.asyncio
async def test_aggregator_unexpected_collector_exception_isolation() -> None:
    """Unexpected collector exception is safely caught, sanitized, and isolated."""
    ev_so = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-so-1")

    col_good = MockOutcomeCollector(
        source_type=EvidenceSourceType.SUPEROFFICE_CRM,
        outcome=SourceCollectionResult(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            status=SourceCollectionStatus.SUCCESS,
            evidence=(ev_so,),
        ),
    )
    col_bad = MockOutcomeCollector(
        source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
        exception_to_raise=RuntimeError("Secret DB password failed on port 1433"),
    )

    engine = EvidenceAggregatorEngine([col_good, col_bad])
    result = await engine.aggregate("inv-exc", "req:1")

    assert result.total_sources == 2
    assert result.successful_sources_count == 1
    assert result.has_failures is True
    assert result.has_partial_failures is True
    assert result.all_sources_failed is False
    assert len(result.evidence) == 1

    bad_outcome = result.source_outcomes[1]
    assert bad_outcome.status == SourceCollectionStatus.FAILED
    assert bad_outcome.error_code == "SOURCE_EXECUTION_FAILED"
    # Verify raw sensitive exception text is not leaked in error_message
    assert "Secret DB password" not in str(bad_outcome.error_message)


# =========================================================================
# Provenance & Duplicate Evidence Identity Tests
# =========================================================================


@pytest.mark.asyncio
async def test_aggregator_fails_closed_on_duplicate_evidence_id() -> None:
    """Duplicate evidence_id across collectors raises DuplicateEvidenceIdError."""
    ev1 = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, evidence_id="ev-duplicate-id")
    ev2 = _make_evidence(EvidenceSourceType.MSSQL_DIAGNOSTICS, evidence_id="ev-duplicate-id")

    col1 = MockOutcomeCollector(
        source_type=EvidenceSourceType.SUPEROFFICE_CRM,
        outcome=SourceCollectionResult(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            status=SourceCollectionStatus.SUCCESS,
            evidence=(ev1,),
        ),
    )
    col2 = MockOutcomeCollector(
        source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
        outcome=SourceCollectionResult(
            source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
            status=SourceCollectionStatus.SUCCESS,
            evidence=(ev2,),
        ),
    )

    engine = EvidenceAggregatorEngine([col1, col2])
    with pytest.raises(DuplicateEvidenceIdError) as exc_info:
        await engine.aggregate("inv-dup", "corr-dup")

    assert exc_info.value.evidence_id == "ev-duplicate-id"
    assert exc_info.value.error_code == "DUPLICATE_EVIDENCE_ID"


@pytest.mark.asyncio
async def test_aggregator_fails_closed_on_outcome_source_mismatch() -> None:
    """Collector outcome declaring a different source_type than collector raises error."""
    col = MockOutcomeCollector(
        source_type=EvidenceSourceType.SUPEROFFICE_CRM,
        outcome=SourceCollectionResult(
            source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,  # Mismatched
            status=SourceCollectionStatus.SUCCESS,
            evidence=(),
        ),
    )

    engine = EvidenceAggregatorEngine([col])
    with pytest.raises(EvidenceProvenanceMismatchError) as exc_info:
        await engine.aggregate("inv-mismatch", "corr-1")

    assert exc_info.value.expected_source == "superoffice_crm"
    assert exc_info.value.actual_source == "mssql_diagnostics"


@pytest.mark.asyncio
async def test_aggregator_fails_closed_on_item_source_mismatch_bypassed_validation() -> None:
    """Collector returning mismatched item raises EvidenceProvenanceMismatchError."""
    ev_mismatched = _make_evidence(EvidenceSourceType.KNOWLEDGE_BASE, evidence_id="ev-raw-1")

    # Bypass Pydantic validator using model_construct to test aggregator-level defensive check
    outcome = SourceCollectionResult.model_construct(
        source_type=EvidenceSourceType.SUPEROFFICE_CRM,
        status=SourceCollectionStatus.SUCCESS,
        evidence=(ev_mismatched,),
        error_code=None,
        error_message=None,
    )

    col = MockOutcomeCollector(
        source_type=EvidenceSourceType.SUPEROFFICE_CRM,
        outcome=outcome,
    )

    engine = EvidenceAggregatorEngine([col])
    with pytest.raises(EvidenceProvenanceMismatchError) as exc_info:
        await engine.aggregate("inv-item-mismatch", "corr-item")

    assert exc_info.value.expected_source == "superoffice_crm"
    assert exc_info.value.actual_source == "knowledge_base"
    assert exc_info.value.evidence_id == "ev-raw-1"


# =========================================================================
# Input Validation Tests
# =========================================================================


@pytest.mark.asyncio
async def test_aggregator_validates_empty_inputs() -> None:
    """aggregate rejects empty or whitespace investigation_id and correlation_key."""
    engine = EvidenceAggregatorEngine()

    with pytest.raises(DomainValidationError):
        await engine.aggregate(investigation_id="", correlation_key="valid-key")

    with pytest.raises(DomainValidationError):
        await engine.aggregate(investigation_id="valid-id", correlation_key="  ")
