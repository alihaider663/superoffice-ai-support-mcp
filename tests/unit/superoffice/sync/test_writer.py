"""Unit tests for SuperOffice codebase writer and manifest generation."""

import json
from pathlib import Path

from so_mcp.sync.contracts import (
    ExtraTableSchemaDTO,
    ScreenRecordDTO,
    ScriptRecordDTO,
    SyncManifestDTO,
)
from so_mcp.sync.writer import SuperOfficeCodebaseWriter


def test_writer_write_scripts(tmp_path: Path) -> None:
    writer = SuperOfficeCodebaseWriter(tmp_path)
    writer.ensure_directories()

    scripts = [
        ScriptRecordDTO(
            id=1,
            name="global",
            body="print('hello');",
            hierarchy_path="Scripts/Core",
        ),
        ScriptRecordDTO(
            id=2,
            name="ticket_after_save",
            body="String pwd = 'admin123'; // test password",
            hierarchy_path="Scripts/Tickets",
        ),
        ScriptRecordDTO(
            id=3,
            name="global",  # Collision in Scripts/Core
            body="print('duplicate global');",
            hierarchy_path="Scripts/Core",
        ),
    ]

    entries = writer.write_scripts(scripts, dry_run=False)

    assert len(entries) == 3

    # Script 1
    s1_file = tmp_path / "crmscripts" / "Scripts" / "Core" / "global.crmscript"
    assert s1_file.exists()
    assert s1_file.read_text(encoding="utf-8") == "print('hello');"

    # Script 2 with warning
    s2_file = tmp_path / "crmscripts" / "Scripts" / "Tickets" / "ticket_after_save.crmscript"
    assert s2_file.exists()
    assert len(entries[1].warnings) == 1

    # Script 3 collision disambiguation
    s3_file = tmp_path / "crmscripts" / "Scripts" / "Core" / "global_id3.crmscript"
    assert s3_file.exists()
    assert s3_file.read_text(encoding="utf-8") == "print('duplicate global');"


def test_writer_dry_run_creates_no_files(tmp_path: Path) -> None:
    writer = SuperOfficeCodebaseWriter(tmp_path)
    writer.ensure_directories()

    scripts = [
        ScriptRecordDTO(
            id=10,
            name="dry_test",
            body="print('dry');",
            hierarchy_path="Scripts",
        )
    ]

    entries = writer.write_scripts(scripts, dry_run=True)
    assert len(entries) == 1

    target_file = tmp_path / "crmscripts" / "Scripts" / "dry_test.crmscript"
    assert not target_file.exists()


def test_writer_screens_and_schema(tmp_path: Path) -> None:
    writer = SuperOfficeCodebaseWriter(tmp_path)
    writer.ensure_directories()

    screens = [
        ScreenRecordDTO(
            id=1,
            name="main_ticket_screen",
            table_name="screen_definition",
            data={"id": 1, "name": "main"},
        )
    ]
    schemas = [
        ExtraTableSchemaDTO(
            id=1,
            table_name="y_custom",
            fields=[{"id": 1, "field_name": "f1"}],
        )
    ]

    writer.write_screens(screens, dry_run=False)
    writer.write_schema(schemas, dry_run=False)

    screen_file = tmp_path / "screens" / "screen_definition.json"
    schema_file = tmp_path / "schema" / "extra_tables.json"

    assert screen_file.exists()
    assert schema_file.exists()

    schema_data = json.loads(schema_file.read_text(encoding="utf-8"))
    assert schema_data[0]["table_name"] == "y_custom"


def test_writer_manifest(tmp_path: Path) -> None:
    writer = SuperOfficeCodebaseWriter(tmp_path)
    writer.ensure_directories()

    manifest = SyncManifestDTO(
        generated_at="2026-09-23T12:00:00Z",
        source_mode="http",
        target_dir=str(tmp_path),
        total_scripts=1,
        total_screens=0,
        total_extra_tables=0,
    )

    manifest_file = writer.write_manifest(manifest, dry_run=False)
    assert manifest_file.exists()
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert data["source_mode"] == "http"


def test_writer_screen_scripts_and_actions(tmp_path: Path) -> None:
    """Screen-level scripts, button action scripts, and element scripts are written to disk."""
    writer = SuperOfficeCodebaseWriter(tmp_path)
    writer.ensure_directories()

    screen = ScreenRecordDTO(
        id=13,
        name="Create case",
        table_name="screen_definition",
        load_script_body="print('load create case');",
        load_post_cgi_script_body="print('post cgi');",
        creation_script="print('creation script');",
        actions=[
            {
                "id": 101,
                "button": "ok",
                "ejscript_body": "print('ok clicked');",
            },
            {
                "id": 102,
                "button": "cancel",
                "ejscript_body": "print('cancel clicked');",
            },
        ],
        elements=[
            {
                "id": 201,
                "name": "customer",
                "creation_script": "print('render customer');",
            }
        ],
    )

    entries = writer.write_screens([screen], dry_run=False)
    assert len(entries) > 0

    screen_dir = tmp_path / "screens" / "Create case"
    load_file = screen_dir / "load_script.crmscript"
    assert load_file.exists()
    assert load_file.read_text(encoding="utf-8") == "print('load create case');"

    assert (screen_dir / "load_post_cgi.crmscript").exists()
    assert (screen_dir / "creation_script.crmscript").exists()

    # Button action scripts
    ok_file = screen_dir / "actions" / "ok.crmscript"
    assert ok_file.exists()
    assert ok_file.read_text(encoding="utf-8") == "print('ok clicked');"
    assert (screen_dir / "actions" / "cancel.crmscript").exists()

    # Element creation scripts
    elem_file = screen_dir / "elements" / "customer.crmscript"
    assert elem_file.exists()
    assert elem_file.read_text(encoding="utf-8") == "print('render customer');"

    # Screen metadata JSON
    assert (screen_dir / "screen.json").exists()

    # Master table JSON in screens root
    assert (tmp_path / "screens" / "screen_definition.json").exists()
    assert (tmp_path / "screens" / "screen_actions.json").exists()
    assert (tmp_path / "screens" / "screen_elements.json").exists()
