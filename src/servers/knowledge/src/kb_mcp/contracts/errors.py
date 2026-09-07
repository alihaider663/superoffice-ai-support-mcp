"""Knowledge-specific error models inheriting from platform_core errors."""

from typing import Any

from platform_core.errors import IntegrationError, ResourceNotFoundError


class KnowledgeSearchError(IntegrationError):
    """Raised when an error occurs during Supabase vector or full-text knowledge retrieval.

    Ensures Supabase URLs, PostgreSQL schemas, and backend vector parameters are not leaked.
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "KNOWLEDGE_SEARCH_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            system_name="SupabaseKnowledgeStore",
            error_code=error_code,
            details=details,
        )


class RunbookNotFoundError(ResourceNotFoundError):
    """Raised when a requested runbook identifier does not exist in the Knowledge repository."""

    def __init__(self, runbook_id: str) -> None:
        super().__init__(
            resource_type="Runbook",
            identifier=runbook_id,
        )
