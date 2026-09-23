"""Unit tests for high-level SuperOffice codebase synchronization service."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from so_mcp.settings import SuperOfficeCodebaseSyncSettings
from so_mcp.sync.contracts import ExtraTableSchemaDTO, ScreenRecordDTO, ScriptRecordDTO
from so_mcp.sync.service import SuperOfficeCodebaseSyncService
from so_mcp.sync.writer import SuperOfficeCodebaseWriter


@pytest.mark.asyncio
async def test_service_sync_http_success(tmp_path: Path) -> None:
    settings = SuperOfficeCodebaseSyncSettings(
        codebase_local_path=tmp_path,
        sync_mode="http",
    )

    mock_extractor = AsyncMock()
    mock_extractor.fetch_hierarchy_tree.return_value = {1: "Scripts/Sales"}
    mock_extractor.fetch_scripts.return_value = [
        ScriptRecordDTO(
            id=1, name="quote_calc", body="print('calc');", hierarchy_path="Scripts/Sales"
        )
    ]
    mock_extractor.fetch_screens.return_value = [
        ScreenRecordDTO(id=10, name="quote_screen", table_name="screen_definition")
    ]
    mock_extractor.fetch_extra_tables.return_value = [
        ExtraTableSchemaDTO(id=5, table_name="y_quote_extra")
    ]
    mock_extractor.fetch_configs.return_value = {"item_config": [{"id": 1, "name": "cfg1"}]}

    writer = SuperOfficeCodebaseWriter(tmp_path)
    service = SuperOfficeCodebaseSyncService(
        settings=settings,
        writer=writer,
        http_extractor=mock_extractor,
    )

    result = await service.sync(mode="http", dry_run=False)

    assert result.success is True
    manifest = result.manifest
    assert manifest.total_scripts == 1
    assert manifest.total_screens == 1
    assert manifest.total_extra_tables == 1

    # Check files
    script_file = tmp_path / "crmscripts" / "Scripts" / "Sales" / "quote_calc.crmscript"
    assert script_file.exists()
    assert (tmp_path / "manifest.json").exists()


@pytest.mark.asyncio
async def test_service_sync_invalid_mode(tmp_path: Path) -> None:
    settings = SuperOfficeCodebaseSyncSettings(codebase_local_path=tmp_path)
    service = SuperOfficeCodebaseSyncService(settings=settings)

    result = await service.sync(mode="unsupported_mode")
    assert result.success is False
    assert "Invalid sync mode" in (result.error_message or "")
