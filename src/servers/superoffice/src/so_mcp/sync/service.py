"""High-level orchestration service for SuperOffice codebase synchronization."""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from so_mcp.settings import SuperOfficeCodebaseSyncSettings
from so_mcp.sync.contracts import (
    SyncManifestDTO,
    SyncManifestEntryDTO,
    SyncResultDTO,
)
from so_mcp.sync.http_extractor import SuperOfficeHttpExtractor
from so_mcp.sync.mssql_extractor import (
    SuperOfficeMssqlExtractor,
    create_mssql_sync_engine,
)
from so_mcp.sync.writer import SuperOfficeCodebaseWriter

logger = logging.getLogger(__name__)


class SuperOfficeCodebaseSyncService:
    """Orchestrates extraction, scanning, directory mirroring, and manifest creation."""

    def __init__(
        self,
        settings: SuperOfficeCodebaseSyncSettings | None = None,
        *,
        output_dir: Path | None = None,
        writer: SuperOfficeCodebaseWriter | None = None,
        http_extractor: SuperOfficeHttpExtractor | None = None,
        mssql_extractor: Any = None,
    ) -> None:
        self._settings = settings or SuperOfficeCodebaseSyncSettings()
        target_dir = output_dir or self._settings.codebase_local_path
        self._writer = writer or SuperOfficeCodebaseWriter(target_dir)
        self._http_extractor = http_extractor
        self._mssql_extractor = mssql_extractor

    @property
    def output_dir(self) -> Path:
        return self._writer.output_dir

    def _get_http_extractor(self) -> SuperOfficeHttpExtractor:
        if self._http_extractor is not None:
            return self._http_extractor

        return SuperOfficeHttpExtractor(
            base_url=str(self._settings.api_url),
            endpoint_path=self._settings.crmscript_sync_endpoint,
            username=self._settings.username,
            password=self._settings.password.get_secret_value(),
            allow_self_signed_cert=self._settings.allow_self_signed_cert,
            timeout_seconds=float(self._settings.sync_batch_size),
        )

    def _get_mssql_extractor(self) -> Any:
        if self._mssql_extractor is not None:
            return self._mssql_extractor

        engine = create_mssql_sync_engine(
            host=self._settings.mssql_host,
            port=self._settings.mssql_port,
            database=self._settings.mssql_database,
            user=self._settings.mssql_user,
            password=self._settings.mssql_password.get_secret_value(),
            trust_cert=self._settings.mssql_trust_server_certificate,
        )
        self._mssql_extractor = SuperOfficeMssqlExtractor(engine)
        return self._mssql_extractor

    async def _sync_http(
        self,
        allowed: set[str],
        sync_all: bool,
        dry_run: bool,
    ) -> tuple[list[SyncManifestEntryDTO], int, int, int]:
        extractor = self._get_http_extractor()
        entries: list[SyncManifestEntryDTO] = []
        n_scripts, n_screens, n_tables = 0, 0, 0

        if sync_all or "ejscript" in allowed:
            h_map = await extractor.fetch_hierarchy_tree()
            scripts = await extractor.fetch_scripts(h_map)
            n_scripts = len(scripts)
            entries.extend(self._writer.write_scripts(scripts, dry_run=dry_run))

        if sync_all or "screens" in allowed:
            screens = await extractor.fetch_screens()
            n_screens = len(screens)
            entries.extend(self._writer.write_screens(screens, dry_run=dry_run))

        if sync_all or "schema" in allowed:
            tables = await extractor.fetch_extra_tables()
            n_tables = len(tables)
            entries.extend(self._writer.write_schema(tables, dry_run=dry_run))

        if sync_all or "config" in allowed:
            configs = await extractor.fetch_configs()
            entries.extend(self._writer.write_configs(configs, dry_run=dry_run))

        return entries, n_scripts, n_screens, n_tables

    async def _sync_mssql(
        self,
        allowed: set[str],
        sync_all: bool,
        dry_run: bool,
    ) -> tuple[list[SyncManifestEntryDTO], int, int, int]:
        extractor = self._get_mssql_extractor()
        entries: list[SyncManifestEntryDTO] = []
        n_scripts, n_screens, n_tables = 0, 0, 0

        if sync_all or "ejscript" in allowed:
            h_map = await extractor.fetch_hierarchy_tree()
            scripts = await extractor.fetch_scripts(h_map)
            n_scripts = len(scripts)
            entries.extend(self._writer.write_scripts(scripts, dry_run=dry_run))

        if sync_all or "screens" in allowed:
            screens = await extractor.fetch_screens()
            n_screens = len(screens)
            entries.extend(self._writer.write_screens(screens, dry_run=dry_run))

        if sync_all or "schema" in allowed:
            tables = await extractor.fetch_extra_tables()
            n_tables = len(tables)
            entries.extend(self._writer.write_schema(tables, dry_run=dry_run))

        return entries, n_scripts, n_screens, n_tables

    async def sync(
        self,
        *,
        mode: str | None = None,
        tables: list[str] | None = None,
        dry_run: bool = False,
    ) -> SyncResultDTO:
        """Execute synchronization across scripts, screens, and custom schemas."""
        active_mode = (mode or self._settings.sync_mode).lower()
        if active_mode not in ("http", "mssql"):
            return SyncResultDTO(
                success=False,
                manifest=SyncManifestDTO(
                    generated_at=datetime.now(UTC).isoformat(),
                    source_mode=active_mode,
                    target_dir=str(self.output_dir),
                ),
                error_message=f"Invalid sync mode '{active_mode}'. Supported: 'http', 'mssql'.",
            )

        if not dry_run:
            self._writer.ensure_directories()

        allowed = set(tables) if tables else {"all", "ejscript", "screens", "schema", "config"}
        sync_all = "all" in allowed

        try:
            if active_mode == "http":
                entries, n_scripts, n_screens, n_tables = await self._sync_http(
                    allowed, sync_all, dry_run
                )
            else:
                entries, n_scripts, n_screens, n_tables = await self._sync_mssql(
                    allowed, sync_all, dry_run
                )

            manifest = SyncManifestDTO(
                generated_at=datetime.now(UTC).isoformat(),
                source_mode=active_mode,
                target_dir=str(self.output_dir),
                total_scripts=n_scripts,
                total_screens=n_screens,
                total_extra_tables=n_tables,
                entries=entries,
            )

            self._writer.write_manifest(manifest, dry_run=dry_run)
            return SyncResultDTO(success=True, manifest=manifest)

        except Exception as exc:
            logger.exception("Codebase sync failed: %s", exc)
            return SyncResultDTO(
                success=False,
                manifest=SyncManifestDTO(
                    generated_at=datetime.now(UTC).isoformat(),
                    source_mode=active_mode,
                    target_dir=str(self.output_dir),
                    entries=[],
                ),
                error_message=str(exc),
            )
