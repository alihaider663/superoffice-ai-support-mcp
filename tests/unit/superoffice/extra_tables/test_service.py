"""Unit tests for ExtraTableService and PII sanitization."""

import pytest

from platform_security.sanitization import RecursiveOutputSanitizer
from so_mcp.extra_tables.contracts import (
    ExtraFieldDefinitionDTO,
    ExtraTableDetailSchemaDTO,
    ExtraTableQueryCriteriaDTO,
    SuperOfficeInvalidExtraTableError,
)
from so_mcp.extra_tables.repository import FakeExtraTableRepository
from so_mcp.extra_tables.service import ExtraTableService


@pytest.fixture
def sample_service() -> ExtraTableService:
    schema = ExtraTableDetailSchemaDTO(
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
                field_name="x_email",
                display_name="Contact Email",
                type_code=10,
                type_name="string",
            ),
            ExtraFieldDefinitionDTO(
                id=3,
                extra_table_id=1,
                field_name="x_brand",
                display_name="Brand",
                type_code=10,
                type_name="string",
            ),
            ExtraFieldDefinitionDTO(
                id=4,
                extra_table_id=1,
                field_name="x_auth_token",
                display_name="Token",
                type_code=10,
                type_name="string",
            ),
        ),
    )

    rows = [
        {
            "id": 101,
            "x_msisdn": "+46701234567",
            "x_email": "customer@telco.se",
            "x_brand": "MainBrand",
            "x_auth_token": "secret_token_1234567890",
        },
        {
            "id": 102,
            "x_msisdn": "0739998877",
            "x_email": "support@telco.se",
            "x_brand": "BudgetBrand",
            "x_auth_token": "secret_token_9876543210",
        },
    ]

    repo = FakeExtraTableRepository(
        tables={"y_subscription": schema},
        rows_by_table={"y_subscription": rows},
    )

    return ExtraTableService(repository=repo, sanitizer=RecursiveOutputSanitizer())


@pytest.mark.asyncio
async def test_service_list_and_get_schema(sample_service: ExtraTableService) -> None:
    tables = await sample_service.list_extra_tables()
    assert len(tables) == 1
    assert tables[0].table_name == "y_subscription"

    schema = await sample_service.get_extra_table_schema("y_subscription")
    assert schema.table_name == "y_subscription"
    assert len(schema.fields) == 4


@pytest.mark.asyncio
async def test_service_get_schema_unknown_table_raises(sample_service: ExtraTableService) -> None:
    with pytest.raises(SuperOfficeInvalidExtraTableError):
        await sample_service.get_extra_table_schema("y_nonexistent")


@pytest.mark.asyncio
async def test_service_query_sanitizes_pii_and_secrets(sample_service: ExtraTableService) -> None:
    criteria = ExtraTableQueryCriteriaDTO(
        table_name="y_subscription",
        limit=5,
    )
    result = await sample_service.query_extra_table(criteria)

    assert result.total_rows_returned == 2
    row1 = result.rows[0]

    # Non-sensitive text preserved
    assert row1["id"] == 101
    assert row1["x_brand"] == "MainBrand"

    # Phone numbers redacted
    assert "[REDACTED_PHONE]" in row1["x_msisdn"]
    assert "+46701234567" not in row1["x_msisdn"]

    # Emails redacted
    assert "[REDACTED_EMAIL]" in row1["x_email"]
    assert "customer@telco.se" not in row1["x_email"]

    # Sensitive token / secret key redacted
    assert row1["x_auth_token"] == "[REDACTED_SECRET]"
