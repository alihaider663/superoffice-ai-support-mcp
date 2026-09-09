"""Unit tests for the Knowledge Ingestion CLI.

Gate 7D.5E: CLI contract validation, routing, security rejection, and dry-run/ingest exit codes.
"""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from kb_mcp.contracts.cli import CliExitCode
from kb_mcp.contracts.constants import MAX_SOURCE_FILE_BYTES
from kb_mcp.contracts.errors import (
    EmbeddingInferenceError,
    KnowledgePersistenceError,
    KnowledgeRuntimeInitializationError,
)
from kb_mcp.contracts.ingestion import (
    IngestionResultDTO,
    IngestionStatus,
)
from kb_mcp.ingestion.cli import main
from kb_mcp.ingestion.service import KnowledgeAdmissionService

# Sample valid payloads
_SAMPLE_VALID_MD = """# Safe Architecture Overview
This document describes the safe architecture of the platform.
It contains only approved technical documentation.
"""

_SAMPLE_VALID_TXT = """Safe Plain Text SOP
Step 1: Check the monitoring dashboard.
Step 2: Follow standard escalation procedures.
"""

_SAMPLE_VALID_RUNBOOK = {
    "runbook_id": "rb_auth_recovery",
    "title": "Auth Recovery Runbook",
    "problem_description": "Handles authentication service token failures.",
    "diagnostic_steps": ["Check token signing logs.", "Verify certificate validity."],
    "remediation_steps": ["Rotate signing keys.", "Restart auth service."],
    "source_reference": "runbook://rb-auth-recovery-v1",
    "product": "SuperOffice Core",
    "verified_version": "1.0",
}

_SAMPLE_VALID_KNOWN_ISSUE = {
    "issue_id": "ki_saml_redirect_loop",
    "title": "SAML Redirect Loop",
    "symptom_summary": "Users experience endless redirect during SAML SSO.",
    "root_cause_summary": "Clock skew between IdP and Service Provider exceeds 5 minutes.",
    "workaround": "Synchronize NTP clocks on identity hosts.",
    "source_reference": "known-issue://ki-saml-redirect-loop-v1",
    "permanent_fix_reference": "https://github.com/org/repo/pull/123",
    "affected_products": ["SuperOffice Web"],
    "affected_versions": ["1.0", "1.1"],
    "category": "Authentication",
}


def test_cli_without_arguments_returns_validation_error() -> None:
    """Invoking CLI without arguments should return VALIDATION_ERROR (2)."""
    assert main([]) == CliExitCode.VALIDATION_ERROR


def test_cli_unsupported_subcommand_returns_validation_error() -> None:
    """Invoking CLI with an unknown command should return VALIDATION_ERROR (2)."""
    assert main(["foobar"]) == CliExitCode.VALIDATION_ERROR


def test_cli_missing_type_returns_validation_error(tmp_path: Path) -> None:
    """Omitting mandatory --type must return VALIDATION_ERROR (2)."""
    f = tmp_path / "doc.md"
    f.write_text(_SAMPLE_VALID_MD, encoding="utf-8")
    assert main(["dry-run", "-f", str(f), "-r", "docs://test"]) == CliExitCode.VALIDATION_ERROR


def test_cli_missing_source_reference_for_md_returns_validation_error(tmp_path: Path) -> None:
    """.md file without --source-reference must fail with VALIDATION_ERROR (2)."""
    f = tmp_path / "doc.md"
    f.write_text(_SAMPLE_VALID_MD, encoding="utf-8")
    assert main(["dry-run", "-f", str(f), "-t", "documentation"]) == CliExitCode.VALIDATION_ERROR


def test_cli_missing_source_reference_for_markdown_returns_validation_error(tmp_path: Path) -> None:
    """.markdown file without --source-reference must fail with VALIDATION_ERROR (2)."""
    f = tmp_path / "doc.markdown"
    f.write_text(_SAMPLE_VALID_MD, encoding="utf-8")
    assert main(["dry-run", "-f", str(f), "-t", "documentation"]) == CliExitCode.VALIDATION_ERROR


def test_cli_valid_markdown_with_source_reference_succeeds(tmp_path: Path) -> None:
    """.markdown file with valid --source-reference must succeed."""
    f = tmp_path / "doc.markdown"
    f.write_text(_SAMPLE_VALID_MD, encoding="utf-8")
    code = main(["dry-run", "-f", str(f), "-t", "documentation", "-r", "docs://valid-markdown"])
    assert code == CliExitCode.SUCCESS


def test_cli_missing_source_reference_for_txt_returns_validation_error(tmp_path: Path) -> None:
    """.txt file without --source-reference must fail with VALIDATION_ERROR (2)."""
    f = tmp_path / "doc.txt"
    f.write_text(_SAMPLE_VALID_TXT, encoding="utf-8")
    assert main(["dry-run", "-f", str(f), "-t", "sop"]) == CliExitCode.VALIDATION_ERROR


def test_cli_providing_source_reference_for_runbook_json_rejected(tmp_path: Path) -> None:
    """Passing --source-reference for structured runbook JSON must be rejected with exit code 2."""
    f = tmp_path / "rb.json"
    f.write_text(json.dumps(_SAMPLE_VALID_RUNBOOK), encoding="utf-8")
    code = main(["dry-run", "-f", str(f), "-t", "runbook", "-r", "runbook://override-attempt"])
    assert code == CliExitCode.VALIDATION_ERROR


def test_cli_providing_source_reference_for_known_issue_json_rejected(tmp_path: Path) -> None:
    """Passing --source-reference for structured known issue JSON must fail with code 2."""
    f = tmp_path / "ki.json"
    f.write_text(json.dumps(_SAMPLE_VALID_KNOWN_ISSUE), encoding="utf-8")
    code = main(
        ["dry-run", "-f", str(f), "-t", "known_issue", "-r", "known-issue://override-attempt"]
    )
    assert code == CliExitCode.VALIDATION_ERROR


def test_structured_json_provenance_comes_strictly_from_validated_payload(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Proves Runbook and Known-Issue canonical provenance originates from JSON payload."""
    rb_file = tmp_path / "rb.json"
    rb_file.write_text(json.dumps(_SAMPLE_VALID_RUNBOOK), encoding="utf-8")
    code_rb = main(["dry-run", "-f", str(rb_file), "-t", "runbook", "--json"])
    assert code_rb == CliExitCode.SUCCESS
    out_rb = json.loads(capsys.readouterr().out)
    assert out_rb["source_reference"] == _SAMPLE_VALID_RUNBOOK["source_reference"]
    assert out_rb["structured_record_type"] == "runbook"

    ki_file = tmp_path / "ki.json"
    ki_file.write_text(json.dumps(_SAMPLE_VALID_KNOWN_ISSUE), encoding="utf-8")
    code_ki = main(["dry-run", "-f", str(ki_file), "-t", "known_issue", "--json"])
    assert code_ki == CliExitCode.SUCCESS
    out_ki = json.loads(capsys.readouterr().out)
    assert out_ki["source_reference"] == _SAMPLE_VALID_KNOWN_ISSUE["source_reference"]
    assert out_ki["structured_record_type"] == "known_issue"


def test_cli_unsupported_extensions_rejected(tmp_path: Path) -> None:
    """Unsupported file extensions (.yaml, .pdf, .docx, .html) must return VALIDATION_ERROR (2)."""
    for bad_ext in [".yaml", ".yml", ".pdf", ".docx", ".html"]:
        f = tmp_path / f"test{bad_ext}"
        f.write_text("dummy", encoding="utf-8")
        assert (
            main(["dry-run", "-f", str(f), "-t", "documentation", "-r", "docs://test"])
            == CliExitCode.VALIDATION_ERROR
        )


def test_cli_category_and_format_mismatch_rejected(tmp_path: Path) -> None:
    """.md with structured runbook type or .json with documentation type must be rejected."""
    md_file = tmp_path / "doc.md"
    md_file.write_text(_SAMPLE_VALID_MD, encoding="utf-8")
    assert main(["dry-run", "-f", str(md_file), "-t", "runbook"]) == CliExitCode.VALIDATION_ERROR

    json_file = tmp_path / "doc.json"
    json_file.write_text("{}", encoding="utf-8")
    assert (
        main(["dry-run", "-f", str(json_file), "-t", "documentation", "-r", "docs://test"])
        == CliExitCode.VALIDATION_ERROR
    )


def test_dry_run_rejects_secret_bearing_content(tmp_path: Path) -> None:
    """Dry-run must fail closed with exit code 2 when secrets are detected."""
    f = tmp_path / "secret.md"
    f.write_text("Here is a token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456", encoding="utf-8")
    assert (
        main(["dry-run", "-f", str(f), "-t", "documentation", "-r", "docs://secret-test"])
        == CliExitCode.VALIDATION_ERROR
    )


def test_dry_run_rejects_malformed_utf8(tmp_path: Path) -> None:
    """Dry-run must fail closed with exit code 2 on malformed UTF-8 bytes."""
    f = tmp_path / "corrupt.md"
    f.write_bytes(b"Invalid bytes: \xff\xfe\x00\x00\x80\x81")
    assert (
        main(["dry-run", "-f", str(f), "-t", "documentation", "-r", "docs://corrupt-test"])
        == CliExitCode.VALIDATION_ERROR
    )


def test_dry_run_rejects_oversized_file(tmp_path: Path) -> None:
    """Dry-run must fail closed with exit code 2 if file exceeds MAX_SOURCE_FILE_BYTES."""
    f = tmp_path / "huge.md"
    # Create file slightly over 2 MiB
    f.write_bytes(b"# Huge\n" + b"A" * (MAX_SOURCE_FILE_BYTES + 10))
    assert (
        main(["dry-run", "-f", str(f), "-t", "documentation", "-r", "docs://huge-test"])
        == CliExitCode.VALIDATION_ERROR
    )


def test_dry_run_isolation_zero_mutation_or_inference(tmp_path: Path) -> None:
    """Dry-run must not invoke FastEmbed, create database engines, or access artifact stores."""
    f = tmp_path / "safe.md"
    f.write_text(_SAMPLE_VALID_MD, encoding="utf-8")

    with (
        patch("kb_mcp.ingestion.composition.create_knowledge_engine") as mock_engine,
        patch("kb_mcp.ingestion.composition.create_embedding_provider") as mock_provider,
        patch("kb_mcp.ingestion.composition.FilesystemKnowledgeArtifactStore") as mock_store,
    ):
        code = main(["dry-run", "-f", str(f), "-t", "documentation", "-r", "docs://isolated-test"])
        assert code == CliExitCode.SUCCESS
        mock_engine.assert_not_called()
        mock_provider.assert_not_called()
        mock_store.assert_not_called()


def test_ingest_missing_database_url_returns_config_error(tmp_path: Path) -> None:
    """Ingest subcommand without KNOWLEDGE_DATABASE_URL returns CONFIG_ERROR (3)."""
    f = tmp_path / "doc.md"
    f.write_text(_SAMPLE_VALID_MD, encoding="utf-8")

    with patch("kb_mcp.ingestion.cli.KnowledgeServerSettings") as mock_settings_cls:
        mock_settings = MagicMock()
        mock_settings.is_database_configured = False
        mock_settings_cls.return_value = mock_settings

        code = main(["ingest", "-f", str(f), "-t", "documentation", "-r", "docs://cfg-test"])
        assert code == CliExitCode.CONFIG_ERROR


def test_ingest_missing_artifact_root_returns_config_error(tmp_path: Path) -> None:
    """Ingest subcommand without KNOWLEDGE_ARTIFACT_ROOT returns CONFIG_ERROR (3)."""
    f = tmp_path / "doc.md"
    f.write_text(_SAMPLE_VALID_MD, encoding="utf-8")

    with patch("kb_mcp.ingestion.cli.KnowledgeServerSettings") as mock_settings_cls:
        mock_settings = MagicMock()
        mock_settings.is_database_configured = True
        mock_settings.artifact_root = None
        mock_settings_cls.return_value = mock_settings

        code = main(["ingest", "-f", str(f), "-t", "documentation", "-r", "docs://cfg-test"])
        assert code == CliExitCode.CONFIG_ERROR


def test_ingest_embedding_failure_returns_runtime_unavailable(tmp_path: Path) -> None:
    """Ingest subcommand failing during embedding inference returns RUNTIME_UNAVAILABLE (4)."""
    f = tmp_path / "doc.md"
    f.write_text(_SAMPLE_VALID_MD, encoding="utf-8")

    mock_context = MagicMock()
    mock_context.admission_service = KnowledgeAdmissionService()
    mock_context.coordinator.ingest = AsyncMock(
        side_effect=EmbeddingInferenceError("Offline model failed")
    )
    mock_context.close = AsyncMock()

    with (
        patch("kb_mcp.ingestion.cli.KnowledgeServerSettings"),
        patch("kb_mcp.ingestion.cli.compose_ingestion_pipeline", return_value=mock_context),
    ):
        code = main(["ingest", "-f", str(f), "-t", "documentation", "-r", "docs://fail-test"])
        assert code == CliExitCode.RUNTIME_UNAVAILABLE
        mock_context.close.assert_awaited_once()


def test_ingest_persistence_failure_returns_persistence_error(tmp_path: Path) -> None:
    """Ingest subcommand failing during database commit returns PERSISTENCE_ERROR (5)."""
    f = tmp_path / "doc.md"
    f.write_text(_SAMPLE_VALID_MD, encoding="utf-8")

    mock_context = MagicMock()
    mock_context.admission_service = KnowledgeAdmissionService()
    mock_context.coordinator.ingest = AsyncMock(
        side_effect=KnowledgePersistenceError("Database transaction failed")
    )
    mock_context.close = AsyncMock()

    with (
        patch("kb_mcp.ingestion.cli.KnowledgeServerSettings"),
        patch("kb_mcp.ingestion.cli.compose_ingestion_pipeline", return_value=mock_context),
    ):
        code = main(["ingest", "-f", str(f), "-t", "documentation", "-r", "docs://fail-test"])
        assert code == CliExitCode.PERSISTENCE_ERROR
        mock_context.close.assert_awaited_once()


def test_ingest_success_returns_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Ingest subcommand on valid document returns exit code 0 and clean output."""
    f = tmp_path / "doc.md"
    f.write_text(_SAMPLE_VALID_MD, encoding="utf-8")

    mock_context = MagicMock()
    mock_context.admission_service = KnowledgeAdmissionService()
    mock_result = IngestionResultDTO(
        status=IngestionStatus.APPROVED,
        document_id="doc_1234567890abcdef12345678",
        source_reference="docs://safe-architecture",
        content_hash="a" * 64,
        version=1,
        chunk_count=2,
    )
    mock_context.coordinator.ingest = AsyncMock(return_value=mock_result)
    mock_context.close = AsyncMock()

    with (
        patch("kb_mcp.ingestion.cli.KnowledgeServerSettings"),
        patch("kb_mcp.ingestion.cli.compose_ingestion_pipeline", return_value=mock_context),
    ):
        code = main(
            [
                "ingest",
                "-f",
                str(f),
                "-t",
                "documentation",
                "-r",
                "docs://safe-architecture",
                "--json",
            ]
        )
        assert code == CliExitCode.SUCCESS
        out = json.loads(capsys.readouterr().out)
        assert out["status"] == "APPROVED"
        assert out["version"] == 1
        assert out["chunk_count"] == 2
        mock_context.close.assert_awaited_once()


def test_output_sanitization_no_internals_leaked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ensure CLI stdout and stderr never leak physical file paths, SQL queries, or embeddings."""
    f = tmp_path / "doc.md"
    f.write_text(_SAMPLE_VALID_MD, encoding="utf-8")

    code = main(["dry-run", "-f", str(f), "-t", "documentation", "-r", "docs://test-leak"])
    assert code == CliExitCode.SUCCESS
    captured = capsys.readouterr()

    # Must not contain physical file path or scratch references
    assert str(tmp_path) not in captured.out
    assert "postgresql://" not in captured.out
    assert "embedding" not in captured.out


def test_ingest_database_engine_init_failure_returns_persistence_error(tmp_path: Path) -> None:
    """Database engine creation/connectivity failure returns PERSISTENCE_ERROR (5)."""
    f = tmp_path / "doc.md"
    f.write_text(_SAMPLE_VALID_MD, encoding="utf-8")

    with (
        patch("kb_mcp.ingestion.cli.KnowledgeServerSettings"),
        patch(
            "kb_mcp.ingestion.cli.compose_ingestion_pipeline",
            side_effect=KnowledgeRuntimeInitializationError(
                "Failed to create Knowledge database engine: connection refused"
            ),
        ),
    ):
        code = main(["ingest", "-f", str(f), "-t", "documentation", "-r", "docs://db-fail"])
        assert code == CliExitCode.PERSISTENCE_ERROR


def test_ingest_sqlalchemy_error_returns_persistence_error(tmp_path: Path) -> None:
    """SQLAlchemy runtime persistence error returns PERSISTENCE_ERROR (5)."""
    f = tmp_path / "doc.md"
    f.write_text(_SAMPLE_VALID_MD, encoding="utf-8")

    mock_context = MagicMock()
    mock_context.admission_service = KnowledgeAdmissionService()
    mock_context.coordinator.ingest = AsyncMock(
        side_effect=SQLAlchemyError("PostgreSQL connection terminated unexpectedly")
    )
    mock_context.close = AsyncMock()

    with (
        patch("kb_mcp.ingestion.cli.KnowledgeServerSettings"),
        patch("kb_mcp.ingestion.cli.compose_ingestion_pipeline", return_value=mock_context),
    ):
        code = main(["ingest", "-f", str(f), "-t", "documentation", "-r", "docs://sql-fail"])
        assert code == CliExitCode.PERSISTENCE_ERROR
        mock_context.close.assert_awaited_once()


@pytest.mark.parametrize(
    ("case_id", "filename", "file_bytes", "doc_type", "source_ref"),
    [
        # 1. unsupported extension
        ("1_unsupported_ext", "bad.yaml", b"key: value\n", "documentation", "docs://test"),
        # 2. malformed UTF-8
        (
            "2_malformed_utf8",
            "bad.md",
            b"\xff\xfe\x00\x00\x80\x81",
            "documentation",
            "docs://test",
        ),
        # 3. secret-bearing Markdown
        (
            "3_secret_md",
            "secret.md",
            b"# Secret\nghp_1234567890abcdefghijklmnopqrstuvwxyz\n",
            "documentation",
            "docs://test",
        ),
        # 4. secret in structured JSON identity/provenance field
        (
            "4_identity_secret",
            "rb_secret.json",
            json.dumps({**_SAMPLE_VALID_RUNBOOK, "runbook_id": "ghp_1234567890abcdef"}).encode(),
            "runbook",
            None,
        ),
        # 5. strongly-labelled personal identifier in identity field
        (
            "5_identity_pii",
            "rb_pii.json",
            json.dumps({**_SAMPLE_VALID_RUNBOOK, "runbook_id": "personal_id:12345678"}).encode(),
            "runbook",
            None,
        ),
        # 6. mass PII >10 findings
        (
            "6_mass_pii",
            "mass_pii.md",
            "\n".join(f"Contact user{i}@company.no for help." for i in range(12)).encode(),
            "documentation",
            "docs://test",
        ),
        # 7. invalid provenance scheme
        (
            "7_bad_scheme",
            "bad_scheme.md",
            b"# Header\nValid content for testing.\n",
            "documentation",
            "ftp://invalid-scheme",
        ),
        # 8. category/scheme mismatch
        ("8_category_mismatch", "doc.md", b"# Header\nValid content.\n", "runbook", None),
        # 9. malformed Runbook JSON
        (
            "9_malformed_rb",
            "bad_rb.json",
            b'{"runbook_id": "rb1", "invalid_json": true',
            "runbook",
            None,
        ),
        # 10. malformed Known-Issue JSON
        (
            "10_malformed_ki",
            "bad_ki.json",
            b'{"issue_id": "ki1", "missing_fields": true}',
            "known_issue",
            None,
        ),
        # 11. structured JSON + CLI --source-reference override
        (
            "11_structured_override",
            "rb_override.json",
            json.dumps(_SAMPLE_VALID_RUNBOOK).encode(),
            "runbook",
            "runbook://override-attempt",
        ),
    ],
)
def test_cli_negative_security_exact_matrix(  # noqa: PLR0917
    tmp_path: Path,
    case_id: str,  # noqa: ARG001
    filename: str,
    file_bytes: bytes,
    doc_type: str,
    source_ref: str | None,
) -> None:
    """Prove all 11 frozen negative-security cases exit with code 2 and have zero side effects."""
    f = tmp_path / filename
    f.write_bytes(file_bytes)

    cmd = ["dry-run", "-f", str(f), "-t", doc_type]
    if source_ref is not None:
        cmd.extend(["-r", source_ref])

    with (
        patch("kb_mcp.ingestion.composition.create_knowledge_engine") as mock_engine,
        patch("kb_mcp.ingestion.composition.create_embedding_provider") as mock_provider,
        patch("kb_mcp.ingestion.composition.FilesystemKnowledgeArtifactStore") as mock_store,
    ):
        code = main(cmd)
        assert code == CliExitCode.VALIDATION_ERROR
        # Zero side effects: zero embeddings, zero artifact writes, zero database activity
        mock_engine.assert_not_called()
        mock_provider.assert_not_called()
        mock_store.assert_not_called()


def test_subprocess_invalid_argument_clean_stderr(tmp_path: Path) -> None:
    """Invoking CLI via subprocess with invalid argument returns code 2 with clean stderr."""
    f = tmp_path / "non_existent.md"
    cmd = [
        sys.executable,
        "-m",
        "kb_mcp.ingestion.cli",
        "dry-run",
        "-f",
        str(f),
        "-t",
        "documentation",
        "-r",
        "docs://test",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == CliExitCode.VALIDATION_ERROR
    assert "Traceback" not in proc.stderr
    assert "CLI Error" in proc.stderr or "Validation Error" in proc.stderr
