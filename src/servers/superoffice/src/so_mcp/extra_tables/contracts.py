"""Contracts and DTOs for SuperOffice user-defined extra tables (y_*)."""

from typing import Any, Literal

from pydantic import Field

from platform_core.errors import DomainValidationError, IntegrationError
from platform_core.models import PlatformBaseModel

# Standard metadata columns present on physical SuperOffice tables
SUPEROFFICE_STANDARD_COLUMNS: tuple[str, ...] = (
    "id",
    "registered",
    "registered_associate_id",
    "updated",
    "updated_associate_id",
    "updatedCount",
)

# Friendly mapping for SuperOffice extra_fields type IDs
SUPEROFFICE_FIELD_TYPE_MAP: dict[int, str] = {
    1: "integer",
    2: "float",
    3: "currency",
    4: "date",
    5: "time",
    6: "boolean",
    7: "dropdown",
    8: "document",
    9: "image",
    10: "string",
    11: "text",
    12: "associate_id",
    13: "link",
}


def get_field_type_name(type_id: int | None) -> str:
    """Return friendly name for a SuperOffice field type code."""
    if type_id is None:
        return "unknown"
    return SUPEROFFICE_FIELD_TYPE_MAP.get(type_id, f"type_{type_id}")


# ============================================================================
# Domain Exceptions
# ============================================================================


class SuperOfficeInvalidExtraTableError(DomainValidationError):
    """Raised when an extra table name fails validation or is not in the whitelist."""

    def __init__(self, table_name: str, reason: str = "Invalid or unapproved extra table") -> None:
        super().__init__(
            f"{reason}: '{table_name}'. Only registered 'y_*' tables are accessible.",
            field_name="table_name",
            details={"table_name": table_name, "error_code": "SUPEROFFICE_INVALID_EXTRA_TABLE"},
        )


class SuperOfficeInvalidColumnError(DomainValidationError):
    """Raised when a requested column fails whitelist validation for the target table."""

    def __init__(self, table_name: str, column_name: str) -> None:
        super().__init__(
            f"Invalid column '{column_name}' for extra table '{table_name}'. "
            "Only approved schema columns may be selected, filtered, or ordered.",
            field_name="column_name",
            details={
                "table_name": table_name,
                "column_name": column_name,
                "error_code": "SUPEROFFICE_INVALID_COLUMN",
            },
        )


class SuperOfficeExtraTableQueryError(IntegrationError):
    """Raised when an extra table query execution fails at the database boundary."""

    def __init__(
        self,
        message: str,
        table_name: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged = {"table_name": table_name, **(details or {})}
        super().__init__(
            message=message,
            system_name="SuperOffice",
            error_code="SUPEROFFICE_EXTRA_TABLE_QUERY_ERROR",
            details=merged,
        )


# ============================================================================
# DTO Models
# ============================================================================


class ExtraFieldDefinitionDTO(PlatformBaseModel):
    """Field schema definition inside a custom extra table."""

    id: int = Field(..., description="Extra field definition ID")
    extra_table_id: int = Field(..., description="Parent extra table ID")
    field_name: str = Field(..., description="Physical column name (e.g. x_msisdn)")
    display_name: str = Field(default="", description="Human-readable field label")
    type_code: int = Field(default=0, description="Raw SuperOffice type identifier")
    type_name: str = Field(
        default="string",
        description="Friendly type name (string, integer, etc.)",
    )
    default_value: str = Field(default="", description="Default field value")
    description: str = Field(default="", description="Field purpose description")


class ExtraTableSummaryDTO(PlatformBaseModel):
    """Summary of a user-defined extra table."""

    id: int = Field(..., description="Extra table catalog ID")
    table_name: str = Field(..., description="Physical table name (e.g. y_subscription)")
    display_name: str = Field(default="", description="Human-readable table name")
    description: str = Field(default="", description="Table purpose or description")
    field_count: int = Field(default=0, description="Number of custom x_* fields defined")


class ExtraTableDetailSchemaDTO(PlatformBaseModel):
    """Complete schema definition of a custom extra table including fields."""

    id: int = Field(..., description="Extra table catalog ID")
    table_name: str = Field(..., description="Physical table name (e.g. y_subscription)")
    display_name: str = Field(default="", description="Human-readable table name")
    description: str = Field(default="", description="Table purpose or description")
    fields: tuple[ExtraFieldDefinitionDTO, ...] = Field(
        default=(), description="Custom x_* field definitions"
    )
    standard_columns: tuple[str, ...] = Field(
        default=SUPEROFFICE_STANDARD_COLUMNS,
        description="Standard SuperOffice metadata columns present on physical table",
    )


class ExtraTableQueryCriteriaDTO(PlatformBaseModel):
    """Criteria for querying rows from an extra table."""

    table_name: str = Field(..., min_length=3, description="Target extra table name")
    fields: tuple[str, ...] | None = Field(
        default=None,
        description="Specific column names to select. If omitted, selects id and all extra fields.",
    )
    filters: dict[str, Any] | None = Field(
        default=None,
        description="Column-value filter mapping (equality or prefix)",
    )
    order_by: str | None = Field(
        default="id",
        description="Column to sort by (defaults to id)",
    )
    order_direction: Literal["asc", "desc"] = Field(
        default="asc",
        description="Sort direction (asc or desc)",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=50,
        description="Maximum rows to return (1..50, hard ceiling: 50)",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of rows to skip for pagination",
    )


class ExtraTableQueryResultDTO(PlatformBaseModel):
    """Result of an extra table query."""

    table_name: str = Field(..., description="Target extra table name")
    total_rows_returned: int = Field(..., ge=0, description="Number of rows in this page")
    limit: int = Field(..., ge=1, le=50, description="Requested limit")
    offset: int = Field(..., ge=0, description="Requested offset")
    columns: tuple[str, ...] = Field(..., description="Returned column names in order")
    rows: tuple[dict[str, Any], ...] = Field(..., description="List of row dictionaries")
