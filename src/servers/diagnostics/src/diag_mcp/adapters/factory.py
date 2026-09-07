"""Factory for creating Diagnostics MSSQL database engine and repository adapters."""

import urllib.parse

import pyodbc  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from diag_mcp.adapters.mssql_repository import MssqlDiagnosticRepository
from diag_mcp.contracts.interfaces import DiagnosticRepository
from diag_mcp.settings import DiagnosticsServerSettings


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
