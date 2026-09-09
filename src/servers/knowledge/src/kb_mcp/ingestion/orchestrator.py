"""Knowledge Ingestion Coordinator orchestrating chunking, embeddings, and persistence."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

from kb_mcp.contracts.constants import (
    EMBEDDING_BATCH_CEILING,
    EMBEDDING_DIMENSION,
    MAX_CHUNKS_PER_DOCUMENT,
)
from kb_mcp.contracts.errors import (
    EmbeddingDimensionError,
    EmbeddingInferenceError,
    KnowledgeChunkingError,
    KnowledgeIngestionError,
)
from kb_mcp.contracts.ingestion import (
    CanonicalKnowledgeDocumentDTO,
    EmbeddedChunkDTO,
    IngestionResultDTO,
    IngestionStatus,
    SanitizedKnownIssuePayloadDTO,
    SanitizedRunbookPayloadDTO,
    StagedArtifactToken,
)

if TYPE_CHECKING:
    from kb_mcp.contracts.ingestion import ChunkDraftDTO
    from kb_mcp.contracts.interfaces import (
        EmbeddingProvider,
        KnowledgeArtifactStore,
        KnowledgeIngestionRepository,
    )
    from kb_mcp.ingestion.chunking import DeterministicChunker

logger = logging.getLogger(__name__)


class KnowledgeIngestionCoordinator:
    """Orchestrates deterministic chunking, local embeddings, and transactional persistence.

    Enforces invariants:
    - Consumes ONLY CanonicalKnowledgeDocumentDTO (does not accept raw source bytes).
    - Chunking and embedding generation execute OUTSIDE database transactions.
    - PostgreSQL transaction-scoped advisory locking prevents concurrent document race conditions.
    - Atomically promotes artifact and commits DB state.
    - Applies fail-safe compensation if DB fails after artifact promotion.
    """

    def __init__(
        self,
        chunker: DeterministicChunker,
        embedding_provider: EmbeddingProvider,
        artifact_store: KnowledgeArtifactStore,
        repository: KnowledgeIngestionRepository,
        *,
        batch_ceiling: int = EMBEDDING_BATCH_CEILING,
    ) -> None:
        self._chunker = chunker
        self._embedding_provider = embedding_provider
        self._artifact_store = artifact_store
        self._repository = repository
        self._batch_ceiling = min(max(1, batch_ceiling), EMBEDDING_BATCH_CEILING)

    async def ingest(
        self,
        document: CanonicalKnowledgeDocumentDTO,
    ) -> IngestionResultDTO:
        """Ingest an approved canonical knowledge document.

        Args:
            document: Immutable canonical document to ingest.

        Returns:
            IngestionResultDTO with status APPROVED (if updated) or UNCHANGED (if identical).

        Raises:
            KnowledgeIngestionError: If input document is invalid.
            KnowledgeChunkingError: If chunking fails or bounds violated.
            EmbeddingError: If embedding inference fails.
            KnowledgePersistenceError: If database operations fail.
            KnowledgeArtifactError: If artifact store operations fail.
        """
        if not isinstance(document, CanonicalKnowledgeDocumentDTO):
            raise KnowledgeIngestionError(
                "KnowledgeIngestionCoordinator requires a CanonicalKnowledgeDocumentDTO instance."
            )

        # 1. Cheap fast-path check without holding locks unless matching hash is observed
        fast_path_result = await self._check_fast_path(document)
        if fast_path_result is not None:
            return fast_path_result

        # 2. Deterministic chunking (OUTSIDE database transaction)
        chunk_drafts = self._chunk_document(document)

        # 3. Local embedding inference in bounded batches (OUTSIDE database transaction)
        embedded_chunks = await self._embed_chunks(chunk_drafts)

        # 4. Stage artifact in temporary storage
        token = self._artifact_store.stage(document)

        # 5. Open transactional boundary with PostgreSQL transaction-scoped advisory lock
        promoted = False
        try:
            async with self._repository.document_transaction(document.document_id) as tx:
                locked_state = await tx.get_locked_document_state()
                if locked_state is not None and locked_state.content_hash == document.content_hash:
                    # Concurrent writer already committed this exact content
                    self._artifact_store.discard_staged(token)
                    logger.info(
                        "Document %s committed concurrently; skipping.",
                        document.document_id,
                    )
                    return IngestionResultDTO(
                        status=IngestionStatus.UNCHANGED,
                        document_id=document.document_id,
                        source_reference=document.source_reference,
                        content_hash=document.content_hash,
                        version=locked_state.version,
                        chunk_count=0,
                    )

                target_version = (locked_state.version + 1) if locked_state is not None else 1

                # Promote staged artifact to immutable content-addressed storage
                self._artifact_store.promote(token, document)
                promoted = True

                # Persist document metadata and canonical content
                await tx.persist_document(document, target_version)

                # Persist structured payload if runbook or known issue
                if isinstance(document.structured_payload, SanitizedRunbookPayloadDTO):
                    await tx.persist_runbook(document.structured_payload)
                elif isinstance(document.structured_payload, SanitizedKnownIssuePayloadDTO):
                    await tx.persist_known_issue(document.structured_payload)

                # Atomically replace chunks with verified embedded vectors
                await tx.persist_chunks(embedded_chunks)

            # Transaction successfully committed
            logger.info(
                "Successfully ingested document %s version %d with %d chunks.",
                document.document_id,
                target_version,
                len(embedded_chunks),
            )
            return IngestionResultDTO(
                status=IngestionStatus.APPROVED,
                document_id=document.document_id,
                source_reference=document.source_reference,
                content_hash=document.content_hash,
                version=target_version,
                chunk_count=len(embedded_chunks),
            )

        except Exception as exc:
            logger.error(
                "Ingestion failed for document %s: %s",
                document.document_id,
                type(exc).__name__,
            )
            await self._compensate_after_failure(document, token, promoted)
            raise

    async def _check_fast_path(
        self,
        document: CanonicalKnowledgeDocumentDTO,
    ) -> IngestionResultDTO | None:
        """Perform unlocked precheck followed by short locked verification if hash matches."""
        existing_state = await self._repository.get_document_state(document.document_id)
        if existing_state is None or existing_state.content_hash != document.content_hash:
            return None

        # Confirm under short transaction-scoped advisory lock to prevent race conditions
        async with self._repository.document_transaction(document.document_id) as tx:
            locked_state = await tx.get_locked_document_state()
            if locked_state is not None and locked_state.content_hash == document.content_hash:
                logger.info(
                    "Document %s is unchanged (version=%d); skipping ingestion.",
                    document.document_id,
                    locked_state.version,
                )
                return IngestionResultDTO(
                    status=IngestionStatus.UNCHANGED,
                    document_id=document.document_id,
                    source_reference=document.source_reference,
                    content_hash=document.content_hash,
                    version=locked_state.version,
                    chunk_count=0,
                )
        return None

    def _chunk_document(
        self,
        document: CanonicalKnowledgeDocumentDTO,
    ) -> tuple[ChunkDraftDTO, ...]:
        """Execute deterministic chunking with boundary validation."""
        chunk_drafts = self._chunker.chunk_document(document)
        if not chunk_drafts:
            raise KnowledgeChunkingError(
                f"Document {document.document_id} produced 0 chunks.",
                details={"document_id": document.document_id},
            )
        if len(chunk_drafts) > MAX_CHUNKS_PER_DOCUMENT:
            raise KnowledgeChunkingError(
                f"Document {document.document_id} exceeded maximum chunks limit "
                f"({len(chunk_drafts)} > {MAX_CHUNKS_PER_DOCUMENT}).",
                details={
                    "document_id": document.document_id,
                    "chunk_count": len(chunk_drafts),
                    "max_chunks": MAX_CHUNKS_PER_DOCUMENT,
                },
            )
        return chunk_drafts

    async def _embed_chunks(
        self,
        chunk_drafts: tuple[ChunkDraftDTO, ...],
    ) -> list[EmbeddedChunkDTO]:
        """Generate verified embeddings in bounded batches preserving order."""
        embedded_chunks: list[EmbeddedChunkDTO] = []
        for i in range(0, len(chunk_drafts), self._batch_ceiling):
            batch_drafts = chunk_drafts[i : i + self._batch_ceiling]
            texts = [draft.content for draft in batch_drafts]
            vectors = await self._embedding_provider.embed_documents(texts)
            if len(vectors) != len(batch_drafts):
                raise EmbeddingInferenceError(
                    f"Embedding count mismatch: expected {len(batch_drafts)}, got {len(vectors)}."
                )

            for draft, vec in zip(batch_drafts, vectors, strict=True):
                if len(vec) != EMBEDDING_DIMENSION:
                    raise EmbeddingDimensionError(
                        actual_dimension=len(vec),
                        expected_dimension=EMBEDDING_DIMENSION,
                    )
                for val in vec:
                    if not isinstance(val, (int, float)) or not math.isfinite(val):
                        raise EmbeddingInferenceError(
                            f"Embedding vector for chunk {draft.chunk_id} contains "
                            f"non-finite values."
                        )
                embedded_chunks.append(
                    EmbeddedChunkDTO(
                        chunk_id=draft.chunk_id,
                        document_id=draft.document_id,
                        chunk_index=draft.chunk_index,
                        content=draft.content,
                        embedding=vec,
                    )
                )
        return embedded_chunks

    async def _compensate_after_failure(
        self,
        document: CanonicalKnowledgeDocumentDTO,
        token: StagedArtifactToken,
        promoted: bool,
    ) -> None:
        """Apply three-state compensation policy on ingestion failure."""
        if not promoted:
            try:
                self._artifact_store.discard_staged(token)
            except Exception as discard_exc:
                logger.warning(
                    "Failed to discard staged artifact for document %s: %s",
                    document.document_id,
                    discard_exc,
                )
            return

        # Fail-safe compensation: on DB failure after artifact promotion, retain artifact
        # if referenced or if reference check query fails; remove unreferenced only if
        # confirmed unreferenced. Unknown is never treated as unreferenced.
        try:
            is_ref = await self._repository.is_document_hash_referenced(
                document.document_id, document.content_hash
            )
            if not is_ref:
                logger.info(
                    "Reverting unreferenced promoted artifact for %s (%s) after DB failure",
                    document.document_id,
                    document.content_hash,
                )
                self._artifact_store.remove_unreferenced(
                    document.document_type,
                    document.document_id,
                    document.content_hash,
                )
            else:
                logger.warning(
                    "Retaining promoted artifact for %s (%s): confirmed referenced in DB",
                    document.document_id,
                    document.content_hash,
                )
        except Exception as ref_exc:
            logger.warning(
                "Reference check failed during compensation for %s; "
                "retaining artifact (reconciliation required): %s",
                document.document_id,
                ref_exc,
            )
