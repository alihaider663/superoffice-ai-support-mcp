"""Bounded development-only sample Knowledge corpus seeder."""

from __future__ import annotations

import json
import logging
import math
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import Integer, String, bindparam, text

from kb_mcp.adapters.fastembed_provider import FastEmbedEmbeddingProvider
from kb_mcp.contracts.errors import (
    EmbeddingDimensionError,
    EmbeddingInputError,
)
from tests.fixtures.knowledge.sample_corpus import (
    get_sample_chunks,
    get_sample_documents,
    get_sample_known_issues,
    get_sample_runbooks,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from kb_mcp.contracts.interfaces import EmbeddingProvider

logger = logging.getLogger(__name__)

UPSERT_DOCUMENT_SQL = text(
    """
    INSERT INTO knowledge.documents (
        document_id, title, document_type, source_reference,
        canonical_content, content_hash, version, updated_at
    ) VALUES (
        :document_id, :title, :document_type, :source_reference,
        :canonical_content, :content_hash, :version, NOW()
    )
    ON CONFLICT (document_id) DO UPDATE SET
        title = EXCLUDED.title,
        document_type = EXCLUDED.document_type,
        source_reference = EXCLUDED.source_reference,
        canonical_content = EXCLUDED.canonical_content,
        content_hash = EXCLUDED.content_hash,
        version = EXCLUDED.version,
        updated_at = NOW();
    """
).bindparams(
    bindparam("document_id", type_=String()),
    bindparam("title", type_=String()),
    bindparam("document_type", type_=String()),
    bindparam("source_reference", type_=String()),
    bindparam("canonical_content", type_=String()),
    bindparam("content_hash", type_=String()),
    bindparam("version", type_=Integer()),
)

UPSERT_CHUNK_SQL = text(
    """
    INSERT INTO knowledge.chunks (
        chunk_id, document_id, chunk_index, content, embedding
    ) VALUES (
        :chunk_id, :document_id, :chunk_index, :content, :embedding
    )
    ON CONFLICT (chunk_id) DO UPDATE SET
        document_id = EXCLUDED.document_id,
        chunk_index = EXCLUDED.chunk_index,
        content = EXCLUDED.content,
        embedding = EXCLUDED.embedding;
    """
).bindparams(
    bindparam("chunk_id", type_=String()),
    bindparam("document_id", type_=String()),
    bindparam("chunk_index", type_=Integer()),
    bindparam("content", type_=String()),
    bindparam("embedding", type_=Vector(384)),
)

UPSERT_RUNBOOK_SQL = text(
    """
    INSERT INTO knowledge.runbooks (
        runbook_id, title, problem_description, diagnostic_steps,
        remediation_steps, product, verified_version, source_reference, updated_at
    ) VALUES (
        :runbook_id, :title, :problem_description, CAST(:diagnostic_steps AS jsonb),
        CAST(:remediation_steps AS jsonb), :product, :verified_version, :source_reference, NOW()
    )
    ON CONFLICT (runbook_id) DO UPDATE SET
        title = EXCLUDED.title,
        problem_description = EXCLUDED.problem_description,
        diagnostic_steps = EXCLUDED.diagnostic_steps,
        remediation_steps = EXCLUDED.remediation_steps,
        product = EXCLUDED.product,
        verified_version = EXCLUDED.verified_version,
        source_reference = EXCLUDED.source_reference,
        updated_at = NOW();
    """
).bindparams(
    bindparam("runbook_id", type_=String()),
    bindparam("title", type_=String()),
    bindparam("problem_description", type_=String()),
    bindparam("diagnostic_steps", type_=String()),
    bindparam("remediation_steps", type_=String()),
    bindparam("product", type_=String()),
    bindparam("verified_version", type_=String()),
    bindparam("source_reference", type_=String()),
)

UPSERT_KNOWN_ISSUE_SQL = text(
    """
    INSERT INTO knowledge.known_issues (
        issue_id, title, symptom_summary, root_cause_summary,
        workaround, permanent_fix_reference, affected_products,
        affected_versions, category, source_reference, updated_at
    ) VALUES (
        :issue_id, :title, :symptom_summary, :root_cause_summary,
        :workaround, :permanent_fix_reference, CAST(:affected_products AS jsonb),
        CAST(:affected_versions AS jsonb), :category, :source_reference, NOW()
    )
    ON CONFLICT (issue_id) DO UPDATE SET
        title = EXCLUDED.title,
        symptom_summary = EXCLUDED.symptom_summary,
        root_cause_summary = EXCLUDED.root_cause_summary,
        workaround = EXCLUDED.workaround,
        permanent_fix_reference = EXCLUDED.permanent_fix_reference,
        affected_products = EXCLUDED.affected_products,
        affected_versions = EXCLUDED.affected_versions,
        category = EXCLUDED.category,
        source_reference = EXCLUDED.source_reference,
        updated_at = NOW();
    """
).bindparams(
    bindparam("issue_id", type_=String()),
    bindparam("title", type_=String()),
    bindparam("symptom_summary", type_=String()),
    bindparam("root_cause_summary", type_=String()),
    bindparam("workaround", type_=String()),
    bindparam("permanent_fix_reference", type_=String()),
    bindparam("affected_products", type_=String()),
    bindparam("affected_versions", type_=String()),
    bindparam("category", type_=String()),
    bindparam("source_reference", type_=String()),
)


async def seed_sample_knowledge_corpus(
    engine: AsyncEngine,
    embedding_provider: EmbeddingProvider | None = None,
) -> dict[str, int]:
    """Seed the synthetic sample Knowledge corpus into the target database.

    Strictly bounded to the fixed sample definitions.
    Accepts no arbitrary files, content, or customer inputs.
    Validates embeddings for count (6), dimension (384), and finite values.
    Executes in a single database transaction. Idempotent on re-execution.
    """
    docs = get_sample_documents()
    chunks = get_sample_chunks()
    runbooks = get_sample_runbooks()
    known_issues = get_sample_known_issues()

    provider = embedding_provider or FastEmbedEmbeddingProvider()

    # 1. Generate embeddings for all sample chunks in a single bounded batch
    chunk_contents = [c.content for c in chunks]
    vectors = await provider.embed_documents(chunk_contents)

    # 2. Strict embedding validation
    if len(vectors) != len(chunks):
        raise EmbeddingInputError(
            f"Embedding vector count mismatch: expected {len(chunks)}, got {len(vectors)}."
        )

    for i, vec in enumerate(vectors):
        if len(vec) != 384:
            raise EmbeddingDimensionError(
                actual_dimension=len(vec),
                expected_dimension=384,
                details={"chunk_index": i, "chunk_id": chunks[i].chunk_id},
            )
        if not all(isinstance(val, (int, float)) and math.isfinite(val) for val in vec):
            raise EmbeddingInputError(
                f"Embedding vector for chunk {chunks[i].chunk_id} contains non-finite numbers."
            )

    # 3. Transactional persistence
    async with engine.begin() as conn:
        # Upsert documents
        for doc in docs:
            await conn.execute(
                UPSERT_DOCUMENT_SQL,
                {
                    "document_id": doc.document_id,
                    "title": doc.title,
                    "document_type": doc.document_type,
                    "source_reference": doc.source_reference,
                    "canonical_content": doc.canonical_content,
                    "content_hash": doc.content_hash,
                    "version": doc.version,
                },
            )

        # Upsert chunks with verified vectors
        for chunk, vec in zip(chunks, vectors, strict=True):
            await conn.execute(
                UPSERT_CHUNK_SQL,
                {
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "embedding": list(vec),
                },
            )

        # Upsert runbooks
        for rb in runbooks:
            await conn.execute(
                UPSERT_RUNBOOK_SQL,
                {
                    "runbook_id": rb.runbook_id,
                    "title": rb.title,
                    "problem_description": rb.problem_description,
                    "diagnostic_steps": json.dumps(list(rb.diagnostic_steps)),
                    "remediation_steps": json.dumps(list(rb.remediation_steps)),
                    "product": rb.product,
                    "verified_version": rb.verified_version,
                    "source_reference": rb.source_reference,
                },
            )

        # Upsert known issues
        for ki in known_issues:
            await conn.execute(
                UPSERT_KNOWN_ISSUE_SQL,
                {
                    "issue_id": ki.issue_id,
                    "title": ki.title,
                    "symptom_summary": ki.symptom_summary,
                    "root_cause_summary": ki.root_cause_summary,
                    "workaround": ki.workaround,
                    "permanent_fix_reference": ki.permanent_fix_reference,
                    "affected_products": json.dumps(list(ki.affected_products)),
                    "affected_versions": json.dumps(list(ki.affected_versions)),
                    "category": ki.category,
                    "source_reference": ki.source_reference,
                },
            )

    counts = {
        "documents": len(docs),
        "chunks": len(chunks),
        "runbooks": len(runbooks),
        "known_issues": len(known_issues),
    }
    logger.info(
        "sample_knowledge_corpus_seeded",
        extra=counts,
    )
    return counts


async def _run_dev_seeder() -> None:
    """CLI helper for development-only seeding using configured settings."""
    from kb_mcp.adapters.factory import create_knowledge_engine  # noqa: PLC0415
    from kb_mcp.settings import KnowledgeServerSettings  # noqa: PLC0415

    settings = KnowledgeServerSettings()
    if not settings.is_database_configured:
        raise RuntimeError("KNOWLEDGE_DATABASE_URL is not configured.")

    engine = create_knowledge_engine(settings)
    try:
        counts = await seed_sample_knowledge_corpus(engine)
        print("SEED_RESULT:", counts)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(_run_dev_seeder())
