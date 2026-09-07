"""Unit tests for SuperOfficeWarningLogReader (Gate 7A.4B2 / 7A.4B2-R1 / 7A.4B2-R2)."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from diag_mcp.adapters.warning_log_parser import ParsedWarningEvent
from diag_mcp.adapters.warning_log_reader import (
    SERVICE_NAME,
    LocalTimestampClassification,
    SuperOfficeWarningLogReader,
    classify_local_timestamp,
)
from diag_mcp.contracts.dtos import LogSearchCriteriaDTO
from diag_mcp.contracts.errors import LogSearchError


@pytest.fixture
def sample_warning_file(tmp_path: Path) -> Path:
    """Create a synthetic warning log file with single and multiline events."""
    log_file = tmp_path / "warning.2026-08-25"
    content = (
        "[101] [(System) ] [soap.exe ] 2026-08-25 09:00:00.000 [1.5] [2.5]: "
        "ConversionHelper::analyzeNSException: Authentication failed.\n"
        "Details: User token expired\n"
        "Reason: No credential record matched\n"
        "[102] [() ] [smtp.exe ] 2026-08-25 09:30:00.000 [0.0] [1.0]: "
        "Outbox::sendMails: Connection refused\n"
        "[103] [(Batch) ] [task.exe ] 2026-08-25 10:00:00.000 [5.702] [10.108]: "
        "Task completed with non-fatal warnings\n"
    )
    log_file.write_text(content, encoding="utf-8")
    return log_file


def _make_parsed_event(local_ts: datetime, numeric_id: int = 1) -> ParsedWarningEvent:
    """Helper to create a synthetic ParsedWarningEvent with arbitrary timestamp."""
    return ParsedWarningEvent(
        numeric_id=numeric_id,
        context="System",
        process_name="test.exe",
        local_timestamp=local_ts,
        metric_1=0.0,
        metric_2=0.0,
        header_message="Test message",
        continuation_lines=(),
        physical_line_count=1,
        total_bytes=50,
        is_truncated=False,
    )


def test_parser_remains_timezone_neutral(sample_warning_file: Path) -> None:
    """Verify parsed event timestamp remains naive wall-clock datetime (Gate 7A.4B2-R1 Item A)."""
    reader = SuperOfficeWarningLogReader(log_dir=sample_warning_file.parent)
    events = reader.read_events_from_file(sample_warning_file)

    assert len(events) == 3
    assert events[0].local_timestamp.tzinfo is None
    assert events[0].local_timestamp == datetime(2026, 8, 25, 9, 0, 0)


def test_missing_timezone_fails_closed(sample_warning_file: Path) -> None:
    """Verify normalization fails closed if timezone is not configured (Item B)."""
    reader = SuperOfficeWarningLogReader(
        log_dir=sample_warning_file.parent,
        enabled=True,
        application_log_timezone=None,
    )
    events = reader.read_events_from_file(sample_warning_file)

    with pytest.raises(LogSearchError) as exc_info:
        reader.to_domain_dto(events[0])
    assert exc_info.value.error_code == "APPLICATION_LOG_TIMEZONE_NOT_CONFIGURED"

    with pytest.raises(LogSearchError) as exc_search:
        asyncio.run(reader.search_logs(LogSearchCriteriaDTO()))
    assert exc_search.value.error_code == "APPLICATION_LOG_TIMEZONE_NOT_CONFIGURED"


def test_invalid_timezone_fails_closed(sample_warning_file: Path) -> None:
    """Verify invalid timezone name fails closed with APPLICATION_LOG_TIMEZONE_INVALID (Item E)."""
    reader = SuperOfficeWarningLogReader(
        log_dir=sample_warning_file.parent,
        enabled=True,
        application_log_timezone="Invalid/NonExistent_Zone",
    )
    events = reader.read_events_from_file(sample_warning_file)

    with pytest.raises(LogSearchError) as exc_info:
        reader.to_domain_dto(events[0])
    assert exc_info.value.error_code == "APPLICATION_LOG_TIMEZONE_INVALID"


def test_explicit_utc_normalization(sample_warning_file: Path) -> None:
    """Verify explicit UTC produces aware UTC timestamp matching wall-clock (Item C)."""
    reader = SuperOfficeWarningLogReader(
        log_dir=sample_warning_file.parent,
        enabled=True,
        application_log_timezone="UTC",
    )
    events = reader.read_events_from_file(sample_warning_file)
    dto = reader.to_domain_dto(events[0])

    assert dto.timestamp.tzinfo == UTC
    assert dto.timestamp == datetime(2026, 8, 25, 9, 0, 0, tzinfo=UTC)


def test_non_utc_timezone_conversion(sample_warning_file: Path) -> None:
    """Verify non-UTC timezone converts wall-clock to actual UTC, not relabeling (Item D)."""
    reader = SuperOfficeWarningLogReader(
        log_dir=sample_warning_file.parent,
        enabled=True,
        application_log_timezone="Asia/Karachi",
    )
    events = reader.read_events_from_file(sample_warning_file)
    dto = reader.to_domain_dto(events[0])

    assert dto.timestamp.tzinfo == UTC
    assert dto.timestamp == datetime(2026, 8, 25, 4, 0, 0, tzinfo=UTC)
    assert dto.timestamp.hour == 4


def test_no_direct_utc_replace_regression() -> None:
    """Verify warning_log_reader.py does not contain naive .replace(tzinfo=UTC) (Item F)."""
    reader_file = Path("src/servers/diagnostics/src/diag_mcp/adapters/warning_log_reader.py")
    content = reader_file.read_text(encoding="utf-8")
    assert ".replace(tzinfo=UTC)" not in content


# ============================================================================
# Gate 7A.4B2-R2: DST Safety and Round-Trip Validation Tests
# ============================================================================


def test_dst_normal_timestamp_stockholm() -> None:
    """Verify ordinary local time in a DST-observing zone normalizes correctly (Section 10.A)."""
    tz = ZoneInfo("Europe/Stockholm")
    reader = SuperOfficeWarningLogReader(
        application_log_timezone="Europe/Stockholm",
        enabled=True,
    )
    # Summer time: Europe/Stockholm is UTC+2 (CEST)
    summer_dt = datetime(2026, 8, 25, 9, 0, 0)
    classification, utc_dt = classify_local_timestamp(summer_dt, tz)
    assert classification == LocalTimestampClassification.VALID
    assert utc_dt == datetime(2026, 8, 25, 7, 0, 0, tzinfo=UTC)

    dto = reader.to_domain_dto(_make_parsed_event(summer_dt))
    assert dto.timestamp == datetime(2026, 8, 25, 7, 0, 0, tzinfo=UTC)


def test_dst_fallback_ambiguous_timestamp_fails_safe() -> None:
    """Verify fall-back ambiguous local time raises APPLICATION_LOG_TIMESTAMP_AMBIGUOUS (10.B)."""
    tz = ZoneInfo("Europe/Stockholm")
    reader = SuperOfficeWarningLogReader(
        application_log_timezone="Europe/Stockholm",
        enabled=True,
    )
    # On Sunday, 2026-10-25 at 03:00 CEST clocks are turned back to 02:00 CET.
    # 02:30:00 occurs twice: fold=0 is 00:30 UTC, fold=1 is 01:30 UTC.
    ambiguous_dt = datetime(2026, 10, 25, 2, 30, 0)

    # Prove fold=0 != fold=1
    cand0 = ambiguous_dt.replace(tzinfo=tz, fold=0).astimezone(UTC)
    cand1 = ambiguous_dt.replace(tzinfo=tz, fold=1).astimezone(UTC)
    assert cand0 != cand1
    assert cand0 == datetime(2026, 10, 25, 0, 30, 0, tzinfo=UTC)
    assert cand1 == datetime(2026, 10, 25, 1, 30, 0, tzinfo=UTC)

    # Prove classifier detects ambiguity
    classification, utc_dt = classify_local_timestamp(ambiguous_dt, tz)
    assert classification == LocalTimestampClassification.AMBIGUOUS
    assert utc_dt is None

    # Normalization must fail safe without arbitrarily selecting fold=0 or fold=1
    with pytest.raises(LogSearchError) as exc_info:
        reader.to_domain_dto(_make_parsed_event(ambiguous_dt))
    assert exc_info.value.error_code == "APPLICATION_LOG_TIMESTAMP_AMBIGUOUS"


def test_dst_spring_forward_nonexistent_timestamp_fails_safe() -> None:
    """Verify spring-forward gap local time raises APPLICATION_LOG_TIMESTAMP_NONEXISTENT (10.C)."""
    tz = ZoneInfo("Europe/Stockholm")
    reader = SuperOfficeWarningLogReader(
        application_log_timezone="Europe/Stockholm",
        enabled=True,
    )
    # On Sunday, 2026-03-29 at 02:00 CET clocks jump forward to 03:00 CEST.
    # 02:30:00 never existed in local time.
    gap_dt = datetime(2026, 3, 29, 2, 30, 0)

    # Prove neither candidate validly round-trips to the gap time
    back0 = gap_dt.replace(tzinfo=tz, fold=0).astimezone(UTC).astimezone(tz).replace(tzinfo=None)
    back1 = gap_dt.replace(tzinfo=tz, fold=1).astimezone(UTC).astimezone(tz).replace(tzinfo=None)
    assert back0 != gap_dt
    assert back1 != gap_dt

    # Prove classifier detects nonexistence
    classification, utc_dt = classify_local_timestamp(gap_dt, tz)
    assert classification == LocalTimestampClassification.NONEXISTENT
    assert utc_dt is None

    # Normalization must fail safe
    with pytest.raises(LogSearchError) as exc_info:
        reader.to_domain_dto(_make_parsed_event(gap_dt))
    assert exc_info.value.error_code == "APPLICATION_LOG_TIMESTAMP_NONEXISTENT"


def test_round_trip_validation_semantics() -> None:
    """Verify implementation validates via round-trip, not naive utcoffset() (Section 11)."""
    tz = ZoneInfo("Europe/Stockholm")
    gap_dt = datetime(2026, 3, 29, 2, 30, 0)

    # Naive ZoneInfo.utcoffset() returns a non-None offset even for a nonexistent time!
    naive_attached = gap_dt.replace(tzinfo=tz)
    # Demonstrating utcoffset() alone is insufficient!
    assert naive_attached.utcoffset() is not None

    # Our classifier detects the nonexistence via deterministic round-trip validation
    classification, _ = classify_local_timestamp(gap_dt, tz)
    assert classification == LocalTimestampClassification.NONEXISTENT


def test_no_automatic_fold_choice_policy() -> None:
    """Verify source code does not automatically select fold=0 without validation (Section 12)."""
    reader_file = Path("src/servers/diagnostics/src/diag_mcp/adapters/warning_log_reader.py")
    content = reader_file.read_text(encoding="utf-8")
    # Must NOT have unconditional assignment: fold=0 followed by immediate return
    assert "return aware_dt.astimezone(UTC)" not in content
    # classify_local_timestamp must be invoked
    assert "classify_local_timestamp" in content


# ============================================================================
# Existing Reader Functionality Tests
# ============================================================================


def test_read_events_from_file_utf8_no_bom(sample_warning_file: Path) -> None:
    """Verify reading and parsing events from a standard UTF-8 log file."""
    reader = SuperOfficeWarningLogReader(log_dir=sample_warning_file.parent)
    events = reader.read_events_from_file(sample_warning_file)

    assert len(events) == 3
    assert events[0].numeric_id == 101
    assert events[0].process_name == "soap.exe"
    assert len(events[0].continuation_lines) == 2
    assert events[0].component == "ConversionHelper"
    assert events[0].method == "analyzeNSException"

    assert events[1].numeric_id == 102
    assert events[1].continuation_lines == ()

    assert events[2].numeric_id == 103
    assert events[2].metric_1 == 5.702
    assert events[2].metric_2 == 10.108


def test_read_events_from_file_utf8_bom(tmp_path: Path) -> None:
    """Verify reading file with UTF-8 BOM bytes (\xef\xbb\xbf)."""
    log_file = tmp_path / "warning.2026-08-26"
    raw_bytes = (
        b"\xef\xbb\xbf[201] [(sys) ] [p.exe ] 2026-08-26 08:00:00.000 [0] [0]: BOM test msg\n"
    )
    log_file.write_bytes(raw_bytes)

    reader = SuperOfficeWarningLogReader(log_dir=tmp_path)
    events = reader.read_events_from_file(log_file)
    assert len(events) == 1
    assert events[0].numeric_id == 201
    assert events[0].header_message == "BOM test msg"


def test_invalid_utf8_raises_encoding_error(tmp_path: Path) -> None:
    """Verify non-UTF-8 bytes raise APPLICATION_LOG_ENCODING_ERROR without guessing ANSI."""
    log_file = tmp_path / "warning.corrupt"
    log_file.write_bytes(b"[301] [(sys) ] [p.exe ] 2026-08-25 08:00:00.000 [0] [0]: \xff\xfe bad\n")

    reader = SuperOfficeWarningLogReader(log_dir=tmp_path)
    with pytest.raises(LogSearchError) as exc_info:
        reader.read_events_from_file(log_file)

    assert exc_info.value.error_code == "APPLICATION_LOG_ENCODING_ERROR"


def test_filename_date_not_used_as_event_date(tmp_path: Path) -> None:
    """Verify event timestamp is parsed from line, NOT derived from filename (Section 12)."""
    log_file = tmp_path / "warning.2026-09-06"
    content = "[99] [(sys) ] [p.exe ] 2026-09-05 23:59:59.999 [0] [0]: Previous day event\n"
    log_file.write_text(content, encoding="utf-8")

    reader = SuperOfficeWarningLogReader(log_dir=tmp_path)
    events = reader.read_events_from_file(log_file)
    assert len(events) == 1
    assert events[0].local_timestamp == datetime(2026, 9, 5, 23, 59, 59, 999000)
    assert events[0].local_timestamp.day == 5


def test_source_derived_severity_warn(sample_warning_file: Path) -> None:
    """Verify severity is derived from source (WARN), not inferred from message (Section 35)."""
    reader = SuperOfficeWarningLogReader(
        log_dir=sample_warning_file.parent,
        application_log_timezone="UTC",
    )
    events = reader.read_events_from_file(sample_warning_file)

    dto = reader.to_domain_dto(events[0])
    assert dto.severity == "WARN"
    assert dto.service_name == SERVICE_NAME


def test_raw_context_neutral_keys(sample_warning_file: Path) -> None:
    """Verify raw_context exposes numeric_id and does NOT contain thread_id (Section 29)."""
    reader = SuperOfficeWarningLogReader(
        log_dir=sample_warning_file.parent,
        application_log_timezone="UTC",
    )
    events = reader.read_events_from_file(sample_warning_file)

    dto = reader.to_domain_dto(events[0])
    assert "numeric_id" in dto.raw_context
    assert dto.raw_context["numeric_id"] == "101"
    assert "thread_id" not in dto.raw_context
    assert dto.raw_context["process_name"] == "soap.exe"
    assert dto.raw_context["component"] == "ConversionHelper"
    assert dto.raw_context["method"] == "analyzeNSException"


@pytest.mark.asyncio
async def test_search_logs_disabled_fails_closed(tmp_path: Path) -> None:
    """Verify search_logs raises APPLICATION_LOG_NOT_ENABLED when enabled=False."""
    reader = SuperOfficeWarningLogReader(
        log_dir=tmp_path,
        enabled=False,
    )
    criteria = LogSearchCriteriaDTO()

    with pytest.raises(LogSearchError) as exc_info:
        await reader.search_logs(criteria)

    assert exc_info.value.error_code == "APPLICATION_LOG_NOT_ENABLED"


@pytest.mark.asyncio
async def test_search_logs_time_window_filtering(sample_warning_file: Path) -> None:
    """Verify search_logs filters by start_time and end_time (UTC)."""
    reader = SuperOfficeWarningLogReader(
        log_dir=sample_warning_file.parent,
        enabled=True,
        application_log_timezone="UTC",
    )
    criteria = LogSearchCriteriaDTO(
        start_time=datetime(2026, 8, 25, 9, 15, 0, tzinfo=UTC),
        end_time=datetime(2026, 8, 25, 9, 45, 0, tzinfo=UTC),
    )
    res = await reader.search_logs(criteria)
    assert res.returned_count == 1
    assert res.items[0].timestamp == datetime(2026, 8, 25, 9, 30, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_search_logs_query_text_filtering(sample_warning_file: Path) -> None:
    """Verify search_logs filters by literal query_text across header fields (Section 23)."""
    reader = SuperOfficeWarningLogReader(
        log_dir=sample_warning_file.parent,
        enabled=True,
        application_log_timezone="UTC",
    )
    # Header message contains "Authentication failed" -> matches
    criteria = LogSearchCriteriaDTO(query_text="Authentication failed")
    res = await reader.search_logs(criteria)
    assert res.returned_count == 1
    assert "Authentication failed" in res.items[0].message

    criteria_none = LogSearchCriteriaDTO(query_text="NonExistentTermXYZ")
    res_none = await reader.search_logs(criteria_none)
    assert res_none.returned_count == 0


@pytest.mark.asyncio
async def test_warning_continuation_not_publicly_searchable(tmp_path: Path) -> None:
    """Verify tokens in continuation lines do NOT match public query (Gate 7A.4C Sec 23 & 41)."""
    log_file = tmp_path / "warning.2026-08-25"
    content = (
        "[101] [(System) ] [soap.exe ] 2026-08-25 09:00:00.000 [0.0] [0.0]: "
        "Component::method: Safe header message\n"
        "SECRET_CONTINUATION_TOKEN_123\n"
        "Stack trace: at Foo.Bar() in line 42\n"
    )
    log_file.write_text(content, encoding="utf-8")

    reader = SuperOfficeWarningLogReader(
        log_dir=tmp_path,
        enabled=True,
        application_log_timezone="UTC",
    )

    # 1. Querying token only present in continuation must return 0 matches
    res_secret = await reader.search_logs(
        LogSearchCriteriaDTO(query_text="SECRET_CONTINUATION_TOKEN_123")
    )
    assert res_secret.returned_count == 0

    # 2. Querying normal header message must match
    res_header = await reader.search_logs(LogSearchCriteriaDTO(query_text="Safe header"))
    assert res_header.returned_count == 1
    # Verify emitted message is minimized to header only (no continuation / stack trace)
    assert res_header.items[0].message == "Component::method: Safe header message"
    assert "SECRET_CONTINUATION_TOKEN_123" not in res_header.items[0].message


@pytest.mark.asyncio
async def test_search_logs_limit_bounding(sample_warning_file: Path) -> None:
    """Verify search_logs bounds results and flags is_truncated."""
    reader = SuperOfficeWarningLogReader(
        log_dir=sample_warning_file.parent,
        enabled=True,
        application_log_timezone="UTC",
    )
    criteria = LogSearchCriteriaDTO(limit=2)
    res = await reader.search_logs(criteria)
    assert res.returned_count == 2
    assert res.is_truncated is True


@pytest.mark.asyncio
async def test_search_logs_max_scan_bytes_bound(tmp_path: Path) -> None:
    """Verify reader stops reading when max_scan_bytes is reached."""
    log_file = tmp_path / "warning.2026-08-25"
    lines = [
        f"[{i}] [(sys) ] [p.exe ] 2026-08-25 10:00:00.000 [0] [0]: Message {i} with padding text"
        for i in range(1, 50)
    ]
    log_file.write_text("\n".join(lines), encoding="utf-8")

    reader = SuperOfficeWarningLogReader(
        log_dir=tmp_path,
        enabled=True,
        max_scan_bytes=200,
        application_log_timezone="UTC",
    )
    res = await reader.search_logs(LogSearchCriteriaDTO(limit=50))
    assert res.is_truncated is True
    assert res.returned_count < 50


@pytest.mark.asyncio
async def test_search_logs_timeout_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify reader enforces scan_timeout_seconds bound and marks is_truncated."""
    log_file = tmp_path / "warning.2026-08-25"
    lines = [
        f"[{i}] [(sys) ] [p.exe ] 2026-08-25 10:00:00.000 [0] [0]: Message {i}"
        for i in range(1, 20)
    ]
    log_file.write_text("\n".join(lines), encoding="utf-8")

    reader = SuperOfficeWarningLogReader(
        log_dir=tmp_path,
        enabled=True,
        scan_timeout_seconds=1.0,
        application_log_timezone="UTC",
    )
    call_count = 0

    def mock_monotonic() -> float:
        nonlocal call_count
        call_count += 1
        return 0.0 if call_count == 1 else 5.0

    monkeypatch.setattr("diag_mcp.adapters.warning_log_reader.time.monotonic", mock_monotonic)

    res = await reader.search_logs(LogSearchCriteriaDTO(limit=50))
    assert res.is_truncated is True
