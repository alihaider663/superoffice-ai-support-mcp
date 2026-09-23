"""Unit tests for codebase sync filesystem sanitizer and path traversal guards."""

from pathlib import Path

from so_mcp.sync.sanitizer import (
    build_safe_target_path,
    sanitize_filename,
    sanitize_path_segment,
)


def test_sanitize_filename_basic() -> None:
    assert sanitize_filename("global") == "global"
    assert sanitize_filename("ticket_after_save.crmscript") == "ticket_after_save.crmscript"


def test_sanitize_filename_illegal_chars() -> None:
    assert sanitize_filename("script:name*with?chars") == "script_name_with_chars"
    assert sanitize_filename("a/b\\c<d>e|f") == "a_b_c_d_e_f"


def test_sanitize_filename_windows_reserved() -> None:
    assert sanitize_filename("CON") == "_CON"
    assert sanitize_filename("con.crmscript") == "_con.crmscript"
    assert sanitize_filename("NUL") == "_NUL"
    assert sanitize_filename("com1") == "_com1"


def test_sanitize_filename_dots_and_spaces() -> None:
    assert sanitize_filename("   ") == "unnamed"
    assert sanitize_filename("...") == "unnamed"
    assert sanitize_filename("  script_name  ") == "script_name"


def test_sanitize_path_segment() -> None:
    assert sanitize_path_segment("Tickets/Service") == "Tickets_Service"
    assert sanitize_path_segment("") == "general"


def test_build_safe_target_path_valid(tmp_path: Path) -> None:
    base = tmp_path / "target"
    base.mkdir()

    target = build_safe_target_path(base, ["Scripts", "Tickets"], "global.crmscript")
    assert target.name == "global.crmscript"
    assert target.resolve().is_relative_to(base.resolve())


def test_build_safe_target_path_traversal_blocked(tmp_path: Path) -> None:
    base = tmp_path / "target"
    base.mkdir()

    # Sanitizer drops ".." segments, ensuring target remains inside base
    target = build_safe_target_path(base, ["..", "..", "etc"], "passwd.crmscript")
    assert target.resolve().is_relative_to(base.resolve())
