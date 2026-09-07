"""SuperOffice warning log event parser (Gate 7A.4B2).

Implements deterministic physical header parsing, multiline continuation assembly,
hard bounds enforcement (lines, bytes), and fail-safe orphan handling for the
SuperOffice warning-log stream.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

# ============================================================================
# Confirmed Physical Header Grammar (Gates 7A.4B2A / 7A.4B2A-R1)
# [<NUMERIC_ID>] [(<CONTEXT>)] [<PROCESS>] YYYY-MM-DD HH:mm:ss.fff
# [<METRIC_1>] [<METRIC_2>]: <MESSAGE>
# Metrics support integer and decimal values (e.g. [5.702] [10.108] or [0] [1]).
# ============================================================================
HEADER_PATTERN = re.compile(
    r"^\[(?P<numeric_id>\d+)\]"
    r"\s+"
    r"\[\((?P<context>[^)]*)\)\s*\]"
    r"\s+"
    r"\[(?P<process>[^\]]+?)\s*\]"
    r"\s+"
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3})"
    r"\s+"
    r"\[(?P<metric_1>\d+(?:\.\d+)?)\]"
    r"\s+"
    r"\[(?P<metric_2>\d+(?:\.\d+)?)\]"
    r":\s*"
    r"(?P<message>.*)$"
)

# Prefix pattern to detect lines that look like a header start
HEADER_PREFIX_PATTERN = re.compile(r"^\[\d+\]\s+\[\(")

# Optional Component::Method extractor from header message
COMPONENT_METHOD_PATTERN = re.compile(r"^([A-Za-z0-9_]+)::([A-Za-z0-9_]+):\s*(.*)$")

DEFAULT_MAX_EVENT_LINES = 50
DEFAULT_MAX_EVENT_BYTES = 16 * 1024  # 16 KiB


@dataclass(frozen=True, slots=True)
class ParsedWarningEvent:
    """Internal immutable representation of a parsed SuperOffice warning log event.

    Stores raw physical attributes and structural fields. Note that local_timestamp
    is a naive datetime as extracted from the physical log line (no timezone embedded
    in log).
    """

    numeric_id: int
    context: str
    process_name: str
    local_timestamp: datetime
    metric_1: float
    metric_2: float
    header_message: str
    continuation_lines: tuple[str, ...]
    physical_line_count: int
    total_bytes: int
    is_truncated: bool
    component: str | None = None
    method: str | None = None

    @property
    def full_message(self) -> str:
        """Construct complete multi-line message from header and continuation lines."""
        if not self.continuation_lines:
            return self.header_message
        return self.header_message + "\n" + "\n".join(self.continuation_lines)


@dataclass
class _ActiveEventState:
    """Internal mutable accumulator for multiline warning event assembly."""

    numeric_id: int
    context: str
    process_name: str
    local_timestamp: datetime
    metric_1: float
    metric_2: float
    header_message: str
    component: str | None
    method: str | None
    continuation_lines: list[str] = field(default_factory=list)
    physical_line_count: int = 1
    total_bytes: int = 0
    is_truncated: bool = False
    last_line_was_blank: bool = False

    def to_parsed_event(self) -> ParsedWarningEvent:
        return ParsedWarningEvent(
            numeric_id=self.numeric_id,
            context=self.context,
            process_name=self.process_name,
            local_timestamp=self.local_timestamp,
            metric_1=self.metric_1,
            metric_2=self.metric_2,
            header_message=self.header_message,
            continuation_lines=tuple(self.continuation_lines),
            physical_line_count=self.physical_line_count,
            total_bytes=self.total_bytes,
            is_truncated=self.is_truncated,
            component=self.component,
            method=self.method,
        )


class SuperOfficeWarningLogParser:
    """Deterministic multiline parser for SuperOffice warning log streams.

    Features:
    - Compiled regex matching confirmed header grammar (with decimal/integer metrics).
    - Neutral field naming (numeric_id, metric_1, metric_2 - no thread_id assumptions).
    - Trims whitespace padding from context and process fields.
    - Preserves naive local timestamp without assuming UTC directly.
    - Multiline event assembly bounded by max lines (50) and max bytes (16 KiB).
    - Ignores orphan continuation lines prior to the first valid header.
    - Safe handling for malformed header-like lines (closes active event, skips safely).
    - Collapses consecutive blank lines to prevent unbounded whitespace buffers.
    """

    def __init__(
        self,
        *,
        max_event_lines: int = DEFAULT_MAX_EVENT_LINES,
        max_event_bytes: int = DEFAULT_MAX_EVENT_BYTES,
    ) -> None:
        self._max_event_lines = max_event_lines
        self._max_event_bytes = max_event_bytes
        self._active_event: _ActiveEventState | None = None
        self._orphan_lines_skipped: int = 0
        self._malformed_headers_skipped: int = 0

    @property
    def orphan_lines_skipped(self) -> int:
        """Count of non-header lines encountered and skipped before first valid header."""
        return self._orphan_lines_skipped

    @property
    def malformed_headers_skipped(self) -> int:
        """Count of lines matching header prefix but failing full header parsing."""
        return self._malformed_headers_skipped

    @property
    def has_active_event(self) -> bool:
        """Whether the parser currently holds an uncompleted active event."""
        return self._active_event is not None

    @staticmethod
    def looks_like_header_prefix(line: str) -> bool:
        """Check if line starts with the characteristic header bracket sequence."""
        return bool(HEADER_PREFIX_PATTERN.match(line))

    def _handle_header_match(
        self, clean_line: str, match: re.Match[str]
    ) -> ParsedWarningEvent | None:
        header_bytes = len(clean_line.encode("utf-8")) + 1
        ts_str = match.group("timestamp")
        local_ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")

        msg_text = match.group("message")
        cm_match = COMPONENT_METHOD_PATTERN.match(msg_text)
        if cm_match is not None:
            component: str | None = cm_match.group(1)
            method: str | None = cm_match.group(2)
        else:
            component = None
            method = None

        completed_event = (
            self._active_event.to_parsed_event() if self._active_event is not None else None
        )

        self._active_event = _ActiveEventState(
            numeric_id=int(match.group("numeric_id")),
            context=match.group("context").strip(),
            process_name=match.group("process").strip(),
            local_timestamp=local_ts,
            metric_1=float(match.group("metric_1")),
            metric_2=float(match.group("metric_2")),
            header_message=msg_text,
            component=component,
            method=method,
            total_bytes=header_bytes,
        )

        return completed_event

    def _handle_continuation_line(self, clean_line: str) -> None:
        assert self._active_event is not None
        is_blank = not clean_line or clean_line.isspace()
        if is_blank:
            if self._active_event.last_line_was_blank:
                return
            self._active_event.last_line_was_blank = True
            content_to_append = ""
        else:
            self._active_event.last_line_was_blank = False
            content_to_append = clean_line

        line_bytes = len(content_to_append.encode("utf-8")) + 1
        new_line_count = self._active_event.physical_line_count + 1
        new_total_bytes = self._active_event.total_bytes + line_bytes

        if new_line_count > self._max_event_lines or new_total_bytes > self._max_event_bytes:
            self._active_event.is_truncated = True
            return

        self._active_event.continuation_lines.append(content_to_append)
        self._active_event.physical_line_count = new_line_count
        self._active_event.total_bytes = new_total_bytes

    def feed_line(self, line: str) -> ParsedWarningEvent | None:
        """Process a single physical line from the warning log stream.

        Returns:
            A completed ParsedWarningEvent if this line closed a previous event,
            or None if the line was accumulated into an active event or skipped.
        """
        clean_line = line.rstrip("\r\n")

        match = HEADER_PATTERN.match(clean_line)
        if match is not None:
            return self._handle_header_match(clean_line, match)

        if self.looks_like_header_prefix(clean_line):
            self._malformed_headers_skipped += 1
            if self._active_event is not None:
                completed_event = self._active_event.to_parsed_event()
                self._active_event = None
                return completed_event
            return None

        if self._active_event is None:
            if not clean_line or clean_line.isspace():
                return None
            self._orphan_lines_skipped += 1
            return None

        self._handle_continuation_line(clean_line)
        return None

    def end_of_file(self) -> ParsedWarningEvent | None:
        """Signal end of stream, emitting any remaining active event.

        Returns:
            The final completed ParsedWarningEvent if one was active, or None.
        """
        if self._active_event is not None:
            completed_event = self._active_event.to_parsed_event()
            self._active_event = None
            return completed_event
        return None

    def reset(self) -> None:
        """Reset parser state and clear any active in-progress event."""
        self._active_event = None
        self._orphan_lines_skipped = 0
        self._malformed_headers_skipped = 0
