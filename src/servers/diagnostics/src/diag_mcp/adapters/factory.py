"""Factory for creating Diagnostics MSSQL database engine and repository adapters."""

import logging
import urllib.parse
from pathlib import Path

import pyodbc  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from diag_mcp.adapters.app_log_locator import WarningLogCandidateLocator
from diag_mcp.adapters.app_log_resolver import ApplicationLogLocationResolver
from diag_mcp.adapters.composite_log_adapter import CompositeLogSearchAdapter
from diag_mcp.adapters.iis_log_reader import SuperOfficeIisW3cLogReader
from diag_mcp.adapters.mssql_repository import MssqlDiagnosticRepository
from diag_mcp.adapters.warning_log_reader import SuperOfficeWarningLogReader
from diag_mcp.contracts.interfaces import DiagnosticRepository, LogSearchClient
from diag_mcp.settings import DiagnosticsServerSettings

logger = logging.getLogger(__name__)


def create_diagnostic_engine(settings: DiagnosticsServerSettings) -> AsyncEngine:
    """Create a SQLAlchemy 2.0 AsyncEngine configured for read-only MSSQL diagnostics.

    Enforces SNAPSHOT isolation, 5s statement query timeouts, distinct login timeouts,
    configurable connection pooling, and disabled PyODBC pooling.
    """
    # 1. Disable PyODBC global pooling at server bootstrap boundary
    pyodbc.pooling = False

    # 2. Build ODBC connection string
    password_str = settings.mssql_password.get_secret_value()
    trust_cert = "yes" if settings.mssql_trust_server_certificate else "no"
    odbc_params = [
        "Driver={ODBC Driver 18 for SQL Server}",
        f"Server=tcp:{settings.mssql_host},{settings.mssql_port}",
        f"Database={settings.mssql_database}",
        f"UID={settings.mssql_user}",
        f"PWD={password_str}",
        "Encrypt=yes",
        f"TrustServerCertificate={trust_cert}",
        f"LoginTimeout={settings.mssql_login_timeout_seconds}",
    ]
    odbc_str = ";".join(odbc_params)
    quoted_odbc_str = urllib.parse.quote_plus(odbc_str)
    connection_url = f"mssql+aioodbc:///?odbc_connect={quoted_odbc_str}"

    query_timeout_seconds = settings.mssql_query_timeout_seconds

    # 3. Asynchronous post-connect hook setting pyodbc.Connection.timeout for statement execution
    async def _configure_pyodbc_connection(pyodbc_conn: pyodbc.Connection) -> None:
        pyodbc_conn.timeout = query_timeout_seconds

    # 4. Create AsyncEngine with AsyncAdaptedQueuePool, configured settings, and SNAPSHOT isolation
    return create_async_engine(
        connection_url,
        poolclass=AsyncAdaptedQueuePool,
        isolation_level=settings.mssql_isolation_level,
        pool_size=settings.mssql_pool_size,
        max_overflow=settings.mssql_max_overflow,
        pool_recycle=settings.mssql_pool_recycle_seconds,
        pool_pre_ping=settings.mssql_pool_pre_ping,
        connect_args={
            "after_created": _configure_pyodbc_connection,
            "timeout": settings.mssql_login_timeout_seconds,
        },
    )


def create_diagnostic_repository(settings: DiagnosticsServerSettings) -> DiagnosticRepository:
    """Create a configured MssqlDiagnosticRepository."""
    engine = create_diagnostic_engine(settings)
    return MssqlDiagnosticRepository(
        engine=engine,
        query_timeout_seconds=settings.mssql_query_timeout_seconds,
        max_rows=settings.mssql_max_rows,
    )


def create_application_log_resolver(
    settings: DiagnosticsServerSettings,
    *,
    engine: AsyncEngine | None = None,
) -> ApplicationLogLocationResolver:
    """Create a configured ApplicationLogLocationResolver."""
    return ApplicationLogLocationResolver(
        settings=settings,
        engine=engine,
    )


def create_warning_log_candidate_locator(
    settings: DiagnosticsServerSettings,
) -> WarningLogCandidateLocator:
    """Create a configured WarningLogCandidateLocator."""
    return WarningLogCandidateLocator(settings=settings)


def create_warning_log_reader(
    settings: DiagnosticsServerSettings,
    *,
    locator: WarningLogCandidateLocator | None = None,
    location_resolver: ApplicationLogLocationResolver | None = None,
    log_dir: Path | None = None,
    application_log_timezone: str | None = None,
) -> SuperOfficeWarningLogReader:
    """Create a configured SuperOfficeWarningLogReader."""
    return SuperOfficeWarningLogReader(
        settings=settings,
        locator=locator,
        location_resolver=location_resolver,
        log_dir=log_dir,
        application_log_timezone=application_log_timezone,
    )


def create_iis_log_reader(
    settings: DiagnosticsServerSettings,
    *,
    log_dir: Path | None = None,
) -> SuperOfficeIisW3cLogReader:
    """Create a configured SuperOfficeIisW3cLogReader."""
    return SuperOfficeIisW3cLogReader(
        settings=settings,
        log_dir=log_dir,
    )


def create_composite_log_adapter(
    settings: DiagnosticsServerSettings,
    *,
    iis_reader: LogSearchClient | None = None,
    warning_reader: LogSearchClient | None = None,
    engine: AsyncEngine | None = None,
) -> CompositeLogSearchAdapter:
    """Create a configured CompositeLogSearchAdapter based on server settings.

    Preserves admin configuration intent (iis_enabled and warning_enabled) even if
    individual reader initialization fails, ensuring fail-closed runtime semantics.
    """
    active_iis_reader = iis_reader
    if active_iis_reader is None and settings.iis_log_enabled:
        try:
            active_iis_reader = create_iis_log_reader(settings)
        except Exception as exc:
            logger.exception("Failed to initialize IIS log reader adapter: %s", exc)
            active_iis_reader = None

    active_warning_reader = warning_reader
    if active_warning_reader is None and settings.application_log_enabled:
        try:
            active_resolver = None
            if not settings.application_log_path_override:
                active_engine = engine or create_diagnostic_engine(settings)
                active_resolver = create_application_log_resolver(settings, engine=active_engine)
            active_warning_reader = create_warning_log_reader(
                settings,
                location_resolver=active_resolver,
            )
        except Exception as exc:
            logger.exception("Failed to initialize Warning log reader adapter: %s", exc)
            active_warning_reader = None

    return CompositeLogSearchAdapter(
        iis_reader=active_iis_reader,
        warning_reader=active_warning_reader,
        iis_enabled=settings.iis_log_enabled,
        warning_enabled=settings.application_log_enabled,
    )
