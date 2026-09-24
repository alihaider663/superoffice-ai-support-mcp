"""Application service coordinating SuperOffice extra tables discovery,
querying, and PII sanitization.
"""

import logging
from typing import Any

from platform_security.interfaces import OutputSanitizer
from platform_security.sanitization import RecursiveOutputSanitizer
from so_mcp.extra_tables.contracts import (
    ExtraTableDetailSchemaDTO,
    ExtraTableQueryCriteriaDTO,
    ExtraTableQueryResultDTO,
    ExtraTableSummaryDTO,
    SuperOfficeInvalidExtraTableError,
)
from so_mcp.extra_tables.repository import ExtraTableRepositoryProtocol
from so_mcp.extra_tables.validator import ExtraTableSecurityValidator

logger = logging.getLogger(__name__)


class ExtraTableService:
    """Coordinates business logic, security validation, and PII scrubbing for extra tables."""

    def __init__(
        self,
        repository: ExtraTableRepositoryProtocol,
        sanitizer: OutputSanitizer | None = None,
    ) -> None:
        self._repository = repository
        self._sanitizer = sanitizer or RecursiveOutputSanitizer()

    async def list_extra_tables(
        self,
        search: str | None = None,
    ) -> list[ExtraTableSummaryDTO]:
        """Discover and list all registered extra tables."""
        return await self._repository.list_tables(search=search)

    async def get_extra_table_schema(
        self,
        table_name: str,
    ) -> ExtraTableDetailSchemaDTO:
        """Retrieve the verified schema definition for a specific extra table."""
        normalized = ExtraTableSecurityValidator.normalize_table_name(table_name)
        schema = await self._repository.get_table_schema(normalized)
        if schema is None:
            raise SuperOfficeInvalidExtraTableError(
                table_name,
                "Extra table does not exist or is not registered in SuperOffice catalog",
            )
        return schema

    async def query_extra_table(
        self,
        criteria: ExtraTableQueryCriteriaDTO,
    ) -> ExtraTableQueryResultDTO:
        """Validate criteria, query target extra table, and sanitize output rows."""
        # 1. Validate table exists in catalog
        schema = await self.get_extra_table_schema(criteria.table_name)

        # 2. Execute query via repository
        raw_result = await self._repository.query_table(criteria, schema)

        # 3. Sanitize returned rows to scrub PII and credentials
        sanitized_rows: list[dict[str, Any]] = []
        for row in raw_result.rows:
            sanitized_row = self._sanitizer.sanitize(row)
            if isinstance(sanitized_row, dict):
                sanitized_rows.append(sanitized_row)
            else:
                sanitized_rows.append(row)

        return ExtraTableQueryResultDTO(
            table_name=raw_result.table_name,
            total_rows_returned=raw_result.total_rows_returned,
            limit=raw_result.limit,
            offset=raw_result.offset,
            columns=raw_result.columns,
            rows=tuple(sanitized_rows),
        )
