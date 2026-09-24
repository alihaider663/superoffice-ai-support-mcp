"""Security validation and identifier sanitization for SuperOffice extra tables."""

import re
from typing import Any

from so_mcp.extra_tables.contracts import (
    SUPEROFFICE_STANDARD_COLUMNS,
    ExtraTableDetailSchemaDTO,
    SuperOfficeInvalidColumnError,
    SuperOfficeInvalidExtraTableError,
)

# Strict identifier regexes preventing SQL injection
_RE_TABLE_NAME = re.compile(r"^y_[a-z0-9_]{1,64}$")
_RE_IDENTIFIER_SAFE = re.compile(r"^[a-z0-9_]{1,64}$")

# Disallowed SQL tokens in any raw user string (fail-closed defense-in-depth)
_FORBIDDEN_SQL_SUBSTRINGS = (
    ";",
    "--",
    "/*",
    "*/",
    "xp_",
    "sp_",
    "sys.",
    "sysobjects",
    "information_schema",
)
_FORBIDDEN_SQL_KEYWORDS = {
    "exec",
    "execute",
    "drop",
    "alter",
    "create",
    "truncate",
    "insert",
    "update",
    "delete",
    "union",
    "select",
}


class ExtraTableSecurityValidator:
    """Enforces strict table whitelisting, column whitelisting, and SQL safety."""

    @staticmethod
    def normalize_table_name(table_name: str) -> str:
        """Normalize table name by stripping whitespace, lowercasing, and ensuring 'y_' prefix."""
        cleaned = table_name.strip().lower()
        if not cleaned:
            raise SuperOfficeInvalidExtraTableError(table_name, "Table name cannot be empty")

        for token in _FORBIDDEN_SQL_SUBSTRINGS:
            if token in cleaned:
                raise SuperOfficeInvalidExtraTableError(
                    table_name, f"Table name contains forbidden token '{token}'"
                )

        if not cleaned.startswith("y_"):
            cleaned = f"y_{cleaned}"

        if not _RE_TABLE_NAME.match(cleaned):
            raise SuperOfficeInvalidExtraTableError(
                table_name,
                "Table name contains invalid characters. Must match pattern '^y_[a-z0-9_]+$'",
            )

        if cleaned in _FORBIDDEN_SQL_KEYWORDS:
            raise SuperOfficeInvalidExtraTableError(
                table_name, f"Table name cannot be SQL reserved word '{cleaned}'"
            )

        return cleaned

    @staticmethod
    def validate_table_whitelisted(
        table_name: str,
        whitelist: set[str] | dict[str, Any],
    ) -> str:
        """Ensure the normalized table name exists in the approved catalog whitelist."""
        normalized = ExtraTableSecurityValidator.normalize_table_name(table_name)
        if normalized not in whitelist:
            raise SuperOfficeInvalidExtraTableError(
                normalized,
                "Table is not registered in SuperOffice extra_tables catalog",
            )
        return normalized

    @staticmethod
    def normalize_column_name(column_name: str) -> str:
        """Validate and normalize a column identifier."""
        cleaned = column_name.strip().lower()
        if not cleaned:
            raise SuperOfficeInvalidColumnError("unknown", "Column name cannot be empty")

        # Allow standard SuperOffice metadata columns without keyword collision
        standard_cols_lower = {col.lower() for col in SUPEROFFICE_STANDARD_COLUMNS}
        if cleaned in standard_cols_lower:
            return cleaned

        if not _RE_IDENTIFIER_SAFE.match(cleaned):
            raise SuperOfficeInvalidColumnError(
                "unknown",
                f"Column name '{column_name}' contains invalid characters",
            )

        for token in _FORBIDDEN_SQL_SUBSTRINGS:
            if token in cleaned:
                raise SuperOfficeInvalidColumnError(
                    "unknown",
                    f"Column name '{column_name}' contains forbidden token '{token}'",
                )

        if cleaned in _FORBIDDEN_SQL_KEYWORDS:
            raise SuperOfficeInvalidColumnError(
                "unknown",
                f"Column name '{column_name}' cannot be SQL reserved word '{cleaned}'",
            )

        return cleaned

    @staticmethod
    def get_allowed_columns_for_table(schema: ExtraTableDetailSchemaDTO) -> set[str]:
        """Derive the complete set of valid columns for a given table schema."""
        allowed = set(SUPEROFFICE_STANDARD_COLUMNS)
        for field in schema.fields:
            allowed.add(field.field_name.lower())
        return allowed

    @classmethod
    def validate_columns_for_table(
        cls,
        table_name: str,
        columns: list[str] | tuple[str, ...],
        schema: ExtraTableDetailSchemaDTO,
    ) -> list[str]:
        """Validate that all requested columns exist in the table's schema."""
        allowed_columns = cls.get_allowed_columns_for_table(schema)
        validated: list[str] = []

        for col in columns:
            normalized_col = cls.normalize_column_name(col)
            if normalized_col not in allowed_columns:
                raise SuperOfficeInvalidColumnError(table_name, col)
            validated.append(normalized_col)

        return validated

    @classmethod
    def validate_filter_keys(
        cls,
        table_name: str,
        filters: dict[str, Any],
        schema: ExtraTableDetailSchemaDTO,
    ) -> dict[str, Any]:
        """Validate that all filter keys exist in the table's schema."""
        allowed_columns = cls.get_allowed_columns_for_table(schema)
        validated_filters: dict[str, Any] = {}

        for key, val in filters.items():
            normalized_key = cls.normalize_column_name(key)
            if normalized_key not in allowed_columns:
                raise SuperOfficeInvalidColumnError(table_name, key)
            validated_filters[normalized_key] = val

        return validated_filters

    @classmethod
    def validate_order_by(
        cls,
        table_name: str,
        order_by: str | None,
        schema: ExtraTableDetailSchemaDTO,
    ) -> str:
        """Validate that order_by column exists in table's schema."""
        if not order_by:
            return "id"
        normalized = cls.normalize_column_name(order_by)
        allowed_columns = cls.get_allowed_columns_for_table(schema)
        if normalized not in allowed_columns:
            raise SuperOfficeInvalidColumnError(table_name, order_by)
        return normalized
