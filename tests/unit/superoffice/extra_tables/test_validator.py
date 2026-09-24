"""Unit tests for ExtraTableSecurityValidator."""

import pytest

from so_mcp.extra_tables.contracts import (
    ExtraFieldDefinitionDTO,
    ExtraTableDetailSchemaDTO,
    SuperOfficeInvalidColumnError,
    SuperOfficeInvalidExtraTableError,
)
from so_mcp.extra_tables.validator import ExtraTableSecurityValidator


@pytest.fixture
def sample_schema() -> ExtraTableDetailSchemaDTO:
    return ExtraTableDetailSchemaDTO(
        id=1,
        table_name="y_subscription",
        display_name="Subscription",
        description="Mobile subscriptions",
        fields=(
            ExtraFieldDefinitionDTO(
                id=1,
                extra_table_id=1,
                field_name="x_msisdn",
                display_name="MSISDN",
                type_code=10,
                type_name="string",
            ),
            ExtraFieldDefinitionDTO(
                id=2,
                extra_table_id=1,
                field_name="x_brand",
                display_name="Brand",
                type_code=10,
                type_name="string",
            ),
            ExtraFieldDefinitionDTO(
                id=3,
                extra_table_id=1,
                field_name="x_active",
                display_name="Active",
                type_code=6,
                type_name="boolean",
            ),
        ),
    )


def test_normalize_table_name_success() -> None:
    validator = ExtraTableSecurityValidator
    assert validator.normalize_table_name("subscription") == "y_subscription"
    assert validator.normalize_table_name("y_subscription") == "y_subscription"
    assert validator.normalize_table_name("  Y_LOGTICKET  ") == "y_logticket"
    assert validator.normalize_table_name("y_case_categories") == "y_case_categories"


def test_normalize_table_name_rejects_empty_or_whitespace() -> None:
    validator = ExtraTableSecurityValidator
    with pytest.raises(SuperOfficeInvalidExtraTableError):
        validator.normalize_table_name("")
    with pytest.raises(SuperOfficeInvalidExtraTableError):
        validator.normalize_table_name("   ")


def test_normalize_table_name_rejects_sql_injection() -> None:
    validator = ExtraTableSecurityValidator
    with pytest.raises(SuperOfficeInvalidExtraTableError):
        validator.normalize_table_name("y_sub; DROP TABLE users;--")
    with pytest.raises(SuperOfficeInvalidExtraTableError):
        validator.normalize_table_name("y_table/*comment*/")
    with pytest.raises(SuperOfficeInvalidExtraTableError):
        validator.normalize_table_name("sys.tables")
    with pytest.raises(SuperOfficeInvalidExtraTableError):
        validator.normalize_table_name("y_sub union select 1")


def test_validate_table_whitelisted() -> None:
    validator = ExtraTableSecurityValidator
    whitelist = {"y_subscription", "y_logticket"}

    assert validator.validate_table_whitelisted("subscription", whitelist) == "y_subscription"
    assert validator.validate_table_whitelisted("y_logticket", whitelist) == "y_logticket"

    with pytest.raises(SuperOfficeInvalidExtraTableError):
        validator.validate_table_whitelisted("y_unknown", whitelist)


def test_normalize_column_name_success() -> None:
    validator = ExtraTableSecurityValidator
    assert validator.normalize_column_name("x_msisdn") == "x_msisdn"
    assert validator.normalize_column_name("  X_BRAND  ") == "x_brand"
    assert validator.normalize_column_name("id") == "id"


def test_normalize_column_name_rejects_sql_injection() -> None:
    validator = ExtraTableSecurityValidator
    with pytest.raises(SuperOfficeInvalidColumnError):
        validator.normalize_column_name("col; exec sp_help")
    with pytest.raises(SuperOfficeInvalidColumnError):
        validator.normalize_column_name("col' OR 1=1--")
    with pytest.raises(SuperOfficeInvalidColumnError):
        validator.normalize_column_name("")


def test_validate_columns_for_table(sample_schema: ExtraTableDetailSchemaDTO) -> None:
    validator = ExtraTableSecurityValidator
    # Standard columns and defined custom columns succeed
    valid_cols = ["id", "x_msisdn", "x_brand", "updated"]
    res = validator.validate_columns_for_table("y_subscription", valid_cols, sample_schema)
    assert res == ["id", "x_msisdn", "x_brand", "updated"]

    # Unknown column fails
    with pytest.raises(SuperOfficeInvalidColumnError):
        validator.validate_columns_for_table(
            "y_subscription", ["x_msisdn", "x_secret_unregistered"], sample_schema
        )


def test_validate_filter_keys(sample_schema: ExtraTableDetailSchemaDTO) -> None:
    validator = ExtraTableSecurityValidator
    filters = {"x_brand": "Main", "x_active": "1"}
    res = validator.validate_filter_keys("y_subscription", filters, sample_schema)
    assert res == {"x_brand": "Main", "x_active": "1"}

    with pytest.raises(SuperOfficeInvalidColumnError):
        validator.validate_filter_keys("y_subscription", {"password_hash": "123"}, sample_schema)


def test_validate_order_by(sample_schema: ExtraTableDetailSchemaDTO) -> None:
    validator = ExtraTableSecurityValidator
    assert validator.validate_order_by("y_subscription", None, sample_schema) == "id"
    assert validator.validate_order_by("y_subscription", "x_msisdn", sample_schema) == "x_msisdn"
    assert validator.validate_order_by("y_subscription", "updated", sample_schema) == "updated"

    with pytest.raises(SuperOfficeInvalidColumnError):
        validator.validate_order_by("y_subscription", "invalid_col", sample_schema)
