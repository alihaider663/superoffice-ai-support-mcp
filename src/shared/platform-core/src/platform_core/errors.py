"""Standard hierarchical exception tree for the SuperOffice AI Support Platform."""

from typing import Any


class PlatformError(Exception):
    """Base exception for all domain, infrastructure, and protocol errors in the platform."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "INTERNAL_PLATFORM_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to structured error dictionary."""
        return {
            "error": self.error_code,
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
        }

    def to_sanitized_dict(self) -> dict[str, Any]:
        """Convert exception to structured error dictionary safe for client emission."""
        return self.to_dict()


class ConfigurationError(PlatformError):
    """Raised when environment variables or application settings are invalid or missing."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, error_code="CONFIGURATION_ERROR", details=details)


class DomainValidationError(PlatformError):
    """Raised when input parameters fail domain validation rules."""

    def __init__(
        self,
        message: str,
        *,
        field_name: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = {"field": field_name, **(details or {})} if field_name else (details or {})
        super().__init__(message, error_code="VALIDATION_ERROR", details=merged_details)


# Backward-compatible alias
ValidationError = DomainValidationError


class SecurityError(PlatformError):
    """Base exception for authentication, authorization, and sanitization violations."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "SECURITY_VIOLATION",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, error_code=error_code, details=details)


class AuthenticationError(SecurityError):
    """Raised when authentication credentials or tokens are invalid or expired."""

    def __init__(
        self,
        message: str = "Authentication failed.",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, error_code="AUTHENTICATION_FAILED", details=details)


class AuthorizationError(SecurityError):
    """Raised when a caller lacks required permissions to access a resource or tool."""

    def __init__(
        self,
        message: str = "Permission denied for requested action.",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, error_code="AUTHORIZATION_DENIED", details=details)


class DataSanitizationError(SecurityError):
    """Raised when PII masking or output sanitization fails."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, error_code="SANITIZATION_ERROR", details=details)


class ResourceNotFoundError(PlatformError):
    """Raised when a requested domain entity or resource does not exist."""

    def __init__(self, resource_type: str, identifier: str | int) -> None:
        super().__init__(
            f"{resource_type} with identifier '{identifier}' was not found.",
            error_code="RESOURCE_NOT_FOUND",
            details={"resource_type": resource_type, "identifier": str(identifier)},
        )


class IntegrationError(PlatformError):
    """Base exception for external integration failures."""

    def __init__(
        self,
        message: str,
        *,
        system_name: str,
        error_code: str = "INTEGRATION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = {"system": system_name, **(details or {})}
        super().__init__(message, error_code=error_code, details=merged_details)
        self.system_name = system_name


class IntegrationConnectionError(IntegrationError):
    """Raised when an external system is unreachable or connection fails."""

    def __init__(
        self,
        system_name: str,
        message: str = "Failed to establish connection.",
    ) -> None:
        super().__init__(
            f"Unable to connect to {system_name}: {message}",
            system_name=system_name,
            error_code="INTEGRATION_CONNECTION_ERROR",
        )


class TimeoutError(PlatformError):
    """Raised when an operation or query exceeds its execution time budget."""

    def __init__(self, operation_name: str, timeout_seconds: float) -> None:
        super().__init__(
            f"Operation '{operation_name}' timed out after {timeout_seconds:.1f}s.",
            error_code="OPERATION_TIMEOUT",
            details={"operation": operation_name, "timeout_seconds": timeout_seconds},
        )


class ProtocolViolationError(PlatformError):
    """Raised when an incoming or outgoing payload violates MCP JSON-RPC protocol contracts."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, error_code="PROTOCOL_VIOLATION", details=details)


class RateLimitExceededError(SecurityError):
    """Raised when a caller exceeds the configured request rate limit."""

    def __init__(
        self,
        limit_per_minute: int,
        *,
        retry_after_seconds: float = 60.0,
    ) -> None:
        msg = f"Rate limit of {limit_per_minute} req/min exceeded. Retry in {retry_after_seconds}s."
        super().__init__(
            msg,
            error_code="RATE_LIMIT_EXCEEDED",
            details={
                "limit_per_minute": limit_per_minute,
                "retry_after_seconds": retry_after_seconds,
            },
        )
