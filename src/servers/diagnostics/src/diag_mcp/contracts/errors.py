"""Diagnostics-specific error models inheriting from platform_core errors."""

from typing import Any

from platform_core.errors import IntegrationError


class DatabaseDiagnosticError(IntegrationError):
    """Raised when an error occurs during MSSQL database diagnostic operations.

    Ensures connection strings, SQL statements, and database credentials are not
    leaked to the caller or AI layer.
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "DATABASE_DIAGNOSTIC_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            system_name="MSSQL_Diagnostics",
            error_code=error_code,
            details=details,
        )


class LogSearchError(IntegrationError):
    """Raised when an error occurs during application or API log search operations.

    Ensures file paths, backend endpoints, and raw queries are not leaked.
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "LOG_SEARCH_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            system_name="LogSearchEngine",
            error_code=error_code,
            details=details,
        )
