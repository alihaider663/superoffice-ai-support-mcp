"""PostgreSQL implementation of Knowledge Ingestion Repository and Transaction boundary."""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, Integer, String, bindparam, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

from kb_mcp.contracts.errors import (
    KnowledgeChunkingError,
    KnowledgeIngestionError,
    KnowledgePersistenceError,
)
from kb_mcp.contracts.ingestion import (
    CanonicalKnowledgeDocumentDTO,
    DocumentStateDTO,
    EmbeddedChunkDTO,
    SanitizedKnownIssuePayloadDTO,
    SanitizedRunbookPayloadDTO,
)
from kb_mcp.contracts.interfaces import (
    KnowledgeIngestionRepository,
    KnowledgeIngestionTransaction,
)

logger = logging.getLogger(__name__)

# ============================================================================
# SQL Statements with Strict Typed Bindparams
# ============================================================================

GET_DOCUMENT_STATE_SQL = text(
    """
    SELECT document_id, content_hash, version
    FROM knowledge.documents
    WHERE document_id = :document_id
    LIMIT 1
    """
).bindparams(
    bindparam("document_id", type_=String()),
)

CHECK_DOCUMENT_HASH_SQL = text(
    """
    SELECT 1
    FROM knowledge.documents
    WHERE document_id = :document_id AND content_hash = :content_hash
    LIMIT 1
    """
).bindparams(
    bindparam("document_id", type_=String()),
    bindparam("content_hash", type_=String()),
)

ADVISORY_LOCK_SQL = text(
    """
    SELECT pg_advisory_xact_lock(:lock_key)
    """
).bindparams(
    bindparam("lock_key", type_=BigInteger()),
)

GET_LOCKED_DOCUMENT_STATE_SQL = text(
    """
    SELECT document_id, content_hash, version
    FROM knowledge.documents
    WHERE document_id = :document_id
    FOR UPDATE
    """
).bindparams(
    bindparam("document_id", type_=String()),
)

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

DELETE_CHUNKS_SQL = text(
    """
    DELETE FROM knowledge.chunks WHERE document_id = :document_id
    """
).bindparams(
    bindparam("document_id", type_=String()),
)

INSERT_CHUNK_SQL = text(
    """
    INSERT INTO knowledge.chunks (
        chunk_id, document_id, chunk_index, content, embedding
    ) VALUES (
        :chunk_id, :document_id, :chunk_index, :content, :embedding
    )
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
        remediation_steps, product, verified_version, last_reviewed,
        source_reference, updated_at
    ) VALUES (
        :runbook_id, :title, :problem_description, CAST(:diagnostic_steps AS jsonb),
        CAST(:remediation_steps AS jsonb), :product, :verified_version,
        :last_reviewed, :source_reference, NOW()
    )
    ON CONFLICT (runbook_id) DO UPDATE SET
        title = EXCLUDED.title,
        problem_description = EXCLUDED.problem_description,
        diagnostic_steps = EXCLUDED.diagnostic_steps,
        remediation_steps = EXCLUDED.remediation_steps,
        product = EXCLUDED.product,
        verified_version = EXCLUDED.verified_version,
        last_reviewed = EXCLUDED.last_reviewed,
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
    bindparam("last_reviewed", type_=DateTime(timezone=True)),
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


class _PostgresIngestionTransaction(KnowledgeIngestionTransaction):
    """Internal active transaction handle with advisory lock held."""

    def __init__(self, session: AsyncSession, document_id: str) -> None:
        self._session = session
        self._document_id = document_id
        self._is_active = False

    def _activate(self) -> None:
        self._is_active = True

    def _deactivate(self) -> None:
        self._is_active = False

    def _ensure_active(self) -> None:
        if not self._is_active:
            raise KnowledgePersistenceError(
                "Ingestion transaction is not active or has already closed.",
                details={"document_id": self._document_id},
            )

    async def get_locked_document_state(self) -> DocumentStateDTO | None:
        """Fetch locked document state under SELECT ... FOR UPDATE."""
        self._ensure_active()
        try:
            result = await self._session.execute(
                GET_LOCKED_DOCUMENT_STATE_SQL,
                {"document_id": self._document_id},
            )
            row = result.mappings().first()
            if row is None:
                return None
            return DocumentStateDTO(
                document_id=row["document_id"],
                content_hash=row["content_hash"],
                version=row["version"],
            )
        except Exception as exc:
            logger.error(
                "Failed to get locked document state for %s: %s",
                self._document_id,
                type(exc).__name__,
            )
            raise KnowledgePersistenceError(
                f"Failed to get locked document state for {self._document_id}: "
                f"{type(exc).__name__}",
                details={"document_id": self._document_id, "error_type": type(exc).__name__},
            ) from exc

    async def persist_document(
        self,
        document: CanonicalKnowledgeDocumentDTO,
        version: int,
    ) -> None:
        """Insert or update the canonical knowledge document."""
        self._ensure_active()
        try:
            await self._session.execute(
                UPSERT_DOCUMENT_SQL,
                {
                    "document_id": document.document_id,
                    "title": document.title,
                    "document_type": document.document_type,
                    "source_reference": document.source_reference,
                    "canonical_content": document.canonical_content,
                    "content_hash": document.content_hash,
                    "version": version,
                },
            )
        except Exception as exc:
            logger.error(
                "Failed to persist document %s: %s",
                document.document_id,
                type(exc).__name__,
            )
            raise KnowledgePersistenceError(
                f"Failed to persist document {document.document_id}: {type(exc).__name__}",
                details={"document_id": document.document_id, "error_type": type(exc).__name__},
            ) from exc

    async def persist_chunks(
        self,
        chunks: Sequence[EmbeddedChunkDTO],
    ) -> None:
        """Atomically replace chunks for this document with new embedded chunks."""
        self._ensure_active()
        try:
            # First delete all existing chunks for document
            await self._session.execute(
                DELETE_CHUNKS_SQL,
                {"document_id": self._document_id},
            )
            # Insert each new embedded chunk
            for chunk in chunks:
                await self._session.execute(
                    INSERT_CHUNK_SQL,
                    {
                        "chunk_id": chunk.chunk_id,
                        "document_id": chunk.document_id,
                        "chunk_index": chunk.chunk_index,
                        "content": chunk.content,
                        "embedding": list(chunk.embedding),
                    },
                )
        except Exception as exc:
            logger.error(
                "Failed to persist chunks for document %s: %s",
                self._document_id,
                type(exc).__name__,
            )
            raise KnowledgePersistenceError(
                f"Failed to persist chunks for document {self._document_id}: {type(exc).__name__}",
                details={"document_id": self._document_id, "error_type": type(exc).__name__},
            ) from exc

    async def persist_runbook(
        self,
        runbook: SanitizedRunbookPayloadDTO,
    ) -> None:
        """Upsert structured operational runbook record."""
        self._ensure_active()
        try:
            await self._session.execute(
                UPSERT_RUNBOOK_SQL,
                {
                    "runbook_id": runbook.runbook_id,
                    "title": runbook.title,
                    "problem_description": runbook.problem_description,
                    "diagnostic_steps": json.dumps(list(runbook.diagnostic_steps)),
                    "remediation_steps": json.dumps(list(runbook.remediation_steps)),
                    "product": runbook.product,
                    "verified_version": runbook.verified_version,
                    "last_reviewed": runbook.last_reviewed,
                    "source_reference": runbook.source_reference,
                },
            )
        except Exception as exc:
            logger.error(
                "Failed to persist runbook %s: %s",
                runbook.runbook_id,
                type(exc).__name__,
            )
            raise KnowledgePersistenceError(
                f"Failed to persist runbook {runbook.runbook_id}: {type(exc).__name__}",
                details={"runbook_id": runbook.runbook_id, "error_type": type(exc).__name__},
            ) from exc

    async def persist_known_issue(
        self,
        known_issue: SanitizedKnownIssuePayloadDTO,
    ) -> None:
        """Upsert structured known issue record."""
        self._ensure_active()
        try:
            await self._session.execute(
                UPSERT_KNOWN_ISSUE_SQL,
                {
                    "issue_id": known_issue.issue_id,
                    "title": known_issue.title,
                    "symptom_summary": known_issue.symptom_summary,
                    "root_cause_summary": known_issue.root_cause_summary,
                    "workaround": known_issue.workaround,
                    "permanent_fix_reference": known_issue.permanent_fix_reference,
                    "affected_products": json.dumps(list(known_issue.affected_products)),
                    "affected_versions": json.dumps(list(known_issue.affected_versions)),
                    "category": known_issue.category,
                    "source_reference": known_issue.source_reference,
                },
            )
        except Exception as exc:
            logger.error(
                "Failed to persist known issue %s: %s",
                known_issue.issue_id,
                type(exc).__name__,
            )
            raise KnowledgePersistenceError(
                f"Failed to persist known issue {known_issue.issue_id}: {type(exc).__name__}",
                details={"issue_id": known_issue.issue_id, "error_type": type(exc).__name__},
            ) from exc


class PostgresKnowledgeIngestionRepository(KnowledgeIngestionRepository):
    """PostgreSQL implementation of the KnowledgeIngestionRepository protocol."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | AsyncEngine,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        if isinstance(session_factory, AsyncEngine):
            self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
                bind=session_factory, expire_on_commit=False
            )
        else:
            self._sessionmaker = session_factory

        self._timeout_seconds = timeout_seconds

    async def get_document_state(self, document_id: str) -> DocumentStateDTO | None:
        """Cheap read-only check of document state without holding transaction locks."""
        if not document_id or not isinstance(document_id, str):
            return None
        try:
            async with self._sessionmaker() as session:
                result = await session.execute(
                    GET_DOCUMENT_STATE_SQL,
                    {"document_id": document_id},
                )
                row = result.mappings().first()
                if row is None:
                    return None
                return DocumentStateDTO(
                    document_id=row["document_id"],
                    content_hash=row["content_hash"],
                    version=row["version"],
                )
        except Exception as exc:
            logger.error(
                "Knowledge get_document_state failed: %s",
                type(exc).__name__,
                extra={"document_id": document_id},
            )
            raise KnowledgePersistenceError(
                f"Failed to get document state for {document_id}: {type(exc).__name__}",
                details={"document_id": document_id, "error_type": type(exc).__name__},
            ) from exc

    async def is_document_hash_referenced(self, document_id: str, content_hash: str) -> bool:
        """Check if an approved content hash is referenced by committed active knowledge."""
        if not document_id or not content_hash:
            return False
        try:
            async with self._sessionmaker() as session:
                result = await session.execute(
                    CHECK_DOCUMENT_HASH_SQL,
                    {"document_id": document_id, "content_hash": content_hash},
                )
                return result.scalar() is not None
        except Exception as exc:
            logger.error(
                "Knowledge is_document_hash_referenced failed: %s",
                type(exc).__name__,
                extra={"document_id": document_id, "content_hash": content_hash},
            )
            raise KnowledgePersistenceError(
                f"Failed to check if document hash is referenced: {type(exc).__name__}",
                details={
                    "document_id": document_id,
                    "content_hash": content_hash,
                    "error_type": type(exc).__name__,
                },
            ) from exc

    @asynccontextmanager
    async def document_transaction(
        self, document_id: str
    ) -> AsyncIterator[KnowledgeIngestionTransaction]:
        """Open a transaction-scoped boundary with a document-scoped PostgreSQL advisory lock."""
        if not document_id or not isinstance(document_id, str):
            raise KnowledgePersistenceError(
                "Invalid document_id provided for document_transaction.",
                details={"document_id": document_id},
            )

        # Derive signed 64-bit bigint from first 8 bytes of SHA256(document_id)
        lock_key = int.from_bytes(
            hashlib.sha256(document_id.encode("utf-8")).digest()[:8],
            byteorder="big",
            signed=True,
        )

        session = self._sessionmaker()
        tx = _PostgresIngestionTransaction(session, document_id)
        try:
            async with session.begin():
                # Acquire transaction-scoped advisory lock immediately
                await session.execute(
                    ADVISORY_LOCK_SQL,
                    {"lock_key": lock_key},
                )
                tx._activate()
                try:
                    yield tx
                finally:
                    tx._deactivate()
        except (KnowledgeIngestionError, KnowledgeChunkingError, KnowledgePersistenceError):
            raise
        except Exception as exc:
            logger.error(
                "Knowledge database transaction failed for document %s: %s",
                document_id,
                type(exc).__name__,
            )
            raise KnowledgePersistenceError(
                f"Database transaction failed for document {document_id}: {type(exc).__name__}",
                details={"document_id": document_id, "error_type": type(exc).__name__},
            ) from exc
        finally:
            await session.close()
