"""SuperOffice integration and entity error hierarchy."""

from typing import Any

from platform_core.errors import IntegrationError, ResourceNotFoundError


class SuperOfficeIntegrationError(IntegrationError):
    """Raised when an interaction with the SuperOffice REST WebAPI fails."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "SUPEROFFICE_INTEGRATION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            system_name="SuperOffice",
            error_code=error_code,
            details=details,
        )


class SuperOfficeAuthenticationError(IntegrationError):
    """Raised when SuperOffice API service-account credentials or tokens fail."""

    def __init__(
        self,
        message: str = "SuperOffice API service-account authentication failed.",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            system_name="SuperOffice",
            error_code="SUPEROFFICE_AUTH_FAILURE",
            details=details,
        )


class SuperOfficeEntityNotFoundError(ResourceNotFoundError):
    """Raised when a requested SuperOffice ticket, company, or contact does not exist."""

    def __init__(self, entity_type: str, identifier: str | int) -> None:
        super().__init__(resource_type=f"SuperOffice {entity_type}", identifier=identifier)
