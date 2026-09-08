"""Knowledge-specific error models inheriting from platform_core errors."""

from typing import Any

from platform_core.errors import IntegrationError, PlatformError, ResourceNotFoundError


class KnowledgeSearchError(IntegrationError):
    """Raised when an error occurs during vector or full-text knowledge retrieval.

    Ensures connection URLs, PostgreSQL schemas, and backend vector parameters are not leaked.
    """

    def __init__(
        self,
        message: str,
        *,
        system_name: str = "KnowledgeStore",
        error_code: str = "KNOWLEDGE_SEARCH_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            system_name=system_name,
            error_code=error_code,
            details=details,
        )


class MalformedRunbookDataError(KnowledgeSearchError):
    """Raised when runbook step data (JSONB) in the database is malformed or invalid."""

    def __init__(
        self,
        message: str = "Runbook contains malformed diagnostic or remediation step data.",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="MALFORMED_RUNBOOK_DATA",
            details=details,
        )


class RunbookNotFoundError(ResourceNotFoundError):
    """Raised when a requested runbook identifier does not exist in the Knowledge repository."""

    def __init__(self, runbook_id: str) -> None:
        super().__init__(
            resource_type="Runbook",
            identifier=runbook_id,
        )


class KnowledgeBackendNotConfiguredError(KnowledgeSearchError):
    """Raised when a Knowledge MCP tool is invoked but the backend service is not configured."""

    def __init__(
        self,
        message: str = "Knowledge backend is not configured.",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="KNOWLEDGE_BACKEND_NOT_CONFIGURED",
            details=details,
        )


class EmbeddingError(PlatformError):
    """Base exception for all local embedding generation and provider errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "EMBEDDING_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, details=details)


class EmbeddingInputError(EmbeddingError):
    """Raised when an embedding input text or batch is empty, whitespace-only, or invalid."""

    def __init__(
        self,
        message: str = "Embedding input cannot be empty or whitespace-only.",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="EMBEDDING_INPUT_ERROR",
            details=details,
        )


class EmbeddingModelInitializationError(EmbeddingError):
    """Raised when the embedding model cannot be initialized or loaded."""

    def __init__(
        self,
        message: str = "Failed to initialize embedding model.",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="EMBEDDING_MODEL_INIT_ERROR",
            details=details,
        )


class EmbeddingInferenceError(EmbeddingError):
    """Raised when an error occurs during local embedding inference."""

    def __init__(
        self,
        message: str = "Embedding inference failed.",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="EMBEDDING_INFERENCE_ERROR",
            details=details,
        )


class EmbeddingDimensionError(EmbeddingError):
    """Raised when an embedding output dimension does not match the invariant dimension (384)."""

    def __init__(
        self,
        actual_dimension: int,
        expected_dimension: int = 384,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged = {"expected": expected_dimension, "actual": actual_dimension, **(details or {})}
        super().__init__(
            message=(
                f"Embedding dimension mismatch: expected {expected_dimension}, "
                f"got {actual_dimension}."
            ),
            error_code="EMBEDDING_DIMENSION_ERROR",
            details=merged,
        )


class KnowledgeRuntimeInitializationError(IntegrationError):
    """Raised when the Knowledge runtime environment is configured but fails to initialize."""

    def __init__(
        self,
        message: str = "Failed to initialize configured Knowledge runtime backend.",
        *,
        system_name: str = "KnowledgeRuntime",
        error_code: str = "KNOWLEDGE_RUNTIME_INIT_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            system_name=system_name,
            error_code=error_code,
            details=details,
        )


# ============================================================================
# Ingestion & Admission Errors (Gate 7D.5B / Local-v1)
# ============================================================================


class KnowledgeIngestionError(PlatformError):
    """Base exception for all knowledge ingestion pipeline errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "KNOWLEDGE_INGESTION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, details=details)


class KnowledgeAdmissionError(KnowledgeIngestionError):
    """Raised when a candidate source fails ingestion admission checks."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "KNOWLEDGE_ADMISSION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, details=details)


class KnowledgeContentRejectedError(KnowledgeAdmissionError):
    """Raised when source content is rejected due to security policy violations (secrets/PII)."""

    def __init__(
        self,
        message: str = "Source content rejected due to security policy violation.",
        *,
        reason: str = "SECURITY_VIOLATION",
        details: dict[str, Any] | None = None,
    ) -> None:
        merged = {"reason": reason, **(details or {})}
        super().__init__(
            message=message,
            error_code="KNOWLEDGE_CONTENT_REJECTED",
            details=merged,
        )
        self.reason = reason


class KnowledgeSourceFormatError(KnowledgeAdmissionError):
    """Raised when source content is malformed, invalid UTF-8, or violates schema."""

    def __init__(
        self,
        message: str = "Source content has an invalid or malformed format.",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="KNOWLEDGE_SOURCE_FORMAT_ERROR",
            details=details,
        )


class KnowledgeSizeLimitExceededError(KnowledgeAdmissionError):
    """Raised when source bytes or canonical text exceed frozen bounds."""

    def __init__(
        self,
        message: str = "Source content exceeds allowed size limits.",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="KNOWLEDGE_SIZE_LIMIT_EXCEEDED",
            details=details,
        )
