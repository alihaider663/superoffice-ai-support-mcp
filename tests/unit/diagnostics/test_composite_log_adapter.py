"""Unit tests for CompositeLogSearchAdapter (Gate 7A.4C-R1 Sections 13, 14)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from diag_mcp.adapters.composite_log_adapter import CompositeLogSearchAdapter
from diag_mcp.adapters.factory import create_composite_log_adapter
from diag_mcp.contracts.dtos import (
    BoundedDiagnosticResultDTO,
    LogRecordDomainDTO,
    LogSearchCriteriaDTO,
)
from diag_mcp.contracts.errors import LogSearchError
from diag_mcp.contracts.interfaces import LogSearchClient
from diag_mcp.settings import DiagnosticsServerSettings


class MockLogSearchClient(LogSearchClient):
    """Controlled mock LogSearchClient for testing composite behavior."""

    def __init__(
        self,
        records: list[LogRecordDomainDTO] | None = None,
        *,
        is_truncated: bool = False,
        total_matched: int | None = None,
        should_fail: bool = False,
        failure_error_code: str = "LOG_BACKEND_FAILED",
    ) -> None:
        self._records = records or []
        self._is_truncated = is_truncated
        self._total_matched = total_matched if total_matched is not None else len(self._records)
        self._should_fail = should_fail
        self._failure_error_code = failure_error_code
        self.last_criteria: LogSearchCriteriaDTO | None = None

    async def search_logs(
        self, criteria: LogSearchCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[LogRecordDomainDTO]:
        self.last_criteria = criteria
        if self._should_fail:
            raise LogSearchError(
                message="Backend search failed.",
                error_code=self._failure_error_code,
            )

        limit = criteria.limit or len(self._records)
        sliced = tuple(self._records[:limit])
        return BoundedDiagnosticResultDTO[LogRecordDomainDTO](
            items=sliced,
            returned_count=len(sliced),
            total_matched=self._total_matched,
            is_truncated=self._is_truncated or (len(self._records) > limit),
        )


def _make_record(
    log_id: str,
    ts: datetime,
    service_name: str = "test_service",
    message: str = "test message",
    severity: str = "WARN",
) -> LogRecordDomainDTO:
    return LogRecordDomainDTO(
        log_id=log_id,
        timestamp=ts,
        service_name=service_name,
        severity=severity,
        message=message,
        correlation_id=None,
        ticket_id=None,
        raw_context={},
    )


# ============================================================================
# Section 13: Required Configuration Semantic Matrix Tests
# ============================================================================


@pytest.mark.asyncio
async def test_matrix_h_neither_enabled_fails_closed() -> None:
    """H: Verify neither source enabled raises LOG_SEARCH_BACKEND_NOT_CONFIGURED."""
    adapter = CompositeLogSearchAdapter(
        iis_reader=None,
        warning_reader=None,
        iis_enabled=False,
        warning_enabled=False,
    )
    with pytest.raises(LogSearchError) as exc_info:
        await adapter.search_logs(LogSearchCriteriaDTO(query_text="test"))
    assert exc_info.value.error_code == "LOG_SEARCH_BACKEND_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_matrix_a_iis_disabled_reader_absent_warning_valid() -> None:
    """A: Verify IIS disabled without reader does not fail search when warning is valid."""
    t0 = datetime(2026, 8, 25, 10, 0, 0, tzinfo=UTC)
    warn_client = MockLogSearchClient([_make_record("warn-1", t0, service_name="superoffice_cs")])
    adapter = CompositeLogSearchAdapter(
        iis_reader=None,
        warning_reader=warn_client,
        iis_enabled=False,
        warning_enabled=True,
    )
    res = await adapter.search_logs(LogSearchCriteriaDTO(query_text="test"))
    assert res.returned_count == 1
    assert res.items[0].log_id == "warn-1"


@pytest.mark.asyncio
async def test_matrix_b_iis_enabled_reader_absent_fails_closed() -> None:
    """B: Verify IIS enabled without reader FAILS CLOSED (IIS_LOG_BACKEND_NOT_CONFIGURED)."""
    adapter = CompositeLogSearchAdapter(
        iis_reader=None,
        warning_reader=None,
        iis_enabled=True,
        warning_enabled=False,
    )
    with pytest.raises(LogSearchError) as exc_info:
        await adapter.search_logs(LogSearchCriteriaDTO(query_text="test"))
    assert exc_info.value.error_code == "IIS_LOG_BACKEND_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_matrix_c_warning_disabled_reader_absent_iis_valid() -> None:
    """C: Verify warning disabled without reader does not fail search when IIS is valid."""
    t0 = datetime(2026, 8, 25, 10, 0, 0, tzinfo=UTC)
    iis_client = MockLogSearchClient([_make_record("iis-1", t0, service_name="superoffice_iis")])
    adapter = CompositeLogSearchAdapter(
        iis_reader=iis_client,
        warning_reader=None,
        iis_enabled=True,
        warning_enabled=False,
    )
    res = await adapter.search_logs(LogSearchCriteriaDTO(query_text="test"))
    assert res.returned_count == 1
    assert res.items[0].log_id == "iis-1"


@pytest.mark.asyncio
async def test_matrix_d_warning_enabled_reader_absent_fails_closed() -> None:
    """D: Verify warning enabled without reader FAILS CLOSED."""
    adapter = CompositeLogSearchAdapter(
        iis_reader=None,
        warning_reader=None,
        iis_enabled=False,
        warning_enabled=True,
    )
    with pytest.raises(LogSearchError) as exc_info:
        await adapter.search_logs(LogSearchCriteriaDTO(query_text="test"))
    assert exc_info.value.error_code == "APPLICATION_LOG_BACKEND_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_matrix_e_both_enabled_iis_valid_warning_missing_fails_safe() -> None:
    """E: Verify when both enabled, valid IIS does NOT silently succeed if warning is missing."""
    t0 = datetime(2026, 8, 25, 10, 0, 0, tzinfo=UTC)
    iis_client = MockLogSearchClient([_make_record("iis-1", t0, service_name="superoffice_iis")])
    adapter = CompositeLogSearchAdapter(
        iis_reader=iis_client,
        warning_reader=None,  # Warning enabled but reader missing
        iis_enabled=True,
        warning_enabled=True,
    )
    # MUST FAIL SAFE, NOT return partial IIS results
    with pytest.raises(LogSearchError) as exc_info:
        await adapter.search_logs(LogSearchCriteriaDTO(query_text="test"))
    assert exc_info.value.error_code == "APPLICATION_LOG_BACKEND_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_matrix_f_both_enabled_warning_valid_iis_missing_fails_safe() -> None:
    """F: Verify when both enabled, valid warning does NOT silently succeed if IIS is missing."""
    t0 = datetime(2026, 8, 25, 10, 0, 0, tzinfo=UTC)
    warn_client = MockLogSearchClient([_make_record("warn-1", t0, service_name="superoffice_cs")])
    adapter = CompositeLogSearchAdapter(
        iis_reader=None,  # IIS enabled but reader missing
        warning_reader=warn_client,
        iis_enabled=True,
        warning_enabled=True,
    )
    # MUST FAIL SAFE, NOT return partial warning results
    with pytest.raises(LogSearchError) as exc_info:
        await adapter.search_logs(LogSearchCriteriaDTO(query_text="test"))
    assert exc_info.value.error_code == "IIS_LOG_BACKEND_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_matrix_g_one_enabled_valid_other_explicitly_disabled() -> None:
    """G: Verify one enabled valid + other explicitly disabled succeeds normally."""
    t0 = datetime(2026, 8, 25, 10, 0, 0, tzinfo=UTC)
    iis_client = MockLogSearchClient([_make_record("iis-1", t0, service_name="superoffice_iis")])
    warn_client = MockLogSearchClient([_make_record("warn-1", t0, service_name="superoffice_cs")])

    # IIS only
    adapter_iis = CompositeLogSearchAdapter(
        iis_reader=iis_client,
        warning_reader=warn_client,
        iis_enabled=True,
        warning_enabled=False,
    )
    res_iis = await adapter_iis.search_logs(LogSearchCriteriaDTO())
    assert res_iis.returned_count == 1
    assert res_iis.items[0].log_id == "iis-1"

    # Warning only
    adapter_warn = CompositeLogSearchAdapter(
        iis_reader=iis_client,
        warning_reader=warn_client,
        iis_enabled=False,
        warning_enabled=True,
    )
    res_warn = await adapter_warn.search_logs(LogSearchCriteriaDTO())
    assert res_warn.returned_count == 1
    assert res_warn.items[0].log_id == "warn-1"


# ============================================================================
# Section 14: Factory Intent Preservation Tests
# ============================================================================


def test_factory_intent_preservation_when_readers_fail_to_construct() -> None:
    """Verify create_composite_log_adapter preserves admin intent even if readers fail (Sec 14)."""
    settings = DiagnosticsServerSettings(
        iis_log_enabled=True,
        application_log_enabled=True,
    )
    # Mock reader constructors raising exceptions during factory startup
    with (
        patch(
            "diag_mcp.adapters.factory.create_iis_log_reader",
            side_effect=RuntimeError("Disk inaccessible"),
        ),
        patch(
            "diag_mcp.adapters.factory.create_warning_log_reader",
            side_effect=RuntimeError("DB engine unavailable"),
        ),
    ):
        adapter = create_composite_log_adapter(settings)

    # Factory must preserve intent flags rather than resetting them to False
    assert adapter.iis_enabled is True
    assert adapter.warning_enabled is True
    assert adapter.has_enabled_sources is True


@pytest.mark.asyncio
async def test_factory_created_adapter_fails_closed_when_reader_init_failed() -> None:
    """Verify adapter created with failing reader init fails closed on search (Sec 14)."""
    settings = DiagnosticsServerSettings(
        iis_log_enabled=True,
        application_log_enabled=False,
    )
    with patch(
        "diag_mcp.adapters.factory.create_iis_log_reader",
        side_effect=RuntimeError("Initialization failed"),
    ):
        adapter = create_composite_log_adapter(settings)

    with pytest.raises(LogSearchError) as exc_info:
        await adapter.search_logs(LogSearchCriteriaDTO(query_text="health"))
    assert exc_info.value.error_code == "IIS_LOG_BACKEND_NOT_CONFIGURED"


# ============================================================================
# Existing Composite Behavior Tests (Merge, Truncation, Limits, Deduplication)
# ============================================================================


@pytest.mark.asyncio
async def test_both_sources_enabled_and_succeed() -> None:
    """Verify records from both sources are merged and returned (Section 39)."""
    t0 = datetime(2026, 8, 25, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 8, 25, 10, 5, 0, tzinfo=UTC)
    iis_client = MockLogSearchClient([_make_record("iis-1", t0, service_name="superoffice_iis")])
    warn_client = MockLogSearchClient([_make_record("warn-1", t1, service_name="superoffice_cs")])

    adapter = CompositeLogSearchAdapter(
        iis_reader=iis_client,
        warning_reader=warn_client,
        iis_enabled=True,
        warning_enabled=True,
    )
    res = await adapter.search_logs(LogSearchCriteriaDTO(query_text="test"))
    assert res.returned_count == 2
    # Newest first: warn-1 (10:05) then iis-1 (10:00)
    assert res.items[0].log_id == "warn-1"
    assert res.items[1].log_id == "iis-1"


@pytest.mark.asyncio
async def test_enabled_source_failure_fails_whole_operation() -> None:
    """Verify runtime failure of an enabled source fails safe without partial success (Sec 47)."""
    t0 = datetime(2026, 8, 25, 10, 0, 0, tzinfo=UTC)
    iis_client = MockLogSearchClient([_make_record("iis-1", t0)])
    warn_client = MockLogSearchClient(
        should_fail=True,
        failure_error_code="APPLICATION_LOG_READ_FAILED",
    )

    adapter = CompositeLogSearchAdapter(
        iis_reader=iis_client,
        warning_reader=warn_client,
        iis_enabled=True,
        warning_enabled=True,
    )
    with pytest.raises(LogSearchError) as exc_info:
        await adapter.search_logs(LogSearchCriteriaDTO(query_text="test"))
    assert exc_info.value.error_code == "APPLICATION_LOG_READ_FAILED"


@pytest.mark.asyncio
async def test_merge_ordering_newest_first() -> None:
    """Verify deterministic merge ordering: timestamp DESC, tie-breaker: service, id (Sec 44)."""
    base = datetime(2026, 8, 25, 10, 0, 0, tzinfo=UTC)
    iis_client = MockLogSearchClient(
        [
            _make_record("iis-1", base, service_name="superoffice_iis"),
            _make_record("iis-2", base + timedelta(minutes=10), service_name="superoffice_iis"),
        ]
    )
    warn_client = MockLogSearchClient(
        [
            _make_record("warn-1", base + timedelta(minutes=5), service_name="superoffice_cs"),
            _make_record("warn-2", base + timedelta(minutes=15), service_name="superoffice_cs"),
        ]
    )

    adapter = CompositeLogSearchAdapter(
        iis_reader=iis_client,
        warning_reader=warn_client,
        iis_enabled=True,
        warning_enabled=True,
    )
    res = await adapter.search_logs(LogSearchCriteriaDTO(query_text="test"))
    assert res.returned_count == 4
    # Expected ordering: 10:15 (warn-2), 10:10 (iis-2), 10:05 (warn-1), 10:00 (iis-1)
    assert [r.log_id for r in res.items] == ["warn-2", "iis-2", "warn-1", "iis-1"]


@pytest.mark.asyncio
async def test_truncation_when_source_is_truncated() -> None:
    """Verify truncation propagation and total_matched=None when a source is truncated (Sec 45)."""
    t0 = datetime(2026, 8, 25, 10, 0, 0, tzinfo=UTC)
    iis_client = MockLogSearchClient(
        [_make_record("iis-1", t0)],
        is_truncated=False,
        total_matched=1,
    )
    warn_client = MockLogSearchClient(
        [_make_record("warn-1", t0)],
        is_truncated=True,
        total_matched=None,
    )

    adapter = CompositeLogSearchAdapter(
        iis_reader=iis_client,
        warning_reader=warn_client,
        iis_enabled=True,
        warning_enabled=True,
    )
    res = await adapter.search_logs(LogSearchCriteriaDTO(query_text="test"))
    assert res.returned_count == 2
    assert res.is_truncated is True
    assert res.total_matched is None


@pytest.mark.asyncio
async def test_truncation_and_total_matched_on_limit_slicing() -> None:
    """Verify total_matched is preserved when slicing occurs without source truncation (Sec 45)."""
    base = datetime(2026, 8, 25, 10, 0, 0, tzinfo=UTC)
    iis_records = [_make_record(f"iis-{i}", base + timedelta(seconds=i)) for i in range(3)]
    warn_records = [_make_record(f"warn-{i}", base + timedelta(seconds=i + 20)) for i in range(3)]

    iis_client = MockLogSearchClient(iis_records, is_truncated=False, total_matched=3)
    warn_client = MockLogSearchClient(warn_records, is_truncated=False, total_matched=3)

    adapter = CompositeLogSearchAdapter(
        iis_reader=iis_client,
        warning_reader=warn_client,
        iis_enabled=True,
        warning_enabled=True,
    )
    res = await adapter.search_logs(LogSearchCriteriaDTO(limit=4))
    assert res.returned_count == 4
    assert res.is_truncated is True
    assert res.total_matched == 6


@pytest.mark.asyncio
async def test_duplicate_log_id_deduplicated_safely() -> None:
    """Verify duplicate log_id across sources is safely deduplicated (Section 39)."""
    t0 = datetime(2026, 8, 25, 10, 0, 0, tzinfo=UTC)
    iis_client = MockLogSearchClient([_make_record("dup-1", t0, service_name="iis")])
    warn_client = MockLogSearchClient([_make_record("dup-1", t0, service_name="warn")])

    adapter = CompositeLogSearchAdapter(
        iis_reader=iis_client,
        warning_reader=warn_client,
        iis_enabled=True,
        warning_enabled=True,
    )
    res = await adapter.search_logs(LogSearchCriteriaDTO())
    assert res.returned_count == 1
    assert res.items[0].log_id == "dup-1"
