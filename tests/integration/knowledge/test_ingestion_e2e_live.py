"""Live E2E integration test suite for Operator CLI and Knowledge Ingestion (Gate 7D.5E).

Requires explicit opt-in via environment variable:
    KNOWLEDGE_LIVE_INGESTION_TESTS=1

Verifies:
1. Endpoint safety: local PostgreSQL endpoint (127.0.0.1:5432) and superoffice_ai_knowledge.
2. Baseline verification: pre-test and post-cleanup counts must equal (3, 6, 3, 3).
3. Dry-run E2E: purely in-memory evaluation with 0 DB writes, 0 artifact writes, 0 embeddings.
4. General document lifecycle: initial ingest (v1), idempotent re-ingest (UNCHANGED), update (v2).
5. Structured Runbook & Known-Issue lifecycle: transactional persistence, JSON provenance ownership.
6. Negative security rejections: fail closed with code 2, zero DB writes, zero artifact writes.
7. Subprocess execution: invokes python -m kb_mcp.ingestion.cli to verify process boundary.
8. Retrieval round-trip: verifies retrieval via search_knowledge, get_runbook, find_known_issues.
9. Official MCP SDK client verification: connects via official ClientSession over Streamable HTTP.
10. Teardown cleanup: removes only exact synthetic Gate 7D.5E records and restores baseline counts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

# Prevent OpenBLAS/ONNX thread allocation exhaustion on Windows
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    create_async_engine,
)

from kb_mcp.adapters.factory import (
    create_knowledge_repository,
    create_knowledge_session_factory,
)
from kb_mcp.adapters.fastembed_provider import FastEmbedEmbeddingProvider
from kb_mcp.contracts.cli import CliExitCode
from kb_mcp.contracts.constants import DEFAULT_EMBEDDING_MODEL
from kb_mcp.contracts.dtos import (
    KnowledgeSearchCriteriaDTO,
    KnownIssueSearchCriteriaDTO,
)
from kb_mcp.ingestion.canonical import generate_document_id
from kb_mcp.ingestion.cli import main
from kb_mcp.server import create_knowledge_mcp_server
from kb_mcp.services.knowledge_service import KnowledgeApplicationService
from kb_mcp.settings import KnowledgeServerSettings

# ============================================================================
# Gate 7D.5E Live Safety Guard
# ============================================================================

pytestmark = pytest.mark.skipif(
    os.getenv("KNOWLEDGE_LIVE_INGESTION_TESTS") != "1",
    reason="Live PostgreSQL ingestion tests require opt-in KNOWLEDGE_LIVE_INGESTION_TESTS=1",
)

EXPECTED_BASELINE_COUNTS = (3, 6, 3, 3)  # (documents, chunks, runbooks, known_issues)

# Exact synthetic identifiers for Gate 7D.5E
DOC_ID_7D5E_GEN = generate_document_id("docs://test/7d5e/general_01", "documentation")
DOC_ID_7D5E_TXT = generate_document_id("sop://test/7d5e/sop_01", "sop")
DOC_ID_7D5E_RB = generate_document_id("runbook://test-7d5e-rb1", "runbook")
DOC_ID_7D5E_KI = generate_document_id("known-issue://test-7d5e-ki1", "known_issue")

SYNTHETIC_DOC_IDS = [
    DOC_ID_7D5E_GEN,
    DOC_ID_7D5E_TXT,
    DOC_ID_7D5E_RB,
    DOC_ID_7D5E_KI,
]
SYNTHETIC_RB_IDS = ["test-7d5e-rb1"]
SYNTHETIC_KI_IDS = ["test-7d5e-ki1"]

# Synthetic sample payloads
_SAMPLE_E2E_MARKDOWN_V1 = """# SuperOffice 7D.5E Verification Guide
This guide verifies the local knowledge ingestion pipeline.
Authentication and authorization procedures are validated here.
"""

_SAMPLE_E2E_MARKDOWN_V2 = """# SuperOffice 7D.5E Verification Guide Updated
This guide verifies the local knowledge ingestion pipeline version two.
Updated authentication and authorization procedures are validated here.
Additional operational troubleshooting notes have been added.
"""

_SAMPLE_E2E_TXT = """SuperOffice Standard Operating Procedure 7D.5E
Step 1: Inspect the gateway logs for connection errors.
Step 2: Follow standard escalation procedures for support tier 2.
"""

_SAMPLE_E2E_RUNBOOK = {
    "runbook_id": "test-7d5e-rb1",
    "title": "SuperOffice 7D.5E Synthetic Auth Runbook",
    "problem_description": "Handles authentication token expiry in local test environment.",
    "diagnostic_steps": [
        "Check local token cache.",
        "Verify OAuth provider availability.",
    ],
    "remediation_steps": [
        "Refresh local OAuth cache.",
        "Restart local service container.",
    ],
    "source_reference": "runbook://test-7d5e-rb1",
    "product": "SuperOffice Support Platform",
    "verified_version": "1.0",
}

_SAMPLE_E2E_KNOWN_ISSUE = {
    "issue_id": "test-7d5e-ki1",
    "title": "SuperOffice 7D.5E Synthetic SSO Skew",
    "symptom_summary": "SAML token validation fails intermittently on local clock drift.",
    "root_cause_summary": "Clock synchronization skew exceeds allowable threshold.",
    "workaround": "Restart Windows time synchronization service.",
    "permanent_fix_reference": "https://github.com/superoffice/fixes/issues/789",
    "affected_products": ["SuperOffice AI Platform"],
    "affected_versions": ["1.0-local"],
    "category": "Authentication",
    "source_reference": "known-issue://test-7d5e-ki1",
}


async def _get_table_counts(engine: AsyncEngine) -> tuple[int, int, int, int]:
    """Fetch current row counts for knowledge tables."""
    async with engine.connect() as conn:
        docs = (await conn.execute(text("SELECT count(1) FROM knowledge.documents"))).scalar_one()
        chunks = (await conn.execute(text("SELECT count(1) FROM knowledge.chunks"))).scalar_one()
        rbs = (await conn.execute(text("SELECT count(1) FROM knowledge.runbooks"))).scalar_one()
        kis = (await conn.execute(text("SELECT count(1) FROM knowledge.known_issues"))).scalar_one()
    return (int(docs), int(chunks), int(rbs), int(kis))


async def _verify_sample_corpus(engine: AsyncEngine) -> None:
    """Verify that existing baseline sample corpus remains present and untouched."""
    async with engine.connect() as conn:
        doc = (
            await conn.execute(
                text(
                    "SELECT document_id FROM knowledge.documents "
                    "WHERE document_id = 'sample-doc-postgres-timeout'"
                )
            )
        ).first()
        rb = (
            await conn.execute(
                text(
                    "SELECT runbook_id FROM knowledge.runbooks "
                    "WHERE runbook_id = 'sample-rb-postgres-timeout'"
                )
            )
        ).first()
        ki = (
            await conn.execute(
                text(
                    "SELECT issue_id FROM knowledge.known_issues "
                    "WHERE issue_id = 'sample-ki-db-pool-exhaustion'"
                )
            )
        ).first()

    assert doc is not None, "Baseline sample document missing from knowledge.documents"
    assert rb is not None, "Baseline sample runbook missing from knowledge.runbooks"
    assert ki is not None, "Baseline sample runbook missing from knowledge.known_issues"


async def _cleanup_synthetic_records(engine: AsyncEngine) -> None:
    """Delete ONLY exact Gate 7D.5E synthetic records."""
    async with engine.begin() as conn:
        for d_id in SYNTHETIC_DOC_IDS:
            await conn.execute(
                text("DELETE FROM knowledge.chunks WHERE document_id = :d_id"),
                {"d_id": d_id},
            )
        for r_id in SYNTHETIC_RB_IDS:
            await conn.execute(
                text("DELETE FROM knowledge.runbooks WHERE runbook_id = :r_id"),
                {"r_id": r_id},
            )
        for k_id in SYNTHETIC_KI_IDS:
            await conn.execute(
                text("DELETE FROM knowledge.known_issues WHERE issue_id = :k_id"),
                {"k_id": k_id},
            )
        for d_id in SYNTHETIC_DOC_IDS:
            await conn.execute(
                text("DELETE FROM knowledge.documents WHERE document_id = :d_id"),
                {"d_id": d_id},
            )


@asynccontextmanager
async def official_kb_session(app: Any) -> AsyncIterator[ClientSession]:
    """Open an official MCP ClientSession over Streamable HTTP to Knowledge MCP."""
    transport = httpx.ASGITransport(app=app)
    headers = {"Host": "localhost", "Accept": "application/json, text/event-stream"}
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=transport, base_url="http://localhost", headers=headers
        ) as http_client,
        streamable_http_client("http://localhost/mcp", http_client=http_client) as (r, w, _),
        ClientSession(r, w) as session,
    ):
        await session.initialize()
        yield session


@pytest.fixture
async def live_e2e_setup(
    tmp_path: Path,
) -> AsyncIterator[tuple[KnowledgeServerSettings, AsyncEngine, Path]]:
    """Verify endpoint safety, baseline counts, configure artifact root, and yield."""
    settings = KnowledgeServerSettings()
    assert settings.is_database_configured and settings.database_url is not None, (
        "KNOWLEDGE_DATABASE_URL must be configured for live integration tests."
    )
    raw_url = settings.database_url.get_secret_value()

    # Safety boundary verification: local host and superoffice_ai_knowledge only
    parsed = urlparse(raw_url.replace("+asyncpg", ""))
    assert parsed.hostname in ("127.0.0.1", "localhost"), (
        f"SAFETY VIOLATION: Target host '{parsed.hostname}' is not local."
    )
    assert parsed.path.strip("/").lower() == "superoffice_ai_knowledge", (
        f"SAFETY VIOLATION: Target database '{parsed.path}' is not 'superoffice_ai_knowledge'."
    )

    engine = create_async_engine(raw_url, pool_pre_ping=True)

    # Initial cleanup before recording baseline
    await _cleanup_synthetic_records(engine)

    initial_counts = await _get_table_counts(engine)
    if initial_counts != EXPECTED_BASELINE_COUNTS:
        await engine.dispose()
        pytest.fail(
            f"STOP BEFORE DML: Actual counts {initial_counts} != "
            f"expected baseline {EXPECTED_BASELINE_COUNTS}."
        )

    await _verify_sample_corpus(engine)

    # Configure temporary isolated artifact root outside git and scratch
    artifact_root = tmp_path / "safe_7d5e_artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)

    # Override artifact root in environment for test processes
    old_art_root = os.environ.get("KNOWLEDGE_ARTIFACT_ROOT")
    os.environ["KNOWLEDGE_ARTIFACT_ROOT"] = str(artifact_root.resolve())

    test_settings = KnowledgeServerSettings(
        database_url=settings.database_url,
        artifact_root=artifact_root,
        embedding_cache_dir=settings.embedding_cache_dir,
    )

    try:
        yield test_settings, engine, artifact_root
    finally:
        # Exact teardown cleanup
        await _cleanup_synthetic_records(engine)
        post_counts = await _get_table_counts(engine)
        await engine.dispose()

        if old_art_root is not None:
            os.environ["KNOWLEDGE_ARTIFACT_ROOT"] = old_art_root
        else:
            os.environ.pop("KNOWLEDGE_ARTIFACT_ROOT", None)

        assert post_counts == EXPECTED_BASELINE_COUNTS, (
            f"Cleanup failure: post-cleanup counts {post_counts} != "
            f"baseline {EXPECTED_BASELINE_COUNTS}."
        )


@pytest.mark.asyncio
async def test_dry_run_e2e_zero_side_effects(
    live_e2e_setup: tuple[KnowledgeServerSettings, AsyncEngine, Path],
    tmp_path: Path,
) -> None:
    """dry-run subcommand evaluates sources with zero database writes and zero artifact writes."""
    _settings, engine, artifact_root = live_e2e_setup

    md_file = tmp_path / "guide.md"
    md_file.write_text(_SAMPLE_E2E_MARKDOWN_V1, encoding="utf-8")

    rb_file = tmp_path / "rb.json"
    rb_file.write_text(json.dumps(_SAMPLE_E2E_RUNBOOK), encoding="utf-8")

    ki_file = tmp_path / "ki.json"
    ki_file.write_text(json.dumps(_SAMPLE_E2E_KNOWN_ISSUE), encoding="utf-8")

    # Execute dry-run for all sources
    assert (
        main(
            [
                "dry-run",
                "-f",
                str(md_file),
                "-t",
                "documentation",
                "-r",
                "docs://test/7d5e/general_01",
            ]
        )
        == CliExitCode.SUCCESS
    )
    assert main(["dry-run", "-f", str(rb_file), "-t", "runbook"]) == CliExitCode.SUCCESS
    assert main(["dry-run", "-f", str(ki_file), "-t", "known_issue"]) == CliExitCode.SUCCESS

    # Verify zero database mutations
    counts = await _get_table_counts(engine)
    assert counts == EXPECTED_BASELINE_COUNTS

    # Verify zero artifact files created
    approved_dir = artifact_root / "approved"
    staging_dir = artifact_root / "staging"
    assert not approved_dir.exists() or len(list(approved_dir.glob("**/*.*"))) == 0
    assert not staging_dir.exists() or len(list(staging_dir.glob("**/*.*"))) == 0


@pytest.mark.asyncio
async def test_full_knowledge_ingestion_lifecycle_e2e(  # noqa: PLR0915
    live_e2e_setup: tuple[KnowledgeServerSettings, AsyncEngine, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Execute complete ingestion lifecycle.

    Tests general doc (v1 -> unchanged -> v2), runbook, and known issue.
    """
    settings, engine, _artifact_root = live_e2e_setup

    # ------------------------------------------------------------------------
    # 1. General Document Ingestion Lifecycle
    # ------------------------------------------------------------------------
    doc_file = tmp_path / "doc.md"
    doc_file.write_text(_SAMPLE_E2E_MARKDOWN_V1, encoding="utf-8")

    # Initial Ingest -> APPROVED (v1)
    code1 = main(
        [
            "ingest",
            "-f",
            str(doc_file),
            "-t",
            "documentation",
            "-r",
            "docs://test/7d5e/general_01",
            "--json",
        ]
    )
    assert code1 == CliExitCode.SUCCESS
    res1 = json.loads(capsys.readouterr().out)
    assert res1["status"] == "APPROVED"
    assert res1["version"] == 1
    assert res1["chunk_count"] > 0
    assert res1["document_id"] == DOC_ID_7D5E_GEN

    # Verify DB persistence
    counts_after_doc = await _get_table_counts(engine)
    assert counts_after_doc[0] == EXPECTED_BASELINE_COUNTS[0] + 1
    assert counts_after_doc[1] == EXPECTED_BASELINE_COUNTS[1] + res1["chunk_count"]

    # Identical Re-Ingest -> UNCHANGED (v1)
    code_idemp = main(
        [
            "ingest",
            "-f",
            str(doc_file),
            "-t",
            "documentation",
            "-r",
            "docs://test/7d5e/general_01",
            "--json",
        ]
    )
    assert code_idemp == CliExitCode.SUCCESS
    res_idemp = json.loads(capsys.readouterr().out)
    assert res_idemp["status"] == "UNCHANGED"
    assert res_idemp["version"] == 1
    assert res_idemp["chunk_count"] == 0

    # Counts must be unchanged
    assert await _get_table_counts(engine) == counts_after_doc

    # Updated Content Re-Ingest -> APPROVED (v2)
    doc_file.write_text(_SAMPLE_E2E_MARKDOWN_V2, encoding="utf-8")
    code2 = main(
        [
            "ingest",
            "-f",
            str(doc_file),
            "-t",
            "documentation",
            "-r",
            "docs://test/7d5e/general_01",
            "--json",
        ]
    )
    assert code2 == CliExitCode.SUCCESS
    res2 = json.loads(capsys.readouterr().out)
    assert res2["status"] == "APPROVED"
    assert res2["version"] == 2
    assert res2["chunk_count"] > 0
    assert res2["content_hash"] != res1["content_hash"]

    # ------------------------------------------------------------------------
    # 2. Operational Runbook Ingestion Lifecycle
    # ------------------------------------------------------------------------
    rb_file = tmp_path / "rb.json"
    rb_file.write_text(json.dumps(_SAMPLE_E2E_RUNBOOK), encoding="utf-8")

    code_rb = main(["ingest", "-f", str(rb_file), "-t", "runbook", "--json"])
    assert code_rb == CliExitCode.SUCCESS
    res_rb = json.loads(capsys.readouterr().out)
    assert res_rb["status"] == "APPROVED"
    assert res_rb["version"] == 1
    assert res_rb["document_id"] == DOC_ID_7D5E_RB
    assert res_rb["source_reference"] == _SAMPLE_E2E_RUNBOOK["source_reference"]

    # Verify runbook table row exists
    async with engine.connect() as conn:
        rb_row = (
            await conn.execute(
                text("SELECT runbook_id, title FROM knowledge.runbooks WHERE runbook_id = :rb_id"),
                {"rb_id": SYNTHETIC_RB_IDS[0]},
            )
        ).first()
        assert rb_row is not None
        assert rb_row.runbook_id == SYNTHETIC_RB_IDS[0]

    # Identical Runbook Re-Ingest -> UNCHANGED
    code_rb_reingest = main(["ingest", "-f", str(rb_file), "-t", "runbook", "--json"])
    assert code_rb_reingest == CliExitCode.SUCCESS
    res_rb_reingest = json.loads(capsys.readouterr().out)
    assert res_rb_reingest["status"] == "UNCHANGED"
    assert res_rb_reingest["version"] == 1

    # ------------------------------------------------------------------------
    # 3. Known Issue Ingestion Lifecycle
    # ------------------------------------------------------------------------
    ki_file = tmp_path / "ki.json"
    ki_file.write_text(json.dumps(_SAMPLE_E2E_KNOWN_ISSUE), encoding="utf-8")

    code_ki = main(["ingest", "-f", str(ki_file), "-t", "known_issue", "--json"])
    assert code_ki == CliExitCode.SUCCESS
    res_ki = json.loads(capsys.readouterr().out)
    assert res_ki["status"] == "APPROVED"
    assert res_ki["version"] == 1
    assert res_ki["document_id"] == DOC_ID_7D5E_KI
    assert res_ki["source_reference"] == _SAMPLE_E2E_KNOWN_ISSUE["source_reference"]

    # Verify known issue table row exists
    async with engine.connect() as conn:
        ki_row = (
            await conn.execute(
                text("SELECT issue_id, title FROM knowledge.known_issues WHERE issue_id = :ki_id"),
                {"ki_id": SYNTHETIC_KI_IDS[0]},
            )
        ).first()
        assert ki_row is not None
        assert ki_row.issue_id == SYNTHETIC_KI_IDS[0]

    # Identical Known Issue Re-Ingest -> UNCHANGED
    code_ki_reingest = main(["ingest", "-f", str(ki_file), "-t", "known_issue", "--json"])
    assert code_ki_reingest == CliExitCode.SUCCESS
    res_ki_reingest = json.loads(capsys.readouterr().out)
    assert res_ki_reingest["status"] == "UNCHANGED"
    assert res_ki_reingest["version"] == 1

    # ------------------------------------------------------------------------
    # 4. Retrieval Round-Trip Verification (Native Service Path)
    # ------------------------------------------------------------------------
    session_factory = create_knowledge_session_factory(engine)
    read_repo = create_knowledge_repository(settings, session_factory=session_factory)
    provider = FastEmbedEmbeddingProvider(
        model_name=DEFAULT_EMBEDDING_MODEL,
        cache_dir=settings.embedding_cache_dir,
    )
    app_service = KnowledgeApplicationService(
        repository=read_repo,
        embedding_provider=provider,
    )

    # 4a. search_knowledge finds newly ingested synthetic document
    search_results = await app_service.search_knowledge(
        KnowledgeSearchCriteriaDTO(query_text="SuperOffice 7D.5E Verification Guide", limit=5)
    )
    matched_doc_ids = [r.document_id for r in search_results]
    assert DOC_ID_7D5E_GEN in matched_doc_ids

    # 4b. get_runbook retrieves newly ingested synthetic runbook
    retrieved_rb = await app_service.get_runbook(SYNTHETIC_RB_IDS[0])
    assert retrieved_rb.runbook_id == SYNTHETIC_RB_IDS[0]
    assert retrieved_rb.title == _SAMPLE_E2E_RUNBOOK["title"]

    # 4c. find_known_issues retrieves newly ingested synthetic known issue
    ki_results = await app_service.find_known_issues(
        KnownIssueSearchCriteriaDTO(query_text="Synthetic SSO Skew", limit=5)
    )
    matched_ki_ids = [k.issue_id for k in ki_results]
    assert SYNTHETIC_KI_IDS[0] in matched_ki_ids

    # ------------------------------------------------------------------------
    # 5. Official MCP SDK Client Read-After-Ingest Verification
    # ------------------------------------------------------------------------
    mcp_server = create_knowledge_mcp_server(service=app_service)
    starlette_app = mcp_server.streamable_http_app()

    async with official_kb_session(starlette_app) as session:
        # Tool inventory must remain exactly 3
        tools_list = await session.list_tools()
        tool_names = sorted(t.name for t in tools_list.tools)
        assert tool_names == ["find_known_issues", "get_runbook", "search_knowledge"]

        # Call search_knowledge over official MCP protocol
        mcp_res: CallToolResult = await session.call_tool(
            "search_knowledge",
            arguments={"query_text": "SuperOffice 7D.5E Verification Guide", "max_results": 5},
        )
        assert not mcp_res.isError
        assert len(mcp_res.content) > 0
        retrieved_items = [
            json.loads(b.text) for b in mcp_res.content if isinstance(b, TextContent)
        ]
        assert len(retrieved_items) > 0

        # Output minimization checks: no vectors, no artifact paths, no database URLs
        found_synthetic = False
        for item in retrieved_items:
            assert "embedding" not in item
            assert "vector" not in item
            assert "artifact_path" not in item
            assert "postgresql://" not in str(item)
            if item.get("document_id") == DOC_ID_7D5E_GEN:
                found_synthetic = True

        assert found_synthetic, (
            "Official MCP search_knowledge failed to retrieve synthetic document"
        )


@pytest.mark.asyncio
async def test_subprocess_cli_execution(
    live_e2e_setup: tuple[KnowledgeServerSettings, AsyncEngine, Path],
    tmp_path: Path,
) -> None:
    """Execute CLI via real python -m kb_mcp.ingestion.cli subprocess."""
    _settings, _, _ = live_e2e_setup

    md_file = tmp_path / "subproc_doc.md"
    md_file.write_text(_SAMPLE_E2E_MARKDOWN_V1, encoding="utf-8")

    cmd = [
        sys.executable,
        "-m",
        "kb_mcp.ingestion.cli",
        "dry-run",
        "-f",
        str(md_file),
        "-t",
        "documentation",
        "-r",
        "docs://test/7d5e/subproc_01",
        "--json",
    ]

    subproc_env = {
        **os.environ,
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
    }

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        env=subproc_env,
    )
    assert proc.returncode == 0, f"Subprocess failed with stderr: {proc.stderr}"
    data = json.loads(proc.stdout)
    assert data["status"] == "DRY_RUN_VALID"
    assert data["document_type"] == "documentation"
    assert data["predicted_chunk_count"] > 0


@pytest.mark.asyncio
async def test_negative_security_rejections_zero_mutation(
    live_e2e_setup: tuple[KnowledgeServerSettings, AsyncEngine, Path],
    tmp_path: Path,
) -> None:
    """Security rejections fail closed with exit code 2 and leave storage untouched."""
    _settings, engine, _artifact_root = live_e2e_setup

    counts_before = await _get_table_counts(engine)

    # 1. Unsupported file format (.yaml)
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("key: value", encoding="utf-8")
    assert (
        main(["ingest", "-f", str(bad_yaml), "-t", "documentation", "-r", "docs://bad"])
        == CliExitCode.VALIDATION_ERROR
    )

    # 2. Secret-bearing document
    secret_md = tmp_path / "secret.md"
    secret_md.write_text(
        "# Leaked Credentials\nghp_1234567890abcdefghijklmnopqrstuvwxyz",
        encoding="utf-8",
    )
    assert (
        main(["ingest", "-f", str(secret_md), "-t", "documentation", "-r", "docs://secret"])
        == CliExitCode.VALIDATION_ERROR
    )

    # 3. Malformed UTF-8
    corrupt_md = tmp_path / "corrupt.md"
    corrupt_md.write_bytes(b"\xff\xfe\x00\x00")
    assert (
        main(["ingest", "-f", str(corrupt_md), "-t", "documentation", "-r", "docs://corrupt"])
        == CliExitCode.VALIDATION_ERROR
    )

    # 4. Providing --source-reference for structured runbook JSON
    rb_file = tmp_path / "rb_override.json"
    rb_file.write_text(json.dumps(_SAMPLE_E2E_RUNBOOK), encoding="utf-8")
    assert (
        main(["ingest", "-f", str(rb_file), "-t", "runbook", "-r", "runbook://override"])
        == CliExitCode.VALIDATION_ERROR
    )

    # Verify zero database mutations after all rejections
    counts_after = await _get_table_counts(engine)
    assert counts_after == counts_before
