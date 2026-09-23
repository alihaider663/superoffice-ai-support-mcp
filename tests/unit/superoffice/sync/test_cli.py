"""Unit tests for codebase sync CLI parser and execution."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

from so_mcp.sync.cli import build_parser, main
from so_mcp.sync.contracts import SyncManifestDTO, SyncResultDTO


def test_cli_parser_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args([])
    assert args.output_dir is None
    assert args.mode is None
    assert args.tables is None
    assert args.dry_run is False
    assert args.verbose is False


def test_cli_parser_custom_args(tmp_path: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "-o",
            str(tmp_path),
            "-m",
            "http",
            "-t",
            "ejscript,screens",
            "--dry-run",
            "-v",
        ]
    )
    assert args.output_dir == tmp_path
    assert args.mode == "http"
    assert args.tables == "ejscript,screens"
    assert args.dry_run is True
    assert args.verbose is True


@patch("so_mcp.sync.cli.SuperOfficeCodebaseSyncService")
def test_cli_main_success(mock_service_cls, tmp_path: Path) -> None:
    mock_instance = mock_service_cls.return_value
    manifest = SyncManifestDTO(
        generated_at="2026-09-23T12:00:00Z",
        source_mode="http",
        target_dir=str(tmp_path),
        total_scripts=5,
        total_screens=2,
        total_extra_tables=1,
    )
    mock_instance.sync = AsyncMock(return_value=SyncResultDTO(success=True, manifest=manifest))

    exit_code = main(["-o", str(tmp_path), "--dry-run"])
    assert exit_code == 0
    mock_instance.sync.assert_called_once()
