"""SuperOffice application warning-log location and prefix resolver (Gate 7A.4B1)."""

import asyncio
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from diag_mcp.contracts.errors import LogSearchError
from diag_mcp.settings import DiagnosticsServerSettings

# Authoritative fixed query (Gate 7A.4B1 Sections 3, 4, 27)
# Strictly read-only, explicit column, explicit dbo schema, no SELECT *, no NOLOCK, no dynamic SQL.
FIXED_CONFIG_WARNING_SQL = text("SELECT TOP (1) [warning] FROM [dbo].[config];")
FIXED_CONFIG_WARNING_SQL_STR = "SELECT TOP (1) [warning] FROM [dbo].[config];"

# Windows filesystem forbidden filename characters (Section 7, 8)
_INVALID_FILENAME_CHARS = frozenset('<>:"/\\|?*')
_MAX_CONFIG_PATH_LENGTH = 255


@dataclass(frozen=True, slots=True)
class ApplicationLogLocationDTO:
    """Internal DTO representing the resolved SuperOffice warning log location and prefix.

    Preserves parent directory and leading filename prefix distinction (Section 3).
    Does NOT assume any file extension (Section 9).
    """

    parent_directory: Path
    filename_prefix: str
    source: str  # "DATABASE" or "OVERRIDE"
    raw_configured_path: str
    drive: str = ""


def _validate_raw_path_string(raw_path: Any) -> str:
    """Validate raw configuration input string and basic invariants."""
    if not isinstance(raw_path, str):
        raise LogSearchError(
            "SuperOffice warning log location configuration is invalid.",
            error_code="APPLICATION_LOG_LOCATION_INVALID",
        )

    cleaned = raw_path.strip()
    if not cleaned:
        raise LogSearchError(
            "SuperOffice warning log location configuration is empty or whitespace.",
            error_code="APPLICATION_LOG_LOCATION_INVALID",
        )

    if len(cleaned) > _MAX_CONFIG_PATH_LENGTH:
        raise LogSearchError(
            "SuperOffice warning log location exceeds maximum length of 255 characters.",
            error_code="APPLICATION_LOG_LOCATION_INVALID",
        )

    if cleaned.endswith(("\\", "/")):
        raise LogSearchError(
            "SuperOffice warning log location is a directory path without a filename prefix.",
            error_code="APPLICATION_LOG_LOCATION_INVALID",
        )

    return cleaned


def _validate_prefix_characters(prefix: str) -> None:
    """Validate that the extracted filename prefix contains valid characters."""
    if not prefix:
        raise LogSearchError(
            "SuperOffice warning log location has an empty filename prefix.",
            error_code="APPLICATION_LOG_LOCATION_INVALID",
        )

    has_invalid_char = any(ch in _INVALID_FILENAME_CHARS for ch in prefix)
    has_control_char = any(ord(ch) < 32 for ch in prefix)
    if has_invalid_char or has_control_char:
        raise LogSearchError(
            "SuperOffice warning log prefix contains invalid filename characters.",
            error_code="APPLICATION_LOG_LOCATION_INVALID",
        )


def _parse_windows_spec(cleaned: str) -> tuple[Path, str, str]:
    """Parse a Windows path specification using PureWindowsPath."""
    win_path = PureWindowsPath(cleaned)
    drive = win_path.drive
    parent_pure = win_path.parent
    prefix = win_path.name

    if not prefix:
        raise LogSearchError(
            "SuperOffice warning log location cannot be a filesystem root.",
            error_code="APPLICATION_LOG_LOCATION_INVALID",
        )

    if str(parent_pure).rstrip("\\/") == drive:
        raise LogSearchError(
            "SuperOffice warning log parent directory cannot be a filesystem root.",
            error_code="APPLICATION_LOG_LOCATION_INVALID",
        )

    return Path(str(parent_pure)), prefix, drive


def _parse_posix_spec(cleaned: str) -> tuple[Path, str, str]:
    """Parse a POSIX path specification for test environments."""
    posix_path = Path(cleaned)
    prefix = posix_path.name
    parent_dir = posix_path.parent

    if not prefix:
        raise LogSearchError(
            "SuperOffice warning log location cannot be a filesystem root.",
            error_code="APPLICATION_LOG_LOCATION_INVALID",
        )

    if str(parent_dir) in ("/", ""):
        raise LogSearchError(
            "SuperOffice warning log parent directory cannot be a filesystem root.",
            error_code="APPLICATION_LOG_LOCATION_INVALID",
        )

    return parent_dir, prefix, ""


class ApplicationLogLocationResolver:
    """Resolves and validates the SuperOffice warning-log location from dbo.config or override.

    Enforces:
    - Conservative disabled-by-default behavior (APPLICATION_LOG_DISABLED)
    - Trusted runtime override precedence (DIAGNOSTICS_APPLICATION_LOG_PATH_OVERRIDE)
    - Fixed database query: SELECT TOP (1) [warning] FROM [dbo].[config];
    - Strict 5.0s statement query timeout (D01)
    - Windows path semantics via PureWindowsPath
    - Zero dynamic SQL and safe sanitized errors
    """

    def __init__(
        self,
        settings: DiagnosticsServerSettings | None = None,
        *,
        engine: AsyncEngine | None = None,
        enabled: bool | None = None,
        override_path: str | None = None,
        query_timeout_seconds: int | None = None,
    ) -> None:
        cfg = settings or DiagnosticsServerSettings()
        self._enabled = enabled if enabled is not None else cfg.application_log_enabled
        self._override_path = (
            override_path if override_path is not None else cfg.application_log_path_override
        )
        self._engine = engine
        self._query_timeout_seconds = (
            query_timeout_seconds
            if query_timeout_seconds is not None
            else cfg.mssql_query_timeout_seconds
        )

    @staticmethod
    def parse_path_prefix(raw_path: Any) -> tuple[Path, str, str]:
        """Validate and parse raw Windows path configuration into (parent_dir, prefix, drive).

        Raises LogSearchError with sanitized message (never exposing physical paths).

        Returns:
            tuple[Path, str, str]: (parent_directory, filename_prefix, drive)
        """
        cleaned = _validate_raw_path_string(raw_path)

        # A valid Windows absolute path must have both drive and root slash (e.g. D:\...)
        win_path = PureWindowsPath(cleaned)
        is_win_absolute = win_path.is_absolute()
        is_posix_absolute = Path(cleaned).is_absolute()

        if not is_win_absolute and not is_posix_absolute:
            raise LogSearchError(
                "SuperOffice warning log location must be an absolute path.",
                error_code="APPLICATION_LOG_LOCATION_INVALID",
            )

        if is_win_absolute:
            parent_dir, prefix, drive = _parse_windows_spec(cleaned)
        else:
            parent_dir, prefix, drive = _parse_posix_spec(cleaned)

        _validate_prefix_characters(prefix)
        return parent_dir, prefix, drive

    async def resolve_location(self) -> ApplicationLogLocationDTO:
        """Resolve and validate the SuperOffice warning-log location.

        Precedence (Section 10, 11):
        1. If application_log_enabled is False -> fails closed (APPLICATION_LOG_DISABLED)
        2. If application_log_path_override is set -> parse and return override location
        3. If unset -> execute fixed query on MSSQL database (D01 5s timeout)
        4. If neither succeeds -> fail closed (no silent directory guessing)

        Returns:
            ApplicationLogLocationDTO: Validated location DTO.

        Raises:
            LogSearchError: If disabled, unconfigured, database fails, or path is invalid.
        """
        if not self._enabled:
            raise LogSearchError(
                "SuperOffice application log backend is disabled.",
                error_code="APPLICATION_LOG_DISABLED",
            )

        # 1. Trusted runtime override takes precedence (Section 10)
        if self._override_path is not None and self._override_path.strip() != "":
            parent_dir, prefix, drive = self.parse_path_prefix(self._override_path)
            return ApplicationLogLocationDTO(
                parent_directory=parent_dir,
                filename_prefix=prefix,
                source="OVERRIDE",
                raw_configured_path=self._override_path.strip(),
                drive=drive,
            )

        # 2. Query database for dbo.config.warning (Section 3, 4, 5)
        if self._engine is None:
            raise LogSearchError(
                "Diagnostics database engine is not configured for application log resolution.",
                error_code="APPLICATION_LOG_LOCATION_QUERY_FAILED",
            )

        try:
            # Enforce D01: 5.0s statement timeout
            async with asyncio.timeout(self._query_timeout_seconds):
                async with self._engine.connect() as conn:
                    result = await conn.execute(FIXED_CONFIG_WARNING_SQL)
                    row = result.fetchone()
        except Exception:
            raise LogSearchError(
                "Failed to query SuperOffice warning log location from database.",
                error_code="APPLICATION_LOG_LOCATION_QUERY_FAILED",
            ) from None

        if row is None or row[0] is None or not str(row[0]).strip():
            raise LogSearchError(
                "SuperOffice warning log location is not configured in database.",
                error_code="APPLICATION_LOG_PATH_NOT_CONFIGURED",
            )

        raw_val = str(row[0]).strip()
        parent_dir, prefix, drive = self.parse_path_prefix(raw_val)

        return ApplicationLogLocationDTO(
            parent_directory=parent_dir,
            filename_prefix=prefix,
            source="DATABASE",
            raw_configured_path=raw_val,
            drive=drive,
        )
