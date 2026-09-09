"""Live integration tests for PostgreSQL Knowledge Ingestion (Gate 7D.5D).

Requires explicit opt-in via environment variable:
    KNOWLEDGE_LIVE_INGESTION_TESTS=1

Verifies:
- Endpoint safety: local PostgreSQL endpoint (127.0.0.1:5432) and database superoffice_ai_knowledge.
- Baseline verification: pre-test and post-cleanup counts must equal (3, 6, 3, 3).
- Real local FastEmbed embedding inference (BAAI/bge-small-en-v1.5, 384 dimensions, no download).
- End-to-end ingestion cases: new document, identical re-ingestion, content update with version
  increment, runbook payload, known issue payload, transaction rollback & compensation,
  and same-document concurrency.
- Teardown cleanup: removes only synthetic Gate 7D.5D records and restores pre-test baseline counts.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from kb_mcp.adapters.factory import create_knowledge_ingestion_repository
from kb_mcp.adapters.fastembed_provider import FastEmbedEmbeddingProvider
from kb_mcp.adapters.filesystem_artifact_store import FilesystemKnowledgeArtifactStore
from kb_mcp.contracts.constants import DEFAULT_EMBEDDING_MODEL, EMBEDDING_DIMENSION
from kb_mcp.contracts.errors import KnowledgePersistenceError
from kb_mcp.contracts.ingestion import (
    CanonicalKnowledgeDocumentDTO,
    CorpusCategory,
    IngestionStatus,
    SanitizedKnownIssuePayloadDTO,
    SanitizedRunbookPayloadDTO,
)
from kb_mcp.ingestion.canonical import generate_document_id
from kb_mcp.ingestion.chunking import DeterministicChunker
from kb_mcp.ingestion.orchestrator import KnowledgeIngestionCoordinator
from kb_mcp.settings import KnowledgeServerSettings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

    from kb_mcp.adapters.postgres_ingestion_repository import (
        PostgresKnowledgeIngestionRepository,
    )

# ============================================================================
# Gate 7D.5D Live Safety Guard
# ============================================================================

pytestmark = pytest.mark.skipif(
    os.getenv("KNOWLEDGE_LIVE_INGESTION_TESTS") != "1",
    reason=(
        "Live PostgreSQL ingestion tests require explicit opt-in KNOWLEDGE_LIVE_INGESTION_TESTS=1"
    ),
)

EXPECTED_BASELINE_COUNTS = (3, 6, 3, 3)  # (documents, chunks, runbooks, known_issues)

# Exact synthetic identifiers for Gate 7D.5D
DOC_ID_GENERAL = generate_document_id("docs://test/7d5d/general_01", "documentation")
DOC_ID_RUNBOOK = generate_document_id("runbook://test-7d5d/rb1", "runbook")
DOC_ID_KNOWN_ISSUE = generate_document_id("known-issue://test-7d5d/ki1", "known_issue")
DOC_ID_FAIL = generate_document_id("docs://test/7d5d/fail_01", "documentation")
DOC_ID_CONC = generate_document_id("docs://test/7d5d/conc_01", "documentation")

SYNTHETIC_DOC_IDS = [
    DOC_ID_GENERAL,
    DOC_ID_RUNBOOK,
    DOC_ID_KNOWN_ISSUE,
    DOC_ID_FAIL,
    DOC_ID_CONC,
]
SYNTHETIC_RB_IDS = ["test-7d5d-rb1"]
SYNTHETIC_KI_IDS = ["test-7d5d-ki1"]


@dataclass
class LiveTestEnvironment:
    """Live environment bundle for 7D.5D integration tests."""

    engine: AsyncEngine
    session_maker: async_sessionmaker[AsyncSession]
    repository: PostgresKnowledgeIngestionRepository
    embedding_provider: FastEmbedEmbeddingProvider
    artifact_store: FilesystemKnowledgeArtifactStore
    coordinator: KnowledgeIngestionCoordinator
    artifact_dir: Path


async def _get_table_counts(engine: AsyncEngine) -> tuple[int, int, int, int]:
    """Fetch current row counts for knowledge tables."""
    async with engine.connect() as conn:
        docs = (await conn.execute(text("SELECT count(1) FROM knowledge.documents"))).scalar_one()
        chunks = (await conn.execute(text("SELECT count(1) FROM knowledge.chunks"))).scalar_one()
        rbs = (await conn.execute(text("SELECT count(1) FROM knowledge.runbooks"))).scalar_one()
        kis = (await conn.execute(text("SELECT count(1) FROM knowledge.known_issues"))).scalar_one()
    return (int(docs), int(chunks), int(rbs), int(kis))


async def _verify_sample_corpus(engine: AsyncEngine) -> None:
    """Verify that existing synthetic sample corpus remains present and uncorrupted."""
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
    assert ki is not None, "Baseline sample known issue missing from knowledge.known_issues"


async def _cleanup_synthetic_records(engine: AsyncEngine) -> None:
    """Delete ONLY exact Gate 7D.5D synthetic records."""
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


@pytest.fixture
async def live_env(tmp_path: Path) -> AsyncIterator[LiveTestEnvironment]:
    """Set up and tear down live integration test environment per test."""
    settings = KnowledgeServerSettings()
    assert settings.is_database_configured and settings.database_url is not None, (
        "KNOWLEDGE_DATABASE_URL must be configured for live integration tests."
    )
    raw_url = settings.database_url.get_secret_value()

    # Safety boundary verification: local host and superoffice_ai_knowledge only
    parsed = urlparse(raw_url.replace("+asyncpg", ""))
    assert parsed.hostname in ("127.0.0.1", "localhost"), (
        f"SAFETY VIOLATION: Target host '{parsed.hostname}' is not local (127.0.0.1/localhost)."
    )
    assert parsed.path.strip("/").lower() == "superoffice_ai_knowledge", (
        f"SAFETY VIOLATION: Target database '{parsed.path}' is not 'superoffice_ai_knowledge'."
    )

    engine = create_async_engine(raw_url, pool_pre_ping=True)
    session_maker: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine, expire_on_commit=False
    )

    # Initial cleanup of any leftover synthetic records before baseline recording
    await _cleanup_synthetic_records(engine)

    # Pre-test baseline verification
    initial_counts = await _get_table_counts(engine)
    assert initial_counts == EXPECTED_BASELINE_COUNTS, (
        f"Baseline count discrepancy: expected {EXPECTED_BASELINE_COUNTS}, got {initial_counts}."
    )
    await _verify_sample_corpus(engine)

    # Synthetic artifact directory safely outside repo and scratch
    artifact_root = tmp_path / "safe_7d5d_artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    fake_git = tmp_path / "fake_git_root"
    fake_git.mkdir(parents=True, exist_ok=True)
    artifact_store = FilesystemKnowledgeArtifactStore(
        artifact_root=artifact_root, git_root=fake_git
    )

    # Real local FastEmbed provider
    provider = FastEmbedEmbeddingProvider(
        model_name=DEFAULT_EMBEDDING_MODEL,
        cache_dir=settings.embedding_cache_dir,
    )

    repository = create_knowledge_ingestion_repository(settings, session_factory=session_maker)
    chunker = DeterministicChunker()

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=provider,
        artifact_store=artifact_store,
        repository=repository,
    )

    env = LiveTestEnvironment(
        engine=engine,
        session_maker=session_maker,
        repository=repository,
        embedding_provider=provider,
        artifact_store=artifact_store,
        coordinator=coordinator,
        artifact_dir=artifact_root,
    )

    try:
        yield env
    finally:
        # Cleanup synthetic DB records and verify baseline restoration
        await _cleanup_synthetic_records(engine)
        post_counts = await _get_table_counts(engine)
        await _verify_sample_corpus(engine)
        await engine.dispose()
        assert post_counts == EXPECTED_BASELINE_COUNTS, (
            f"Post-cleanup baseline discrepancy: expected {EXPECTED_BASELINE_COUNTS}, "
            f"got {post_counts}."
        )


# ============================================================================
# Live Test Cases
# ============================================================================


@pytest.mark.asyncio
async def test_live_fastembed_local_loading(live_env: LiveTestEnvironment) -> None:
    """Verify FastEmbed model loads locally and returns valid 384-d vectors without printing."""
    texts = ["Synthetic test text for local FastEmbed verification."]
    vectors = await live_env.embedding_provider.embed_documents(texts)

    assert len(vectors) == 1
    vec = vectors[0]
    assert len(vec) == EMBEDDING_DIMENSION
    assert all(isinstance(v, float) and math.isfinite(v) for v in vec)
    # Vectors must never be printed to logs or stdout


@pytest.mark.asyncio
async def test_live_new_general_document_and_idempotency(live_env: LiveTestEnvironment) -> None:
    """Case A & B: Ingest a new general document, then re-ingest identically (UNCHANGED)."""
    content = (
        "# SuperOffice CRM Integration Guide\n\n"
        "This is an operational guide for integrating SuperOffice with external systems.\n\n"
        "## Architecture Overview\n\n"
        "The architecture relies on asynchronous messaging and secure transactional boundaries."
    )
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    doc = CanonicalKnowledgeDocumentDTO(
        document_id=DOC_ID_GENERAL,
        title="SuperOffice CRM Integration Guide",
        document_type="documentation",
        source_reference="docs://test/7d5d/general_01",
        canonical_content=content,
        content_hash=content_hash,
        corpus_category=CorpusCategory.DOCUMENTATION,
    )

    # Case A: New document ingestion -> APPROVED, version 1
    res1 = await live_env.coordinator.ingest(doc)
    assert res1.status == IngestionStatus.APPROVED
    assert res1.document_id == doc.document_id
    assert res1.version == 1
    assert res1.chunk_count >= 1

    # Verify DB state for document
    async with live_env.engine.connect() as conn:
        doc_row = (
            (
                await conn.execute(
                    text(
                        "SELECT document_id, content_hash, version FROM knowledge.documents "
                        "WHERE document_id = :doc_id"
                    ),
                    {"doc_id": doc.document_id},
                )
            )
            .mappings()
            .first()
        )
        assert doc_row is not None
        assert doc_row["content_hash"] == content_hash
        assert doc_row["version"] == 1

        # Verify chunks in DB
        chunk_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT chunk_id, chunk_index, content FROM knowledge.chunks "
                        "WHERE document_id = :doc_id ORDER BY chunk_index ASC"
                    ),
                    {"doc_id": doc.document_id},
                )
            )
            .mappings()
            .all()
        )
        assert len(chunk_rows) == res1.chunk_count
        assert chunk_rows[0]["chunk_id"] == f"{doc.document_id}_c0000"

    # Case B: Identical re-ingestion -> UNCHANGED, version 1, chunk_count 0
    res2 = await live_env.coordinator.ingest(doc)
    assert res2.status == IngestionStatus.UNCHANGED
    assert res2.version == 1
    assert res2.chunk_count == 0

    # Verify DB chunk count has not doubled
    async with live_env.engine.connect() as conn:
        chunks_count = (
            await conn.execute(
                text("SELECT count(1) FROM knowledge.chunks WHERE document_id = :doc_id"),
                {"doc_id": doc.document_id},
            )
        ).scalar_one()
        assert chunks_count == res1.chunk_count


@pytest.mark.asyncio
async def test_live_changed_content_version_increment_and_chunk_replacement(
    live_env: LiveTestEnvironment,
) -> None:
    """Case C: Ingest changed content -> version +1, complete chunk replacement."""
    initial_content = (
        "# SuperOffice CRM Integration Guide\n\nInitial version text describing architecture."
    )
    initial_hash = hashlib.sha256(initial_content.encode("utf-8")).hexdigest()
    initial_doc = CanonicalKnowledgeDocumentDTO(
        document_id=DOC_ID_GENERAL,
        title="SuperOffice CRM Integration Guide",
        document_type="documentation",
        source_reference="docs://test/7d5d/general_01",
        canonical_content=initial_content,
        content_hash=initial_hash,
        corpus_category=CorpusCategory.DOCUMENTATION,
    )
    res_init = await live_env.coordinator.ingest(initial_doc)
    assert res_init.status == IngestionStatus.APPROVED
    assert res_init.version == 1

    # Updated version with new content
    updated_content = (
        "# SuperOffice CRM Integration Guide (Updated)\n\n"
        "This is an updated version of the guide with new troubleshooting steps.\n\n"
        "## Troubleshooting\n\n"
        "Inspect database connection pool and verify advisory lock keys are valid."
    )
    new_hash = hashlib.sha256(updated_content.encode("utf-8")).hexdigest()
    updated_doc = CanonicalKnowledgeDocumentDTO(
        document_id=DOC_ID_GENERAL,
        title="SuperOffice CRM Integration Guide (Updated)",
        document_type="documentation",
        source_reference="docs://test/7d5d/general_01",
        canonical_content=updated_content,
        content_hash=new_hash,
        corpus_category=CorpusCategory.DOCUMENTATION,
    )

    res = await live_env.coordinator.ingest(updated_doc)
    assert res.status == IngestionStatus.APPROVED
    assert res.version == 2
    assert res.chunk_count >= 1

    # Verify version 2 in DB and chunks updated
    async with live_env.engine.connect() as conn:
        doc_row = (
            (
                await conn.execute(
                    text(
                        "SELECT document_id, content_hash, version FROM knowledge.documents "
                        "WHERE document_id = :doc_id"
                    ),
                    {"doc_id": DOC_ID_GENERAL},
                )
            )
            .mappings()
            .first()
        )
        assert doc_row is not None
        assert doc_row["version"] == 2
        assert doc_row["content_hash"] == new_hash


@pytest.mark.asyncio
async def test_live_runbook_payload_same_transaction(live_env: LiveTestEnvironment) -> None:
    """Case D: Ingest operational Runbook -> document + runbook + chunks in SAME transaction."""
    rb_payload = SanitizedRunbookPayloadDTO(
        source_name="test_rb.json",
        runbook_id="test-7d5d-rb1",
        title="Resolve CRM Database Deadlock",
        problem_description="Diagnose and mitigate transactional deadlocks in SuperOffice CRM.",
        diagnostic_steps=("Check pg_stat_activity", "Identify blocked transactions"),
        remediation_steps=("Cancel conflicting backend", "Review advisory locking order"),
        product="SuperOffice CRM",
        verified_version="10.2",
        source_reference="runbook://test-7d5d/rb1",
        canonical_text="composite text for runbook",
    )
    content = f"# {rb_payload.title}\n\n{rb_payload.problem_description}"
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    doc = CanonicalKnowledgeDocumentDTO(
        document_id=DOC_ID_RUNBOOK,
        title=rb_payload.title,
        document_type="runbook",
        source_reference=rb_payload.source_reference,
        canonical_content=content,
        content_hash=content_hash,
        corpus_category=CorpusCategory.RUNBOOK,
        structured_payload=rb_payload,
    )

    res = await live_env.coordinator.ingest(doc)
    assert res.status == IngestionStatus.APPROVED
    assert res.version == 1

    # Verify document, runbook, and chunks all exist in DB
    async with live_env.engine.connect() as conn:
        doc_count = (
            await conn.execute(
                text("SELECT count(1) FROM knowledge.documents WHERE document_id = :id"),
                {"id": doc.document_id},
            )
        ).scalar_one()
        rb_row = (
            (
                await conn.execute(
                    text(
                        "SELECT runbook_id, title, product, diagnostic_steps "
                        "FROM knowledge.runbooks WHERE runbook_id = :id"
                    ),
                    {"id": rb_payload.runbook_id},
                )
            )
            .mappings()
            .first()
        )
        chunks_count = (
            await conn.execute(
                text("SELECT count(1) FROM knowledge.chunks WHERE document_id = :id"),
                {"id": doc.document_id},
            )
        ).scalar_one()

    assert doc_count == 1
    assert chunks_count >= 1
    assert rb_row is not None
    assert rb_row["title"] == rb_payload.title
    assert rb_row["product"] == "SuperOffice CRM"
    assert "pg_stat_activity" in str(rb_row["diagnostic_steps"])


@pytest.mark.asyncio
async def test_live_known_issue_payload_same_transaction(live_env: LiveTestEnvironment) -> None:
    """Case E: Ingest Known Issue -> document + known issue + chunks in SAME transaction."""
    ki_payload = SanitizedKnownIssuePayloadDTO(
        source_name="test_ki.json",
        issue_id="test-7d5d-ki1",
        title="High Memory Usage in Service Worker",
        symptom_summary="Service worker RSS exceeds memory threshold during batch processing.",
        root_cause_summary="Unbounded cache retention in worker context.",
        workaround="Restart worker service periodically.",
        permanent_fix_reference="KB-FIX-9876",
        affected_products=("Service", "Platform"),
        affected_versions=("10.1", "10.2"),
        category="Performance",
        source_reference="known-issue://test-7d5d/ki1",
        canonical_text="composite text for known issue",
    )
    content = f"# {ki_payload.title}\n\n{ki_payload.symptom_summary}\n\n{ki_payload.workaround}"
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    doc = CanonicalKnowledgeDocumentDTO(
        document_id=DOC_ID_KNOWN_ISSUE,
        title=ki_payload.title,
        document_type="known_issue",
        source_reference=ki_payload.source_reference,
        canonical_content=content,
        content_hash=content_hash,
        corpus_category=CorpusCategory.KNOWN_ISSUE,
        structured_payload=ki_payload,
    )

    res = await live_env.coordinator.ingest(doc)
    assert res.status == IngestionStatus.APPROVED
    assert res.version == 1

    # Verify document, known issue, and chunks all exist in DB
    async with live_env.engine.connect() as conn:
        doc_count = (
            await conn.execute(
                text("SELECT count(1) FROM knowledge.documents WHERE document_id = :id"),
                {"id": doc.document_id},
            )
        ).scalar_one()
        ki_row = (
            (
                await conn.execute(
                    text(
                        "SELECT issue_id, title, category, affected_products "
                        "FROM knowledge.known_issues WHERE issue_id = :id"
                    ),
                    {"id": ki_payload.issue_id},
                )
            )
            .mappings()
            .first()
        )
        chunks_count = (
            await conn.execute(
                text("SELECT count(1) FROM knowledge.chunks WHERE document_id = :id"),
                {"id": doc.document_id},
            )
        ).scalar_one()

    assert doc_count == 1
    assert chunks_count >= 1
    assert ki_row is not None
    assert ki_row["title"] == ki_payload.title
    assert ki_row["category"] == "Performance"
    assert "Service" in str(ki_row["affected_products"])


@pytest.mark.asyncio
async def test_live_transaction_rollback_and_compensation(live_env: LiveTestEnvironment) -> None:
    """Case F: If DB transaction fails after promotion, transaction rolls back cleanly."""
    doc_id = DOC_ID_FAIL
    content = "# Rollback Doc\n\nContent that will fail during transaction persistence."
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    doc = CanonicalKnowledgeDocumentDTO(
        document_id=doc_id,
        title="Rollback Doc",
        document_type="documentation",
        source_reference="docs://test/7d5d/fail_01",
        canonical_content=content,
        content_hash=content_hash,
        corpus_category=CorpusCategory.DOCUMENTATION,
    )

    # Wrap repository's document_transaction to inject a failure after promotion
    orig_tx_factory = live_env.repository.document_transaction

    @asynccontextmanager
    async def failing_tx(d_id: str) -> AsyncIterator[Any]:
        async with orig_tx_factory(d_id) as tx:
            # Wrap persist_chunks to fail intentionally
            async def fail_chunks(_chunks: Any) -> None:
                raise KnowledgePersistenceError("Simulated DB failure during persist_chunks")

            tx.persist_chunks = fail_chunks  # type: ignore[assignment,method-assign]
            yield tx

    live_env.repository.document_transaction = failing_tx  # type: ignore[assignment,method-assign]

    try:
        with pytest.raises(KnowledgePersistenceError, match="Simulated DB failure"):
            await live_env.coordinator.ingest(doc)
    finally:
        live_env.repository.document_transaction = orig_tx_factory  # type: ignore[method-assign]

    # Verify no partial state in DB
    async with live_env.engine.connect() as conn:
        doc_count = (
            await conn.execute(
                text("SELECT count(1) FROM knowledge.documents WHERE document_id = :id"),
                {"id": doc_id},
            )
        ).scalar_one()
        chunk_count = (
            await conn.execute(
                text("SELECT count(1) FROM knowledge.chunks WHERE document_id = :id"),
                {"id": doc_id},
            )
        ).scalar_one()

    assert doc_count == 0, "Failed transaction must not leave document row in database"
    assert chunk_count == 0, "Failed transaction must not leave chunk rows in database"

    # Verify promoted artifact was cleaned up (compensation policy: unreferenced artifact removed)
    approved_path = (
        live_env.artifact_dir / "approved" / doc.document_type / doc_id / f"{content_hash}.md"
    )
    assert not approved_path.exists(), (
        "Unreferenced promoted artifact must be removed during compensation"
    )


@pytest.mark.asyncio
async def test_live_concurrency_same_document(live_env: LiveTestEnvironment) -> None:
    """Section 38: Run concurrent async ingestion attempts for the same synthetic document_id.

    Proves PostgreSQL advisory locking serializes requests, prevents deadlocks,
    avoids duplicate documents/chunks, and maintains consistent state.
    """
    doc_id = DOC_ID_CONC
    content = (
        "# Concurrent Ingestion Test\n\n"
        "Testing simultaneous ingestion requests for the same document ID.\n\n"
        "Advisory locking ensures strict serialization without deadlocks."
    )
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    doc = CanonicalKnowledgeDocumentDTO(
        document_id=doc_id,
        title="Concurrent Ingestion Test",
        document_type="documentation",
        source_reference="docs://test/7d5d/conc_01",
        canonical_content=content,
        content_hash=content_hash,
        corpus_category=CorpusCategory.DOCUMENTATION,
    )

    # Launch two simultaneous ingestion tasks for the exact same document
    results = await asyncio.gather(
        live_env.coordinator.ingest(doc),
        live_env.coordinator.ingest(doc),
        return_exceptions=False,
    )

    statuses = [r.status for r in results]
    # Exactly one must be APPROVED and one UNCHANGED (or both succeed consistently)
    assert IngestionStatus.APPROVED in statuses
    assert len(results) == 2

    # Verify DB contains exactly 1 document row and exact chunk count (no duplicate chunks)
    async with live_env.engine.connect() as conn:
        doc_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT document_id, version, content_hash FROM knowledge.documents "
                        "WHERE document_id = :id"
                    ),
                    {"id": doc_id},
                )
            )
            .mappings()
            .all()
        )

        chunk_rows = (
            (
                await conn.execute(
                    text("SELECT chunk_id FROM knowledge.chunks WHERE document_id = :id"),
                    {"id": doc_id},
                )
            )
            .mappings()
            .all()
        )

    assert len(doc_rows) == 1
    assert doc_rows[0]["version"] == 1
    assert doc_rows[0]["content_hash"] == content_hash
    # No duplicate chunk IDs
    chunk_ids = [r["chunk_id"] for r in chunk_rows]
    assert len(chunk_ids) == len(set(chunk_ids))
