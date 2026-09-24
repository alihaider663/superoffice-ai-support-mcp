"""Filesystem writer for mirrored SuperOffice scripts, screens, and schema configurations."""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from so_mcp.sync.contracts import (
    ExtraTableSchemaDTO,
    ScreenRecordDTO,
    ScriptRecordDTO,
    SyncManifestDTO,
    SyncManifestEntryDTO,
)
from so_mcp.sync.sanitizer import (
    PathTraversalSecurityError,
    build_safe_target_path,
    sanitize_filename,
)
from so_mcp.sync.secret_scanner import scan_script_for_secrets

logger = logging.getLogger(__name__)


class CodebaseWriterError(Exception):
    """Raised when writing to local filesystem fails."""


class SuperOfficeCodebaseWriter:
    """Safely writes extracted scripts, screens, and schema definitions to local filesystem."""

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir.resolve()

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    def ensure_directories(self) -> None:
        """Create base directory and primary subdirectories if they do not exist."""
        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            (self._output_dir / "crmscripts").mkdir(exist_ok=True)
            (self._output_dir / "screens").mkdir(exist_ok=True)
            (self._output_dir / "schema").mkdir(exist_ok=True)
            (self._output_dir / "config").mkdir(exist_ok=True)
        except OSError as exc:
            msg = f"Failed to create output directory {self._output_dir}: {exc}"
            raise CodebaseWriterError(msg) from exc

    def write_scripts(
        self, scripts: list[ScriptRecordDTO], *, dry_run: bool = False
    ) -> list[SyncManifestEntryDTO]:
        """Write all scripts into the crmscripts/ hierarchy using real script names.

        Handles path traversal security and same-folder name collisions.
        """
        crmscripts_root = self._output_dir / "crmscripts"
        entries: list[SyncManifestEntryDTO] = []
        seen_paths: dict[Path, int] = {}

        for script in scripts:
            # Reconstruct relative folder hierarchy segments (e.g. ['Scripts', 'Tickets'])
            raw_segments = [s for s in script.hierarchy_path.replace("\\", "/").split("/") if s]
            if not raw_segments:
                raw_segments = ["Scripts"]

            safe_name = sanitize_filename(script.name, fallback=f"script_{script.id}")
            clean_filename = f"{safe_name}.crmscript"

            try:
                target_file = build_safe_target_path(crmscripts_root, raw_segments, clean_filename)
            except PathTraversalSecurityError as exc:
                logger.error("Skipping script ID %d: %s", script.id, exc)
                continue

            # Same-folder collision handling
            if target_file in seen_paths:
                clean_filename = f"{safe_name}_id{script.id}.crmscript"
                target_file = build_safe_target_path(crmscripts_root, raw_segments, clean_filename)

            seen_paths[target_file] = script.id

            content_bytes = script.body.encode("utf-8")
            sha256_hash = hashlib.sha256(content_bytes).hexdigest()
            size_bytes = len(content_bytes)

            # Security scan for secrets
            warnings = scan_script_for_secrets(script.body)

            if not dry_run:
                try:
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    target_file.write_bytes(content_bytes)
                except OSError as exc:
                    msg = f"Failed to write script {target_file}: {exc}"
                    raise CodebaseWriterError(msg) from exc

            rel_path = target_file.relative_to(self._output_dir).as_posix()
            entries.append(
                SyncManifestEntryDTO(
                    entity_type="script",
                    entity_id=script.id,
                    name=script.name,
                    relative_path=rel_path,
                    sha256=sha256_hash,
                    size_bytes=size_bytes,
                    updated=script.updated or None,
                    warnings=warnings,
                )
            )

        return entries

    def _write_single_screen_script(
        self,
        screens_root: Path,
        folder_name: str,
        subdirs: list[str],
        filename: str,
        *,
        code: str,
        script_id: int,
        script_name: str,
        dry_run: bool,
    ) -> SyncManifestEntryDTO | None:
        if not code or not code.strip():
            return None
        target = build_safe_target_path(screens_root, [folder_name, *subdirs], filename)
        c_bytes = code.encode("utf-8")
        sha = hashlib.sha256(c_bytes).hexdigest()
        warns = scan_script_for_secrets(code)

        if not dry_run:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(c_bytes)
            except OSError as exc:
                raise CodebaseWriterError(f"Failed to write screen script {target}: {exc}") from exc

        r_path = target.relative_to(self._output_dir).as_posix()
        return SyncManifestEntryDTO(
            entity_type="screen_script",
            entity_id=script_id,
            name=script_name,
            relative_path=r_path,
            sha256=sha,
            size_bytes=len(c_bytes),
            warnings=warns,
        )

    def _write_screen_actions(
        self,
        screens_root: Path,
        folder_name: str,
        screen: ScreenRecordDTO,
        *,
        dry_run: bool,
    ) -> list[SyncManifestEntryDTO]:
        entries: list[SyncManifestEntryDTO] = []
        seen_action_files: dict[str, int] = {}
        for action in screen.actions:
            aid = action.get("id") or 0
            btn = sanitize_filename(str(action.get("button") or f"action_{aid}"))
            fn = f"{btn}.crmscript"
            if fn in seen_action_files and seen_action_files[fn] != aid:
                fn = f"{btn}_id{aid}.crmscript"
            seen_action_files[fn] = aid
            entry = self._write_single_screen_script(
                screens_root,
                folder_name,
                ["actions"],
                fn,
                code=str(action.get("ejscript_body") or ""),
                script_id=aid,
                script_name=f"{screen.name}/actions/{btn}",
                dry_run=dry_run,
            )
            if entry is not None:
                entries.append(entry)
        return entries

    def _write_screen_elements(
        self,
        screens_root: Path,
        folder_name: str,
        screen: ScreenRecordDTO,
        *,
        dry_run: bool,
    ) -> list[SyncManifestEntryDTO]:
        entries: list[SyncManifestEntryDTO] = []
        seen_elem_files: dict[str, int] = {}
        for elem in screen.elements:
            eid = elem.get("id") or 0
            ename = sanitize_filename(str(elem.get("name") or f"element_{eid}"))
            fn = f"{ename}.crmscript"
            if fn in seen_elem_files and seen_elem_files[fn] != eid:
                fn = f"{ename}_id{eid}.crmscript"
            seen_elem_files[fn] = eid
            entry = self._write_single_screen_script(
                screens_root,
                folder_name,
                ["elements"],
                fn,
                code=str(elem.get("creation_script") or ""),
                script_id=eid,
                script_name=f"{screen.name}/elements/{ename}",
                dry_run=dry_run,
            )
            if entry is not None:
                entries.append(entry)
        return entries

    def _write_screen_dir(
        self,
        screens_root: Path,
        screen: ScreenRecordDTO,
        seen_screen_folders: dict[str, int],
        *,
        dry_run: bool,
    ) -> list[SyncManifestEntryDTO]:
        entries: list[SyncManifestEntryDTO] = []
        safe_name = sanitize_filename(screen.name or f"screen_{screen.id}")
        if safe_name in seen_screen_folders and seen_screen_folders[safe_name] != screen.id:
            folder_name = f"{safe_name}_id{screen.id}"
        else:
            folder_name = safe_name
        seen_screen_folders[folder_name] = screen.id

        scripts_to_write = [
            ("load_script.crmscript", screen.load_script_body, "load_script"),
            ("load_post_cgi.crmscript", screen.load_post_cgi_script_body, "load_post_cgi"),
            ("load_final.crmscript", screen.load_final_script_body, "load_final"),
            ("creation_script.crmscript", screen.creation_script, "creation_script"),
        ]
        for filename, code, label in scripts_to_write:
            e = self._write_single_screen_script(
                screens_root,
                folder_name,
                [],
                filename,
                code=code,
                script_id=screen.id,
                script_name=f"{screen.name}/{label}",
                dry_run=dry_run,
            )
            if e is not None:
                entries.append(e)

        entries.extend(
            self._write_screen_actions(screens_root, folder_name, screen, dry_run=dry_run)
        )
        entries.extend(
            self._write_screen_elements(screens_root, folder_name, screen, dry_run=dry_run)
        )

        screen_meta = screen.data or {
            "id": screen.id,
            "name": screen.name,
            "description": screen.description,
            "id_string": screen.id_string,
            "screen_key": screen.screen_key,
            "actions": screen.actions,
            "elements": screen.elements,
        }
        target_meta = build_safe_target_path(screens_root, [folder_name], "screen.json")
        meta_bytes = json.dumps(screen_meta, indent=2, ensure_ascii=False).encode("utf-8")
        if not dry_run:
            try:
                target_meta.parent.mkdir(parents=True, exist_ok=True)
                target_meta.write_bytes(meta_bytes)
            except OSError as exc:
                raise CodebaseWriterError(
                    f"Failed to write screen metadata {target_meta}: {exc}"
                ) from exc

        return entries

    def write_screens(
        self, screens: list[ScreenRecordDTO], *, dry_run: bool = False
    ) -> list[SyncManifestEntryDTO]:
        """Serialize screen definitions, scripts, actions, and elements into screens/."""
        screens_root = self._output_dir / "screens"
        entries: list[SyncManifestEntryDTO] = []
        seen_screen_folders: dict[str, int] = {}
        all_screen_defs: list[dict[str, Any]] = []
        all_actions: list[dict[str, Any]] = []
        all_elements: list[dict[str, Any]] = []

        for s in screens:
            all_screen_defs.append(s.data or {"id": s.id, "name": s.name})
            all_actions.extend(s.actions)
            all_elements.extend(s.elements)
            entries.extend(
                self._write_screen_dir(screens_root, s, seen_screen_folders, dry_run=dry_run)
            )

        root_tables = [
            ("screen_definition.json", all_screen_defs),
            ("screen_actions.json", all_actions),
            ("screen_elements.json", all_elements),
        ]
        for fname, table_records in root_tables:
            if not table_records:
                continue
            target_file = build_safe_target_path(screens_root, [], fname)
            content_bytes = json.dumps(table_records, indent=2, ensure_ascii=False).encode("utf-8")
            sha256_hash = hashlib.sha256(content_bytes).hexdigest()

            if not dry_run:
                try:
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    target_file.write_bytes(content_bytes)
                except OSError as exc:
                    raise CodebaseWriterError(
                        f"Failed to write screen file {target_file}: {exc}"
                    ) from exc

            rel_path = target_file.relative_to(self._output_dir).as_posix()
            entries.append(
                SyncManifestEntryDTO(
                    entity_type="screen",
                    entity_id=0,
                    name=fname.replace(".json", ""),
                    relative_path=rel_path,
                    sha256=sha256_hash,
                    size_bytes=len(content_bytes),
                    warnings=[],
                )
            )

        return entries

    def write_schema(
        self, extra_tables: list[ExtraTableSchemaDTO], *, dry_run: bool = False
    ) -> list[SyncManifestEntryDTO]:
        """Serialize custom extra tables and extra fields metadata into schema/."""
        schema_root = self._output_dir / "schema"
        entries: list[SyncManifestEntryDTO] = []

        tables_data = [t.model_dump() for t in extra_tables]
        target_file = build_safe_target_path(schema_root, [], "extra_tables.json")

        content_str = json.dumps(tables_data, indent=2, ensure_ascii=False)
        content_bytes = content_str.encode("utf-8")
        sha256_hash = hashlib.sha256(content_bytes).hexdigest()

        if not dry_run:
            try:
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_bytes(content_bytes)
            except OSError as exc:
                msg = f"Failed to write schema file {target_file}: {exc}"
                raise CodebaseWriterError(msg) from exc

        rel_path = target_file.relative_to(self._output_dir).as_posix()
        entries.append(
            SyncManifestEntryDTO(
                entity_type="schema",
                entity_id=0,
                name="extra_tables",
                relative_path=rel_path,
                sha256=sha256_hash,
                size_bytes=len(content_bytes),
                warnings=[],
            )
        )

        return entries

    def write_configs(
        self, configs: dict[str, list[dict[str, Any]]], *, dry_run: bool = False
    ) -> list[SyncManifestEntryDTO]:
        """Serialize configuration dictionaries into config/."""
        config_root = self._output_dir / "config"
        entries: list[SyncManifestEntryDTO] = []

        for config_name, records in configs.items():
            if not records:
                continue
            filename = f"{sanitize_filename(config_name)}.json"
            target_file = build_safe_target_path(config_root, [], filename)

            content_str = json.dumps(records, indent=2, ensure_ascii=False)
            content_bytes = content_str.encode("utf-8")
            sha256_hash = hashlib.sha256(content_bytes).hexdigest()

            if not dry_run:
                try:
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    target_file.write_bytes(content_bytes)
                except OSError as exc:
                    msg = f"Failed to write config file {target_file}: {exc}"
                    raise CodebaseWriterError(msg) from exc

            rel_path = target_file.relative_to(self._output_dir).as_posix()
            entries.append(
                SyncManifestEntryDTO(
                    entity_type="config",
                    entity_id=0,
                    name=config_name,
                    relative_path=rel_path,
                    sha256=sha256_hash,
                    size_bytes=len(content_bytes),
                    warnings=[],
                )
            )

        return entries

    def write_manifest(self, manifest: SyncManifestDTO, *, dry_run: bool = False) -> Path:
        """Write the master manifest.json at the output directory root."""
        manifest_file = self._output_dir / "manifest.json"
        if not dry_run:
            manifest_json = manifest.model_dump_json(indent=2)
            try:
                manifest_file.write_text(manifest_json, encoding="utf-8")
            except OSError as exc:
                msg = f"Failed to write manifest {manifest_file}: {exc}"
                raise CodebaseWriterError(msg) from exc
        return manifest_file
