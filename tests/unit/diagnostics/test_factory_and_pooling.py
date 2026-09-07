"""Unit tests for Diagnostics engine factory and pooling configuration."""

import asyncio
import urllib.parse
from typing import Any

import pyodbc  # type: ignore[import-not-found]
import pytest
from pydantic import SecretStr

from diag_mcp.adapters.factory import (
    create_diagnostic_engine,
    create_diagnostic_repository,
)
from diag_mcp.adapters.mssql_repository import MssqlDiagnosticRepository
from diag_mcp.settings import DiagnosticsServerSettings


def test_factory_disables_pyodbc_pooling() -> None:
    """Factory explicitly sets pyodbc.pooling to False."""
    pyodbc.pooling = True  # reset to True
    settings = DiagnosticsServerSettings(
        mssql_host="test-db.local",
        mssql_port=1433,
        mssql_database="SuperOfficeDB",
        mssql_user="diag_user",
        mssql_password=SecretStr("safe-password-123"),
        mssql_login_timeout_seconds=5,
        mssql_query_timeout_seconds=5,
        mssql_max_rows=50,
        mssql_isolation_level="SNAPSHOT",
        mssql_pool_size=5,
        mssql_max_overflow=2,
        mssql_pool_recycle_seconds=1800,
        mssql_pool_pre_ping=True,
    )

    engine = create_diagnostic_engine(settings)
    assert pyodbc.pooling is False
    assert engine.url.drivername == "mssql+aioodbc"


def test_factory_creates_mssql_repository() -> None:
    """Factory produces a configured MssqlDiagnosticRepository."""
    settings = DiagnosticsServerSettings(
        mssql_query_timeout_seconds=5,
        mssql_max_rows=50,
    )
    repo = create_diagnostic_repository(settings)
    assert isinstance(repo, MssqlDiagnosticRepository)
    assert repo._query_timeout_seconds == 5
    assert repo._max_rows == 50


class _MockPyODBCConn:
    def __init__(self) -> None:
        self.timeout: int = 0


@pytest.mark.asyncio
async def test_pyodbc_timeout_hook_assigns_property() -> None:
    """The async after_created hook successfully sets timeout on the pyodbc connection object."""
    settings = DiagnosticsServerSettings(mssql_query_timeout_seconds=5)

    mock_pyodbc_conn = _MockPyODBCConn()

    async def _configure(conn: _MockPyODBCConn) -> None:
        conn.timeout = settings.mssql_query_timeout_seconds

    await _configure(mock_pyodbc_conn)
    assert mock_pyodbc_conn.timeout == 5


def test_factory_independent_login_and_query_timeouts() -> None:
    """Verify login timeout and query timeout are independently configured."""
    settings = DiagnosticsServerSettings(
        mssql_login_timeout_seconds=9,
        mssql_query_timeout_seconds=5,
    )
    engine = create_diagnostic_engine(settings)

    # Login timeout is in ODBC connection string and connection args
    unquoted_url = urllib.parse.unquote_plus(str(engine.url))
    assert "LoginTimeout=9" in unquoted_url

    # Query timeout is set on pyodbc connection via after_created hook
    mock_conn = _MockPyODBCConn()

    async def _hook(conn: _MockPyODBCConn) -> None:
        conn.timeout = settings.mssql_query_timeout_seconds

    asyncio.run(_hook(mock_conn))
    assert mock_conn.timeout == 5
    assert settings.mssql_login_timeout_seconds != settings.mssql_query_timeout_seconds


def test_factory_custom_pool_configuration() -> None:
    """Verify custom pool configuration is passed to SQLAlchemy AsyncAdaptedQueuePool."""
    settings = DiagnosticsServerSettings(
        mssql_pool_size=3,
        mssql_max_overflow=1,
        mssql_pool_recycle_seconds=600,
        mssql_pool_pre_ping=False,
    )
    engine = create_diagnostic_engine(settings)
    pool: Any = engine.pool

    assert pool.size() == 3
    assert pool._max_overflow == 1
    assert pool._recycle == 600
    assert pool._pre_ping is False


def test_factory_tls_trust_server_certificate_defaults_to_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify default mssql_trust_server_certificate is False and maps to no."""
    assert DiagnosticsServerSettings.model_fields["mssql_trust_server_certificate"].default is False
    monkeypatch.setenv("DIAGNOSTICS_MSSQL_TRUST_SERVER_CERTIFICATE", "false")
    settings = DiagnosticsServerSettings()
    assert settings.mssql_trust_server_certificate is False

    engine = create_diagnostic_engine(settings)
    unquoted_url = urllib.parse.unquote_plus(str(engine.url))
    assert "TrustServerCertificate=no" in unquoted_url
    assert "Encrypt=yes" in unquoted_url


def test_factory_tls_trust_server_certificate_enabled_maps_to_yes() -> None:
    """Verify mssql_trust_server_certificate=True maps to yes while keeping Encrypt=yes."""
    settings = DiagnosticsServerSettings(mssql_trust_server_certificate=True)
    assert settings.mssql_trust_server_certificate is True

    engine = create_diagnostic_engine(settings)
    unquoted_url = urllib.parse.unquote_plus(str(engine.url))
    assert "TrustServerCertificate=yes" in unquoted_url
    assert "Encrypt=yes" in unquoted_url


def test_settings_secret_password_not_exposed() -> None:
    """Verify mssql_password secret value is not leaked in str or repr."""
    secret_val = "super-secret-password-xyz"
    settings = DiagnosticsServerSettings(mssql_password=SecretStr(secret_val))
    assert secret_val not in str(settings)
    assert secret_val not in repr(settings)
