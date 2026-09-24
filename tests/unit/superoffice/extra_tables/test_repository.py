"""Unit tests for ExtraTableRepository implementations."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from so_mcp.extra_tables.contracts import (
    ExtraFieldDefinitionDTO,
    ExtraTableDetailSchemaDTO,
    ExtraTableQueryCriteriaDTO,
    SuperOfficeExtraTableQueryError,
)
from so_mcp.extra_tables.repository import (
    FakeExtraTableRepository,
    LocalMirrorExtraTableRepository,
    MssqlExtraTableRepository,
)


@pytest.fixture
def sample_table_schema() -> ExtraTableDetailSchemaDTO:
    return ExtraTableDetailSchemaDTO(
        id=1,
        table_name="y_subscription",
        display_name="Subscription",
        description="Mobile subscriptions",
        fields=(
            ExtraFieldDefinitionDTO(
                id=10,
                extra_table_id=1,
                field_name="x_msisdn",
                display_name="MSISDN",
                type_code=10,
                type_name="string",
            ),
            ExtraFieldDefinitionDTO(
                id=11,
                extra_table_id=1,
                field_name="x_brand",
                display_name="Brand",
                type_code=10,
                type_name="string",
            ),
        ),
    )


@pytest.mark.asyncio
async def test_fake_repository_list_and_get(sample_table_schema: ExtraTableDetailSchemaDTO) -> None:
    repo = FakeExtraTableRepository(tables={"y_subscription": sample_table_schema})

    # List tables
    tables = await repo.list_tables()
    assert len(tables) == 1
    assert tables[0].table_name == "y_subscription"
    assert tables[0].field_count == 2

    # Search filter
    assert len(await repo.list_tables(search="subs")) == 1
    assert len(await repo.list_tables(search="nonexistent")) == 0

    # Get schema
    schema = await repo.get_table_schema("y_subscription")
    assert schema is not None
    assert schema.display_name == "Subscription"

    # Schema with 'subscription' normalized to 'y_subscription'
    assert await repo.get_table_schema("subscription") is not None


@pytest.mark.asyncio
async def test_fake_repository_query(sample_table_schema: ExtraTableDetailSchemaDTO) -> None:
    rows = [
        {"id": 1, "x_msisdn": "12345", "x_brand": "Main"},
        {"id": 2, "x_msisdn": "67890", "x_brand": "Vimla"},
        {"id": 3, "x_msisdn": "54321", "x_brand": "Main"},
    ]
    repo = FakeExtraTableRepository(
        tables={"y_subscription": sample_table_schema},
        rows_by_table={"y_subscription": rows},
    )

    # 1. Simple query
    criteria = ExtraTableQueryCriteriaDTO(table_name="y_subscription", limit=10)
    result = await repo.query_table(criteria, sample_table_schema)
    assert result.total_rows_returned == 3

    # 2. Filter query
    filter_criteria = ExtraTableQueryCriteriaDTO(
        table_name="y_subscription",
        filters={"x_brand": "Main"},
        limit=10,
    )
    filtered_result = await repo.query_table(filter_criteria, sample_table_schema)
    assert filtered_result.total_rows_returned == 2
    assert all(r["x_brand"] == "Main" for r in filtered_result.rows)

    # 3. Paging query
    page_criteria = ExtraTableQueryCriteriaDTO(
        table_name="y_subscription",
        limit=2,
        offset=1,
    )
    paged_result = await repo.query_table(page_criteria, sample_table_schema)
    assert paged_result.total_rows_returned == 2
    assert paged_result.rows[0]["id"] == 2


@pytest.mark.asyncio
async def test_local_mirror_repository(tmp_path: Path) -> None:
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir(parents=True)
    schema_file = schema_dir / "extra_tables.json"

    dummy_data = [
        {
            "id": 5,
            "table_name": "y_custom_contract",
            "name": "Custom Contract",
            "description": "Contracts",
            "fields": [
                {
                    "id": 100,
                    "field_name": "x_contract_num",
                    "name": "Contract Number",
                    "type": 1,
                    "default_value": "0",
                    "description": "Num",
                }
            ],
        }
    ]
    schema_file.write_text(json.dumps(dummy_data), encoding="utf-8")

    repo = LocalMirrorExtraTableRepository(tmp_path)
    tables = await repo.list_tables()
    assert len(tables) == 1
    assert tables[0].table_name == "y_custom_contract"

    schema = await repo.get_table_schema("y_custom_contract")
    assert schema is not None
    assert schema.fields[0].field_name == "x_contract_num"
    assert schema.fields[0].type_name == "integer"

    with pytest.raises(SuperOfficeExtraTableQueryError):
        await repo.query_table(
            ExtraTableQueryCriteriaDTO(table_name="y_custom_contract"),
            schema,
        )


@pytest.mark.asyncio
async def test_mssql_repository_catalog_and_query(
    sample_table_schema: ExtraTableDetailSchemaDTO,
) -> None:
    mock_engine = MagicMock()
    mock_conn = AsyncMock()

    # Mock catalog rows
    t_result = MagicMock()
    t_result.fetchall.return_value = [(1, "y_subscription", "Subscription", "Mobile subscriptions")]

    f_result = MagicMock()
    f_result.fetchall.return_value = [
        (10, 1, "x_msisdn", "MSISDN", 10, "", "Phone"),
        (11, 1, "x_brand", "Brand", 10, "", "Brand name"),
    ]

    # Mock query rows
    q_result = MagicMock()
    q_result.fetchall.return_value = [(101, "0701234567", "Main")]

    # Set up execute sequence
    mock_conn.execute.side_effect = [t_result, f_result, q_result]
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    repo = MssqlExtraTableRepository(mock_engine)

    # 1. Fetch catalog
    catalog = await repo.get_table_catalog()
    assert "y_subscription" in catalog
    assert len(catalog["y_subscription"].fields) == 2

    # 2. Query table
    criteria = ExtraTableQueryCriteriaDTO(
        table_name="y_subscription",
        fields=("id", "x_msisdn", "x_brand"),
        filters={"x_brand": "Main"},
        limit=10,
        offset=0,
    )
    result = await repo.query_table(criteria, sample_table_schema)

    assert result.total_rows_returned == 1
    assert result.rows[0]["id"] == 101
    assert result.rows[0]["x_msisdn"] == "0701234567"
    assert result.rows[0]["x_brand"] == "Main"
