"""Unit tests for SuperOffice HTTP codebase extractor."""

import json

import httpx
import pytest

from so_mcp.sync.http_extractor import SuperOfficeHttpExtractor


@pytest.mark.asyncio
async def test_http_extractor_fetch_scripts() -> None:
    mock_payload = {
        "ejscript": [
            {
                "ejscript.id": "101",
                "ejscript.name": "global",
                "ejscript.body": "print('hello');",
                "ejscript.hierarchy_id": "5",
                "ejscript.updated": "2026-01-01 12:00:00",
            },
            {
                "id": "102",
                "name": "ticket_hook",
                "body": "print('ticket');",
                "hierarchy_id": None,
                "updated": "2026-01-02 12:00:00",
            },
        ]
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=json.dumps(mock_payload))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        extractor = SuperOfficeHttpExtractor(
            base_url="https://testserver/SuperOffice",
            endpoint_path="scripts/customer.fcgi",
            username="admin",
            password="pwd",
            client=client,
        )

        hierarchy_map = {5: "Scripts/Core"}
        scripts = await extractor.fetch_scripts(hierarchy_map)

        assert len(scripts) == 2
        assert scripts[0].id == 101
        assert scripts[0].name == "global"
        assert scripts[0].hierarchy_path == "Scripts/Core"

        assert scripts[1].id == 102
        assert scripts[1].name == "ticket_hook"
        assert scripts[1].hierarchy_path == "Scripts"


@pytest.mark.asyncio
async def test_http_extractor_hierarchy_unsupported_fallback() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        # SuperOffice throwing "Unsupported table"
        return httpx.Response(500, text="Unsupported table")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        extractor = SuperOfficeHttpExtractor(
            base_url="https://testserver/SuperOffice",
            endpoint_path="scripts/customer.fcgi",
            username="admin",
            password="pwd",
            client=client,
        )

        h_map = await extractor.fetch_hierarchy_tree()
        assert h_map == {}


@pytest.mark.asyncio
async def test_http_extractor_fetch_extra_tables() -> None:
    table_payload = {"extra_tables": [{"id": 1, "table_name": "y_customlog"}]}
    field_payload = {
        "extra_fields": [
            {"id": 10, "extra_table_id": 1, "field_name": "log_text", "type": 1},
            {"id": 11, "extra_table_id": 1, "field_name": "timestamp", "type": 2},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        table_param = request.url.params.get("table")
        if table_param == "extra_tables":
            return httpx.Response(200, text=json.dumps(table_payload))
        elif table_param == "extra_fields":
            return httpx.Response(200, text=json.dumps(field_payload))
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        extractor = SuperOfficeHttpExtractor(
            base_url="https://testserver/SuperOffice",
            endpoint_path="scripts/customer.fcgi",
            username="admin",
            password="pwd",
            client=client,
        )

        schemas = await extractor.fetch_extra_tables()
        assert len(schemas) == 1
        assert schemas[0].id == 1
        assert schemas[0].table_name == "y_customlog"
        assert len(schemas[0].fields) == 2
