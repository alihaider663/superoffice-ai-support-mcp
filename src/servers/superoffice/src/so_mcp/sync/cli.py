"""Operator CLI for SuperOffice Codebase Synchronization and Mirroring.

Entrypoint: python -m so_mcp.sync.cli [options]
"""

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from so_mcp.settings import SuperOfficeCodebaseSyncSettings
from so_mcp.sync.service import SuperOfficeCodebaseSyncService

logger = logging.getLogger("so_mcp.sync")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="so-sync",
        description="SuperOffice AI Support — Local Codebase Mirror & Sync Utility",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Local directory path to mirror codebase (overrides SUPEROFFICE_CODEBASE_LOCAL_PATH)",
    )
    parser.add_argument(
        "-m",
        "--mode",
        choices=["http", "mssql"],
        default=None,
        help=(
            "Extraction source mode: 'http' via CRMScript handler, "
            "or 'mssql' via direct database connection"
        ),
    )
    parser.add_argument(
        "-t",
        "--tables",
        type=str,
        default=None,
        help="Comma-separated entities to sync (e.g. 'ejscript,screens,schema', or 'all')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and evaluate without writing any files to disk",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )
    return parser


async def run_sync(args: argparse.Namespace) -> int:
    """Execute synchronization service with parsed arguments."""
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    settings = SuperOfficeCodebaseSyncSettings()
    target_dir = args.output_dir or settings.codebase_local_path

    tables = [t.strip() for t in args.tables.split(",") if t.strip()] if args.tables else None

    print("====================================================================")
    print("  SuperOffice Codebase Synchronization Engine")
    print("====================================================================")
    print(f"  Target Local Path : {target_dir}")
    print(f"  Extraction Mode   : {args.mode or settings.sync_mode}")
    print(f"  Dry Run           : {args.dry_run}")
    print(f"  Selected Tables   : {', '.join(tables) if tables else 'all'}")
    print("====================================================================")
    print("Starting synchronization...")

    service = SuperOfficeCodebaseSyncService(
        settings=settings,
        output_dir=target_dir,
    )

    result = await service.sync(
        mode=args.mode,
        tables=tables,
        dry_run=args.dry_run,
    )

    if not result.success:
        print(f"\n[FAILED] Synchronization FAILED: {result.error_message}", file=sys.stderr)
        return 1

    manifest = result.manifest
    total_warnings = sum(len(e.warnings) for e in manifest.entries)

    print("\n[SUCCESS] Synchronization Complete!")
    print("--------------------------------------------------------------------")
    print(f"  Total Scripts Extracted   : {manifest.total_scripts}")
    print(f"  Total Screens Extracted   : {manifest.total_screens}")
    print(f"  Total Extra Tables Synced : {manifest.total_extra_tables}")
    print(f"  Total Files Manifested    : {len(manifest.entries)}")
    print(f"  Security / Secret Warnings: {total_warnings}")

    if total_warnings > 0:
        print("\n[WARNING] Security Warnings Detected in Script Bodies:")
        for entry in manifest.entries:
            for w in entry.warnings:
                print(f"    - {entry.relative_path}: {w}")

    if args.dry_run:
        print("\n(Dry-run mode: No files were written to disk)")
    else:
        print(f"\nFiles mirrored successfully to: {target_dir}")

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(run_sync(args))


if __name__ == "__main__":
    sys.exit(main())
