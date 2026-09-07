"""Unit tests for SuperOfficeWarningLogParser (Gate 7A.4B2)."""

from datetime import datetime

from diag_mcp.adapters.warning_log_parser import (
    ParsedWarningEvent,
    SuperOfficeWarningLogParser,
)


def test_single_line_warning_event() -> None:
    """Verify deterministic parsing of a single-line warning event."""
    parser = SuperOfficeWarningLogParser()
    line = (
        "[1001] [(System)            ] [soap.exe    ] 2026-08-25 09:08:22.123 [5.702] [10.108]: "
        "ConversionHelper::analyzeNSException: Authentication failed."
    )
    res = parser.feed_line(line)
    assert res is None  # Event is active, waiting for next header or EOF

    event = parser.end_of_file()
    assert event is not None
    assert isinstance(event, ParsedWarningEvent)
    assert event.numeric_id == 1001
    assert event.context == "System"
    assert event.process_name == "soap.exe"
    assert event.local_timestamp == datetime(2026, 8, 25, 9, 8, 22, 123000)
    assert event.metric_1 == 5.702
    assert event.metric_2 == 10.108
    assert event.header_message == "ConversionHelper::analyzeNSException: Authentication failed."
    assert event.component == "ConversionHelper"
    assert event.method == "analyzeNSException"
    assert event.continuation_lines == ()
    assert event.physical_line_count == 1
    assert event.is_truncated is False
    assert "Authentication failed." in event.full_message


def test_decimal_metrics_mandatory_regression() -> None:
    """Verify metric values [5.702] [10.108] parse successfully (Gate 7A.4B2 Section 28)."""
    parser = SuperOfficeWarningLogParser()
    line = (
        "[42] [(CRM) ] [app.exe ] 2026-08-25 10:00:00.500 [5.702] [10.108]: "
        "Operation completed with warnings"
    )
    parser.feed_line(line)
    event = parser.end_of_file()
    assert event is not None
    assert event.metric_1 == 5.702
    assert event.metric_2 == 10.108


def test_integer_metrics() -> None:
    """Verify integer metric values [0] [1] parse successfully."""
    parser = SuperOfficeWarningLogParser()
    line = (
        "[10] [() ] [smtp.exe ] 2026-08-25 10:00:00.000 [0] [1]: Outbox::sendMails: Outbox is empty"
    )
    parser.feed_line(line)
    event = parser.end_of_file()
    assert event is not None
    assert event.metric_1 == 0.0
    assert event.metric_2 == 1.0
    assert event.context == ""
    assert event.process_name == "smtp.exe"
    assert event.component == "Outbox"
    assert event.method == "sendMails"


def test_multiline_event_assembly() -> None:
    """Verify multi-line event assembly and non-leakage across consecutive events (Section 30)."""
    parser = SuperOfficeWarningLogParser()
    lines = [
        (
            "[100] [(System) ] [soap.exe ] 2026-08-25 09:08:22.123 [1.0] [2.0]: "
            "ConversionHelper::analyzeNSException: Header error"
        ),
        "Continuation line 1: stack frame or inner detail",
        "Continuation line 2: final reason",
        ("[200] [(CRM) ] [worker.exe ] 2026-08-25 09:09:00.000 [0.5] [1.5]: Worker task completed"),
    ]

    event1 = parser.feed_line(lines[0])
    assert event1 is None

    assert parser.feed_line(lines[1]) is None
    assert parser.feed_line(lines[2]) is None

    # Line 3 is the header of event 2 -> triggers completion and emission of event 1
    event1 = parser.feed_line(lines[3])
    assert event1 is not None
    assert event1.numeric_id == 100
    assert event1.physical_line_count == 3
    assert len(event1.continuation_lines) == 2
    assert event1.continuation_lines[0] == "Continuation line 1: stack frame or inner detail"
    assert event1.continuation_lines[1] == "Continuation line 2: final reason"
    assert event1.is_truncated is False

    # EOF emits event 2
    event2 = parser.end_of_file()
    assert event2 is not None
    assert event2.numeric_id == 200
    assert event2.physical_line_count == 1
    assert len(event2.continuation_lines) == 0


def test_eof_event_emission() -> None:
    """Verify EOF correctly emits active in-progress event (Section 31)."""
    parser = SuperOfficeWarningLogParser()
    parser.feed_line(
        "[50] [(Batch) ] [cron.exe ] 2026-08-25 12:00:00.000 [0.0] [0.0]: Batch started"
    )
    parser.feed_line("Detail line 1")
    event = parser.end_of_file()
    assert event is not None
    assert event.numeric_id == 50
    assert event.physical_line_count == 2
    assert event.continuation_lines == ("Detail line 1",)

    # Subsequent EOF returns None
    assert parser.end_of_file() is None


def test_orphan_continuation_safety() -> None:
    """Verify orphan lines before first valid header are ignored fail-safe (Section 32)."""
    parser = SuperOfficeWarningLogParser()
    assert parser.feed_line("Orphan line without header 1") is None
    assert parser.feed_line("Orphan line without header 2") is None
    assert parser.orphan_lines_skipped == 2

    # Valid header arrives
    assert (
        parser.feed_line("[1] [(sys) ] [p.exe ] 2026-08-25 12:00:00.000 [0] [0]: Valid message")
        is None
    )

    event = parser.end_of_file()
    assert event is not None
    assert event.numeric_id == 1
    assert event.physical_line_count == 1
    assert event.continuation_lines == ()


def test_blank_lines_handling() -> None:
    """Verify leading blanks ignored, internal blanks preserved, and consecutive collapsed."""
    parser = SuperOfficeWarningLogParser()
    assert parser.feed_line("") is None
    assert parser.feed_line("   ") is None
    # whitespace lines before header do not count as orphans
    assert parser.orphan_lines_skipped == 0

    parser.feed_line("[10] [(sys) ] [p.exe ] 2026-08-25 12:00:00.000 [0] [0]: Header message")
    parser.feed_line("Line 1")
    parser.feed_line("")  # blank 1: preserved
    parser.feed_line("   ")  # blank 2: collapsed (ignored)
    parser.feed_line("Line 2")

    event = parser.end_of_file()
    assert event is not None
    assert event.continuation_lines == ("Line 1", "", "Line 2")
    assert event.physical_line_count == 4


def test_malformed_header_like_line_handling() -> None:
    """Verify malformed header-like line closes active event without fabricating event."""
    parser = SuperOfficeWarningLogParser()
    parser.feed_line("[1] [(sys) ] [proc.exe ] 2026-08-25 12:00:00.000 [0] [0]: First event")
    parser.feed_line("Event 1 continuation")

    # Malformed line: starts with [123] [( but has corrupt timestamp/format
    malformed_line = "[123] [(invalid) ] [proc] not_a_timestamp [1] [2]: bad"
    assert parser.looks_like_header_prefix(malformed_line) is True

    # Feeding malformed line terminates active event 1
    event1 = parser.feed_line(malformed_line)
    assert event1 is not None
    assert event1.numeric_id == 1
    assert event1.continuation_lines == ("Event 1 continuation",)
    assert parser.malformed_headers_skipped == 1

    # End of file does NOT emit a fabricated event for the malformed line
    assert parser.end_of_file() is None


def test_neutral_naming_invariance() -> None:
    """Verify internal DTO uses neutral numeric_id and does NOT expose thread_id."""
    parser = SuperOfficeWarningLogParser()
    parser.feed_line("[999] [(ctx) ] [proc.exe ] 2026-08-25 12:00:00.000 [1] [2]: Msg")
    event = parser.end_of_file()
    assert event is not None
    assert hasattr(event, "numeric_id")
    assert not hasattr(event, "thread_id")
    assert event.numeric_id == 999


def test_max_lines_truncation_bound() -> None:
    """Verify event is truncated when exceeding max physical lines (canonical: 50)."""
    max_lines = 10
    parser = SuperOfficeWarningLogParser(max_event_lines=max_lines)
    parser.feed_line("[1] [(ctx) ] [proc.exe ] 2026-08-25 12:00:00.000 [0] [0]: Header")
    for i in range(1, 20):
        parser.feed_line(f"Continuation line {i}")

    event = parser.end_of_file()
    assert event is not None
    assert event.physical_line_count == max_lines
    assert len(event.continuation_lines) == max_lines - 1  # 9 continuations + 1 header = 10
    assert event.is_truncated is True


def test_max_bytes_truncation_bound() -> None:
    """Verify event is truncated when exceeding max bytes (canonical: 16 KiB)."""
    max_bytes = 200
    parser = SuperOfficeWarningLogParser(max_event_bytes=max_bytes)
    parser.feed_line("[1] [(ctx) ] [proc.exe ] 2026-08-25 12:00:00.000 [0] [0]: Header")
    # Feed 100-byte strings
    parser.feed_line("A" * 100)
    parser.feed_line("B" * 150)  # Should exceed 200 bytes

    event = parser.end_of_file()
    assert event is not None
    assert event.is_truncated is True
    assert event.total_bytes <= max_bytes + 100  # Stopped accumulating before exceeding buffer


def test_optional_component_method_absent() -> None:
    """Verify parser accepts header message without Component::Method prefix."""
    parser = SuperOfficeWarningLogParser()
    parser.feed_line(
        "[5] [(sys) ] [p.exe ] 2026-08-25 12:00:00.000 [0] [0]: Just a simple warning text"
    )
    event = parser.end_of_file()
    assert event is not None
    assert event.component is None
    assert event.method is None
    assert event.header_message == "Just a simple warning text"
