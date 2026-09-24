"""Unit tests for LocalCodebaseRepository search, line windowing, and security."""

import json
from pathlib import Path

import pytest

from so_mcp.codebase.contracts import (
    CodebaseFileRequestDTO,
    CodebaseSearchCriteriaDTO,
)
from so_mcp.codebase.repository import LocalCodebaseRepository
from so_mcp.sync.sanitizer import PathTraversalSecurityError


@pytest.fixture
def sample_mirror(tmp_path: Path) -> Path:
    """Populate a temporary mirrored directory mimicking F:\\CodeBase_SuperOffice."""
    crmscripts = tmp_path / "crmscripts" / "Scripts"
    crmscripts.mkdir(parents=True)
    (crmscripts / "soapSubscription.crmscript").write_text(
        '# Script: soapSubscription\nString endpoint = "https://soap.example.com";\nprint("Connecting");\n',
        encoding="utf-8",
    )
    (crmscripts / "global.crmscript").write_text(
        "# Script: global\nBool isGlobal = true;\n",
        encoding="utf-8",
    )

    screen_dir = tmp_path / "screens" / "Create case"
    screen_dir.mkdir(parents=True)
    (screen_dir / "screen.json").write_text(
        json.dumps({"id": 10, "name": "Create case", "title": "Create Case Screen"}),
        encoding="utf-8",
    )
    (screen_dir / "load_script.crmscript").write_text(
        '# Load Script\nprint("Screen loading...");\n',
        encoding="utf-8",
    )

    actions_dir = screen_dir / "actions"
    actions_dir.mkdir()
    (actions_dir / "ok.crmscript").write_text(
        '# OK Action\nprint("Saving ticket...");\n',
        encoding="utf-8",
    )

    elements_dir = screen_dir / "elements"
    elements_dir.mkdir()
    (elements_dir / "customer.crmscript").write_text(
        "# Customer element script\n",
        encoding="utf-8",
    )

    # Add manifest.json
    manifest_data = {
        "sync_timestamp": "2026-09-24T12:00:00Z",
        "entries": [
            {
                "relative_path": "crmscripts/Scripts/soapSubscription.crmscript",
                "file_type": "crmscript",
                "size_bytes": 100,
            },
            {
                "relative_path": "crmscripts/Scripts/global.crmscript",
                "file_type": "crmscript",
                "size_bytes": 50,
            },
            {
                "relative_path": "screens/Create case/load_script.crmscript",
                "file_type": "screen_lifecycle",
                "size_bytes": 60,
            },
            {
                "relative_path": "screens/Create case/actions/ok.crmscript",
                "file_type": "screen_action",
                "size_bytes": 70,
            },
            {
                "relative_path": "screens/Create case/elements/customer.crmscript",
                "file_type": "screen_element",
                "size_bytes": 40,
            },
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")
    return tmp_path


@pytest.mark.asyncio
async def test_search_codebase_finds_keyword(sample_mirror: Path) -> None:
    """search_codebase locates matching scripts by content and path."""
    repo = LocalCodebaseRepository(sample_mirror)
    res = await repo.search_codebase(CodebaseSearchCriteriaDTO(query="soapSubscription"))
    assert res.returned_count == 1
    item = res.items[0]
    assert "soapSubscription.crmscript" in item.relative_path
    assert item.file_type == "crmscript"


@pytest.mark.asyncio
async def test_search_codebase_target_type_filter(sample_mirror: Path) -> None:
    """Target type filters correctly restrict returned entries."""
    repo = LocalCodebaseRepository(sample_mirror)
    res = await repo.search_codebase(
        CodebaseSearchCriteriaDTO(query="Saving ticket", target_type="action")
    )
    assert res.returned_count == 1
    assert "actions/ok.crmscript" in res.items[0].relative_path


@pytest.mark.asyncio
async def test_get_codebase_file_slices_lines(sample_mirror: Path) -> None:
    """get_codebase_file returns requested line range with checksum."""
    repo = LocalCodebaseRepository(sample_mirror)
    req = CodebaseFileRequestDTO(
        relative_path="crmscripts/Scripts/soapSubscription.crmscript",
        start_line=2,
        end_line=2,
    )
    res = await repo.get_codebase_file(req)
    assert res.start_line == 2
    assert res.end_line == 2
    assert res.total_lines == 3
    assert 'String endpoint = "https://soap.example.com";' in res.content
    assert res.sha256 is not None


@pytest.mark.asyncio
async def test_get_codebase_file_clamps_max_window(sample_mirror: Path) -> None:
    """Line window larger than 200 lines is clamped to 200 lines."""
    big_file = sample_mirror / "crmscripts" / "big.crmscript"
    big_file.write_text("\n".join(f"line_{i}" for i in range(1, 301)), encoding="utf-8")

    repo = LocalCodebaseRepository(sample_mirror)
    req = CodebaseFileRequestDTO(
        relative_path="crmscripts/big.crmscript",
        start_line=1,
        end_line=250,
    )
    res = await repo.get_codebase_file(req)
    assert res.start_line == 1
    assert res.end_line == 200
    assert res.is_truncated is True


@pytest.mark.asyncio
async def test_path_traversal_attacks_rejected(sample_mirror: Path) -> None:
    """Parent directory traversal or null bytes raise PathTraversalSecurityError."""
    repo = LocalCodebaseRepository(sample_mirror)

    with pytest.raises(PathTraversalSecurityError):
        await repo.get_codebase_file(CodebaseFileRequestDTO(relative_path="../outside.txt"))

    with pytest.raises(PathTraversalSecurityError):
        await repo.get_codebase_file(CodebaseFileRequestDTO(relative_path="..\\outside.txt"))

    with pytest.raises(PathTraversalSecurityError):
        await repo.get_codebase_file(CodebaseFileRequestDTO(relative_path="crmscripts/\x00secret"))


@pytest.mark.asyncio
async def test_get_screen_details_parses_elements_and_buttons(sample_mirror: Path) -> None:
    """get_screen_details extracts metadata, lifecycle scripts, buttons, and elements."""
    repo = LocalCodebaseRepository(sample_mirror)
    details = await repo.get_screen_details("Create case")
    assert details is not None
    assert details.screen_id == 10
    assert details.screen_name == "Create case"
    assert details.lifecycle_scripts.load_script == "screens/Create case/load_script.crmscript"
    assert len(details.action_buttons) == 1
    assert details.action_buttons[0].name == "ok"
    assert len(details.elements) == 1
    assert details.elements[0].name == "customer"
