"""SuperOffice extra tables discovery and querying package."""

from so_mcp.extra_tables.contracts import (
    SUPEROFFICE_FIELD_TYPE_MAP,
    SUPEROFFICE_STANDARD_COLUMNS,
    ExtraFieldDefinitionDTO,
    ExtraTableDetailSchemaDTO,
    ExtraTableQueryCriteriaDTO,
    ExtraTableQueryResultDTO,
    ExtraTableSummaryDTO,
    SuperOfficeExtraTableQueryError,
    SuperOfficeInvalidColumnError,
    SuperOfficeInvalidExtraTableError,
    get_field_type_name,
)
from so_mcp.extra_tables.repository import (
    ExtraTableRepositoryProtocol,
    FakeExtraTableRepository,
    LocalMirrorExtraTableRepository,
    MssqlExtraTableRepository,
)
from so_mcp.extra_tables.service import ExtraTableService
from so_mcp.extra_tables.validator import ExtraTableSecurityValidator

__all__ = [
    "SUPEROFFICE_FIELD_TYPE_MAP",
    "SUPEROFFICE_STANDARD_COLUMNS",
    "ExtraFieldDefinitionDTO",
    "ExtraTableDetailSchemaDTO",
    "ExtraTableQueryCriteriaDTO",
    "ExtraTableQueryResultDTO",
    "ExtraTableRepositoryProtocol",
    "ExtraTableSecurityValidator",
    "ExtraTableService",
    "ExtraTableSummaryDTO",
    "FakeExtraTableRepository",
    "LocalMirrorExtraTableRepository",
    "MssqlExtraTableRepository",
    "SuperOfficeExtraTableQueryError",
    "SuperOfficeInvalidColumnError",
    "SuperOfficeInvalidExtraTableError",
    "get_field_type_name",
]
