"""Contract and mapping integrity errors for Investigation MCP."""

from platform_core.errors import PlatformError


class InvestigationContractError(PlatformError):
    """Base exception for investigation public contract and mapping errors."""

    def __init__(
        self,
        message: str = "Investigation contract error",
        *,
        error_code: str = "INVESTIGATION_CONTRACT_ERROR",
    ) -> None:
        super().__init__(message)
        self.error_code = error_code


class InvalidEvidenceObservationError(InvestigationContractError):
    """Raised when internal diagnostic evidence fails exact discriminator identification."""

    def __init__(self, message: str = "Evidence observation discriminator failed") -> None:
        super().__init__(message, error_code="INVALID_EVIDENCE_OBSERVATION")


class InvalidSourceErrorCodeError(InvestigationContractError):
    """Raised when internal source outcome error code is not in the approved public allowlist."""

    def __init__(self, message: str = "Internal source error code is unmapped") -> None:
        super().__init__(message, error_code="INVALID_SOURCE_ERROR_CODE")


class InvalidEvidenceTimestampError(InvestigationContractError):
    """Raised when internal diagnostic evidence has an offset-naive timestamp."""

    def __init__(self, message: str = "Evidence timestamp must be timezone-aware") -> None:
        super().__init__(message, error_code="INVALID_EVIDENCE_TIMESTAMP")
