"""Unit tests for KnowledgeIngestionCoordinator (Gate 7D.5D)."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from kb_mcp.contracts.errors import (
    EmbeddingDimensionError,
    EmbeddingInferenceError,
    KnowledgeIngestionError,
    KnowledgePersistenceError,
)
from kb_mcp.contracts.ingestion import (
    AdmissionSourceInputDTO,
    CanonicalKnowledgeDocumentDTO,
    ChunkDraftDTO,
    CorpusCategory,
    DocumentStateDTO,
    EmbeddedChunkDTO,
    IngestionSourceKind,
    IngestionStatus,
    SanitizedKnownIssuePayloadDTO,
    SanitizedRunbookPayloadDTO,
    StagedArtifactToken,
)
from kb_mcp.contracts.interfaces import (
    EmbeddingProvider,
    KnowledgeArtifactStore,
    KnowledgeIngestionRepository,
    KnowledgeIngestionTransaction,
)
from kb_mcp.ingestion.chunking import DeterministicChunker
from kb_mcp.ingestion.orchestrator import KnowledgeIngestionCoordinator


def create_sample_canonical_doc(
    document_id: str = "doc_test1122334455667788",
    title: str = "Test Title",
    content: str = "# Test Title\n\nContent for testing.",
    content_hash: str = "1122334455667788112233445566778811223344556677881122334455667788",
    structured_payload: Any = None,
) -> CanonicalKnowledgeDocumentDTO:
    return CanonicalKnowledgeDocumentDTO(
        document_id=document_id,
        title=title,
        document_type="documentation",
        source_reference=f"docs://{document_id}",
        canonical_content=content,
        content_hash=content_hash,
        corpus_category=CorpusCategory.DOCUMENTATION,
        structured_payload=structured_payload,
    )


class MockTransaction(KnowledgeIngestionTransaction):
    """Mock implementation of KnowledgeIngestionTransaction."""

    def __init__(self, locked_state: DocumentStateDTO | None = None) -> None:
        self.locked_state = locked_state
        self.persist_document_calls: list[tuple[CanonicalKnowledgeDocumentDTO, int]] = []
        self.persist_chunks_calls: list[Sequence[EmbeddedChunkDTO]] = []
        self.persist_runbook_calls: list[SanitizedRunbookPayloadDTO] = []
        self.persist_known_issue_calls: list[SanitizedKnownIssuePayloadDTO] = []

    async def get_locked_document_state(self) -> DocumentStateDTO | None:
        return self.locked_state

    async def persist_document(
        self,
        document: CanonicalKnowledgeDocumentDTO,
        version: int,
    ) -> None:
        self.persist_document_calls.append((document, version))

    async def persist_chunks(
        self,
        chunks: Sequence[EmbeddedChunkDTO],
    ) -> None:
        self.persist_chunks_calls.append(chunks)

    async def persist_runbook(
        self,
        runbook: SanitizedRunbookPayloadDTO,
    ) -> None:
        self.persist_runbook_calls.append(runbook)

    async def persist_known_issue(
        self,
        known_issue: SanitizedKnownIssuePayloadDTO,
    ) -> None:
        self.persist_known_issue_calls.append(known_issue)


class MockRepository(KnowledgeIngestionRepository):
    """Mock implementation of KnowledgeIngestionRepository."""

    def __init__(
        self,
        state: DocumentStateDTO | None = None,
        locked_state: DocumentStateDTO | None = None,
        is_referenced: bool = False,
    ) -> None:
        self.current_state = state
        self.tx = MockTransaction(locked_state if locked_state is not None else state)
        self.is_referenced = is_referenced
        self.get_state_calls: list[str] = []
        self.is_ref_calls: list[tuple[str, str]] = []

    async def get_document_state(self, document_id: str) -> DocumentStateDTO | None:
        self.get_state_calls.append(document_id)
        return self.current_state

    async def is_document_hash_referenced(self, document_id: str, content_hash: str) -> bool:
        self.is_ref_calls.append((document_id, content_hash))
        return self.is_referenced

    @asynccontextmanager
    async def document_transaction(
        self, _document_id: str
    ) -> AsyncIterator[KnowledgeIngestionTransaction]:
        yield self.tx


@pytest.mark.asyncio
async def test_coordinator_rejects_non_canonical_document() -> None:
    """Coordinator rejects non-CanonicalKnowledgeDocumentDTO with KnowledgeIngestionError."""
    coordinator = KnowledgeIngestionCoordinator(
        chunker=MagicMock(),
        embedding_provider=MagicMock(),
        artifact_store=MagicMock(),
        repository=MagicMock(),
    )
    with pytest.raises(KnowledgeIngestionError, match="requires a CanonicalKnowledgeDocumentDTO"):
        await coordinator.ingest({"invalid": "payload"})  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_coordinator_fast_path_unchanged() -> None:
    """When document content hash matches DB state, returns UNCHANGED without chunking."""
    doc = create_sample_canonical_doc()
    state = DocumentStateDTO(
        document_id=doc.document_id,
        content_hash=doc.content_hash,
        version=1,
    )
    repo = MockRepository(state=state, locked_state=state)
    chunker = MagicMock(spec=DeterministicChunker)
    embedder = AsyncMock(spec=EmbeddingProvider)
    store = MagicMock(spec=KnowledgeArtifactStore)

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    result = await coordinator.ingest(doc)

    assert result.status == IngestionStatus.UNCHANGED
    assert result.version == 1
    assert result.chunk_count == 0
    assert result.content_hash == doc.content_hash

    # Chunker, embedder, and store staging must NOT be called
    chunker.chunk_document.assert_not_called()
    embedder.embed_documents.assert_not_called()
    store.stage.assert_not_called()


@pytest.mark.asyncio
async def test_coordinator_successful_new_document_ingestion() -> None:
    """Ingesting a new document chunks, embeds, stages, promotes, and persists version 1."""
    doc = create_sample_canonical_doc()
    repo = MockRepository(state=None, locked_state=None)

    chunker = MagicMock(spec=DeterministicChunker)
    draft = ChunkDraftDTO(
        chunk_id=f"{doc.document_id}_c0000",
        document_id=doc.document_id,
        chunk_index=0,
        content="Test content",
    )
    chunker.chunk_document.return_value = (draft,)

    embedder = AsyncMock(spec=EmbeddingProvider)
    dummy_vec = tuple([0.1] * 384)
    embedder.embed_documents.return_value = (dummy_vec,)

    store = MagicMock(spec=KnowledgeArtifactStore)
    token = StagedArtifactToken(
        staging_id="stage_123",
        document_id=doc.document_id,
        document_type=doc.document_type,
        content_hash=doc.content_hash,
    )
    store.stage.return_value = token

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    result = await coordinator.ingest(doc)

    assert result.status == IngestionStatus.APPROVED
    assert result.version == 1
    assert result.chunk_count == 1
    assert result.document_id == doc.document_id

    # Verify calls
    chunker.chunk_document.assert_called_once_with(doc)
    embedder.embed_documents.assert_called_once_with(["Test content"])
    store.stage.assert_called_once_with(doc)
    store.promote.assert_called_once_with(token, doc)
    assert len(repo.tx.persist_document_calls) == 1
    assert repo.tx.persist_document_calls[0] == (doc, 1)
    assert len(repo.tx.persist_chunks_calls) == 1
    assert repo.tx.persist_chunks_calls[0][0].chunk_id == draft.chunk_id


@pytest.mark.asyncio
async def test_coordinator_successful_update_increments_version() -> None:
    """Ingesting an existing document with updated hash increments version to N + 1."""
    doc = create_sample_canonical_doc(
        content_hash="2233445566778899223344556677889922334455667788992233445566778899"
    )
    old_state = DocumentStateDTO(
        document_id=doc.document_id,
        content_hash="0" * 64,
        version=2,
    )
    repo = MockRepository(state=old_state, locked_state=old_state)

    chunker = MagicMock(spec=DeterministicChunker)
    draft = ChunkDraftDTO(
        chunk_id=f"{doc.document_id}_c0000",
        document_id=doc.document_id,
        chunk_index=0,
        content="Updated content",
    )
    chunker.chunk_document.return_value = (draft,)

    embedder = AsyncMock(spec=EmbeddingProvider)
    embedder.embed_documents.return_value = (tuple([0.2] * 384),)

    store = MagicMock(spec=KnowledgeArtifactStore)
    token = StagedArtifactToken(
        staging_id="stage_456",
        document_id=doc.document_id,
        document_type=doc.document_type,
        content_hash=doc.content_hash,
    )
    store.stage.return_value = token

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    result = await coordinator.ingest(doc)

    assert result.status == IngestionStatus.APPROVED
    assert result.version == 3
    assert repo.tx.persist_document_calls[0] == (doc, 3)


@pytest.mark.asyncio
async def test_coordinator_structured_payload_persistence() -> None:
    """Structured payloads (Runbook / Known Issue) are persisted within transaction."""
    runbook_payload = SanitizedRunbookPayloadDTO(
        source_name="rb.json",
        runbook_id="rb_123",
        title="Sample Runbook",
        problem_description="Problem desc",
        diagnostic_steps=("step 1", "step 2"),
        remediation_steps=("fix 1", "fix 2"),
        source_reference="runbook://rb_123",
        canonical_text="composite text",
    )
    doc = create_sample_canonical_doc(structured_payload=runbook_payload)
    repo = MockRepository(state=None, locked_state=None)

    chunker = MagicMock(spec=DeterministicChunker)
    chunker.chunk_document.return_value = (
        ChunkDraftDTO(
            chunk_id=f"{doc.document_id}_c0000",
            document_id=doc.document_id,
            chunk_index=0,
            content="Runbook text",
        ),
    )
    embedder = AsyncMock(spec=EmbeddingProvider)
    embedder.embed_documents.return_value = (tuple([0.1] * 384),)
    store = MagicMock(spec=KnowledgeArtifactStore)
    store.stage.return_value = StagedArtifactToken(
        staging_id="stage_rb",
        document_id=doc.document_id,
        document_type=doc.document_type,
        content_hash=doc.content_hash,
    )

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    await coordinator.ingest(doc)
    assert len(repo.tx.persist_runbook_calls) == 1
    assert repo.tx.persist_runbook_calls[0] == runbook_payload


@pytest.mark.asyncio
async def test_coordinator_concurrency_race_returns_unchanged() -> None:
    """If concurrent writer commits same hash between precheck and lock, return UNCHANGED."""
    doc = create_sample_canonical_doc()
    # Precheck sees None, but locked_state shows committed same hash!
    locked_state = DocumentStateDTO(
        document_id=doc.document_id,
        content_hash=doc.content_hash,
        version=1,
    )
    repo = MockRepository(state=None, locked_state=locked_state)

    chunker = MagicMock(spec=DeterministicChunker)
    chunker.chunk_document.return_value = (
        ChunkDraftDTO(
            chunk_id=f"{doc.document_id}_c0000",
            document_id=doc.document_id,
            chunk_index=0,
            content="Text",
        ),
    )
    embedder = AsyncMock(spec=EmbeddingProvider)
    embedder.embed_documents.return_value = (tuple([0.1] * 384),)
    store = MagicMock(spec=KnowledgeArtifactStore)
    token = StagedArtifactToken(
        staging_id="stage_race",
        document_id=doc.document_id,
        document_type=doc.document_type,
        content_hash=doc.content_hash,
    )
    store.stage.return_value = token

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    result = await coordinator.ingest(doc)

    assert result.status == IngestionStatus.UNCHANGED
    assert result.version == 1
    assert result.chunk_count == 0
    # Staged artifact discarded without promotion or DB mutation
    store.discard_staged.assert_called_once_with(token)
    store.promote.assert_not_called()
    assert len(repo.tx.persist_document_calls) == 0


@pytest.mark.asyncio
async def test_coordinator_rollback_before_promotion() -> None:
    """Failure before promotion discards staged file and re-raises."""
    doc = create_sample_canonical_doc()
    repo = MockRepository(state=None)
    # Fail locked state fetch
    repo.tx.get_locked_document_state = AsyncMock(  # type: ignore[method-assign]
        side_effect=KnowledgePersistenceError("Lock query failed")
    )

    chunker = MagicMock(spec=DeterministicChunker)
    chunker.chunk_document.return_value = (
        ChunkDraftDTO(
            chunk_id=f"{doc.document_id}_c0000",
            document_id=doc.document_id,
            chunk_index=0,
            content="Text",
        ),
    )
    embedder = AsyncMock(spec=EmbeddingProvider)
    embedder.embed_documents.return_value = (tuple([0.1] * 384),)
    store = MagicMock(spec=KnowledgeArtifactStore)
    token = StagedArtifactToken(
        staging_id="stage_fail",
        document_id=doc.document_id,
        document_type=doc.document_type,
        content_hash=doc.content_hash,
    )
    store.stage.return_value = token

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    with pytest.raises(KnowledgePersistenceError, match="Lock query failed"):
        await coordinator.ingest(doc)

    store.discard_staged.assert_called_once_with(token)
    store.promote.assert_not_called()
    store.remove_unreferenced.assert_not_called()


@pytest.mark.asyncio
async def test_coordinator_rollback_after_promotion_unreferenced_cleaned() -> None:
    """Failure after promotion when unreferenced removes promoted artifact."""
    doc = create_sample_canonical_doc()
    repo = MockRepository(state=None, locked_state=None, is_referenced=False)
    # Fail during persist_chunks
    repo.tx.persist_chunks = AsyncMock(  # type: ignore[method-assign]
        side_effect=KnowledgePersistenceError("Chunks insert failed")
    )

    chunker = MagicMock(spec=DeterministicChunker)
    chunker.chunk_document.return_value = (
        ChunkDraftDTO(
            chunk_id=f"{doc.document_id}_c0000",
            document_id=doc.document_id,
            chunk_index=0,
            content="Text",
        ),
    )
    embedder = AsyncMock(spec=EmbeddingProvider)
    embedder.embed_documents.return_value = (tuple([0.1] * 384),)
    store = MagicMock(spec=KnowledgeArtifactStore)
    token = StagedArtifactToken(
        staging_id="stage_promo_fail",
        document_id=doc.document_id,
        document_type=doc.document_type,
        content_hash=doc.content_hash,
    )
    store.stage.return_value = token

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    with pytest.raises(KnowledgePersistenceError, match="Chunks insert failed"):
        await coordinator.ingest(doc)

    store.promote.assert_called_once_with(token, doc)
    # Unreferenced cleanup must be invoked
    store.remove_unreferenced.assert_called_once_with(
        doc.document_type, doc.document_id, doc.content_hash
    )


@pytest.mark.asyncio
async def test_coordinator_rollback_after_promotion_referenced_retained() -> None:
    """Failure after promotion retains artifact if database check confirms it is referenced."""
    doc = create_sample_canonical_doc()
    repo = MockRepository(state=None, locked_state=None, is_referenced=True)
    repo.tx.persist_chunks = AsyncMock(  # type: ignore[method-assign]
        side_effect=KnowledgePersistenceError("Chunks insert failed")
    )

    chunker = MagicMock(spec=DeterministicChunker)
    chunker.chunk_document.return_value = (
        ChunkDraftDTO(
            chunk_id=f"{doc.document_id}_c0000",
            document_id=doc.document_id,
            chunk_index=0,
            content="Text",
        ),
    )
    embedder = AsyncMock(spec=EmbeddingProvider)
    embedder.embed_documents.return_value = (tuple([0.1] * 384),)
    store = MagicMock(spec=KnowledgeArtifactStore)
    token = StagedArtifactToken(
        staging_id="stage_ref_retained",
        document_id=doc.document_id,
        document_type=doc.document_type,
        content_hash=doc.content_hash,
    )
    store.stage.return_value = token

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    with pytest.raises(KnowledgePersistenceError, match="Chunks insert failed"):
        await coordinator.ingest(doc)

    store.promote.assert_called_once_with(token, doc)
    store.remove_unreferenced.assert_not_called()


@pytest.mark.asyncio
async def test_coordinator_embedding_batch_ceiling() -> None:
    """Coordinator batches embedding requests respecting EMBEDDING_BATCH_CEILING = 32."""
    doc = create_sample_canonical_doc()
    repo = MockRepository(state=None, locked_state=None)

    # 70 drafts -> 32 + 32 + 6
    drafts = [
        ChunkDraftDTO(
            chunk_id=f"{doc.document_id}_c{i:04d}",
            document_id=doc.document_id,
            chunk_index=i,
            content=f"Draft content {i}",
        )
        for i in range(70)
    ]
    chunker = MagicMock(spec=DeterministicChunker)
    chunker.chunk_document.return_value = tuple(drafts)

    embedder = AsyncMock(spec=EmbeddingProvider)
    dummy_vec = tuple([0.1] * 384)
    embedder.embed_documents.side_effect = [
        tuple([dummy_vec] * 32),
        tuple([dummy_vec] * 32),
        tuple([dummy_vec] * 6),
    ]

    store = MagicMock(spec=KnowledgeArtifactStore)
    token = StagedArtifactToken(
        staging_id="stage_batch",
        document_id=doc.document_id,
        document_type=doc.document_type,
        content_hash=doc.content_hash,
    )
    store.stage.return_value = token

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    result = await coordinator.ingest(doc)

    assert result.status == IngestionStatus.APPROVED
    assert result.chunk_count == 70
    assert embedder.embed_documents.call_count == 3
    # Check sizes passed to embed_documents
    call_args_list = embedder.embed_documents.call_args_list
    assert len(call_args_list[0][0][0]) == 32
    assert len(call_args_list[1][0][0]) == 32
    assert len(call_args_list[2][0][0]) == 6


@pytest.mark.asyncio
async def test_coordinator_embed_query_never_called() -> None:
    """Ingestion uses embed_documents exclusively; embed_query is never invoked."""
    doc = create_sample_canonical_doc()
    repo = MockRepository(state=None, locked_state=None)

    chunker = MagicMock(spec=DeterministicChunker)
    chunker.chunk_document.return_value = (
        ChunkDraftDTO(
            chunk_id=f"{doc.document_id}_c0000",
            document_id=doc.document_id,
            chunk_index=0,
            content="Content",
        ),
    )
    embedder = AsyncMock(spec=EmbeddingProvider)
    embedder.embed_documents.return_value = (tuple([0.1] * 384),)
    embedder.embed_query = AsyncMock()

    store = MagicMock(spec=KnowledgeArtifactStore)
    store.stage.return_value = StagedArtifactToken(
        staging_id="stage_eq",
        document_id=doc.document_id,
        document_type=doc.document_type,
        content_hash=doc.content_hash,
    )

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )
    await coordinator.ingest(doc)

    assert embedder.embed_documents.call_count == 1
    embedder.embed_query.assert_not_called()


@pytest.mark.asyncio
async def test_coordinator_embedding_validation_count_mismatch() -> None:
    """Embedding provider returning wrong vector count raises EmbeddingInferenceError."""
    doc = create_sample_canonical_doc()
    repo = MockRepository(state=None, locked_state=None)

    chunker = MagicMock(spec=DeterministicChunker)
    chunker.chunk_document.return_value = (
        ChunkDraftDTO(
            chunk_id=f"{doc.document_id}_c0000",
            document_id=doc.document_id,
            chunk_index=0,
            content="Content",
        ),
    )
    embedder = AsyncMock(spec=EmbeddingProvider)
    # Returns 2 vectors for 1 draft
    embedder.embed_documents.return_value = (tuple([0.1] * 384), tuple([0.2] * 384))

    store = MagicMock(spec=KnowledgeArtifactStore)
    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    with pytest.raises(EmbeddingInferenceError, match="Embedding count mismatch"):
        await coordinator.ingest(doc)

    store.stage.assert_not_called()
    assert len(repo.tx.persist_document_calls) == 0


@pytest.mark.asyncio
async def test_coordinator_embedding_validation_dimension_mismatch() -> None:
    """Embedding vector with dimension != 384 raises EmbeddingDimensionError."""
    doc = create_sample_canonical_doc()
    repo = MockRepository(state=None, locked_state=None)

    chunker = MagicMock(spec=DeterministicChunker)
    chunker.chunk_document.return_value = (
        ChunkDraftDTO(
            chunk_id=f"{doc.document_id}_c0000",
            document_id=doc.document_id,
            chunk_index=0,
            content="Content",
        ),
    )
    embedder = AsyncMock(spec=EmbeddingProvider)
    # 383 dimensions instead of 384
    embedder.embed_documents.return_value = (tuple([0.1] * 383),)

    store = MagicMock(spec=KnowledgeArtifactStore)
    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    with pytest.raises(EmbeddingDimensionError, match="expected 384, got 383"):
        await coordinator.ingest(doc)

    store.stage.assert_not_called()


@pytest.mark.asyncio
async def test_coordinator_embedding_validation_nan_and_inf() -> None:
    """Embedding vectors containing NaN or Infinity fail closed."""
    doc = create_sample_canonical_doc()
    repo = MockRepository(state=None, locked_state=None)

    chunker = MagicMock(spec=DeterministicChunker)
    chunker.chunk_document.return_value = (
        ChunkDraftDTO(
            chunk_id=f"{doc.document_id}_c0000",
            document_id=doc.document_id,
            chunk_index=0,
            content="Content",
        ),
    )

    # Test NaN
    nan_vec = [0.1] * 383 + [float("nan")]
    embedder_nan = AsyncMock(spec=EmbeddingProvider)
    embedder_nan.embed_documents.return_value = (tuple(nan_vec),)

    store = MagicMock(spec=KnowledgeArtifactStore)
    coordinator_nan = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder_nan,
        artifact_store=store,
        repository=repo,
    )
    with pytest.raises(EmbeddingInferenceError, match="contains non-finite values"):
        await coordinator_nan.ingest(doc)

    # Test Infinity
    inf_vec = [0.1] * 383 + [float("inf")]
    embedder_inf = AsyncMock(spec=EmbeddingProvider)
    embedder_inf.embed_documents.return_value = (tuple(inf_vec),)

    coordinator_inf = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder_inf,
        artifact_store=store,
        repository=repo,
    )
    with pytest.raises(EmbeddingInferenceError, match="contains non-finite values"):
        await coordinator_inf.ingest(doc)


@pytest.mark.asyncio
async def test_coordinator_work_order_outside_transaction() -> None:
    """Prove chunking, embedding, and artifact staging occur BEFORE DB write transaction."""
    events: list[str] = []

    doc = create_sample_canonical_doc()

    chunker = MagicMock(spec=DeterministicChunker)

    def do_chunk(d: Any) -> Any:
        events.append("chunk")
        return (
            ChunkDraftDTO(
                chunk_id=f"{d.document_id}_c0000",
                document_id=d.document_id,
                chunk_index=0,
                content="Text",
            ),
        )

    chunker.chunk_document.side_effect = do_chunk

    embedder = AsyncMock(spec=EmbeddingProvider)

    async def do_embed(_texts: Any) -> Any:
        events.append("embed")
        return (tuple([0.1] * 384),)

    embedder.embed_documents.side_effect = do_embed

    store = MagicMock(spec=KnowledgeArtifactStore)

    def do_stage(d: Any) -> Any:
        events.append("stage")
        return StagedArtifactToken(
            staging_id="stage_order",
            document_id=d.document_id,
            document_type=d.document_type,
            content_hash=d.content_hash,
        )

    store.stage.side_effect = do_stage

    tx = MockTransaction(None)

    @asynccontextmanager
    async def do_tx(_doc_id: str) -> AsyncIterator[KnowledgeIngestionTransaction]:
        events.append("begin_tx_and_lock")
        yield tx
        events.append("commit_tx")

    repo = MagicMock(spec=KnowledgeIngestionRepository)
    repo.get_document_state = AsyncMock(return_value=None)
    repo.document_transaction.side_effect = do_tx

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    await coordinator.ingest(doc)

    assert events == [
        "chunk",
        "embed",
        "stage",
        "begin_tx_and_lock",
        "commit_tx",
    ]


@pytest.mark.asyncio
async def test_coordinator_known_issue_structured_payload_persistence() -> None:
    """Known issue structured payload is persisted in same transaction as document and chunks."""
    ki_payload = SanitizedKnownIssuePayloadDTO(
        source_name="ki.json",
        issue_id="ki_456",
        title="Sample Known Issue",
        symptom_summary="Symptom summary",
        root_cause_summary="Root cause",
        workaround="Workaround steps",
        permanent_fix_reference="kb-fix-101",
        affected_products=("CRM",),
        affected_versions=("10.1",),
        category="Config",
        source_reference="known-issue://ki_456",
        canonical_text="composite text",
    )
    doc = create_sample_canonical_doc(structured_payload=ki_payload)
    repo = MockRepository(state=None, locked_state=None)

    chunker = MagicMock(spec=DeterministicChunker)
    chunker.chunk_document.return_value = (
        ChunkDraftDTO(
            chunk_id=f"{doc.document_id}_c0000",
            document_id=doc.document_id,
            chunk_index=0,
            content="KI text",
        ),
    )
    embedder = AsyncMock(spec=EmbeddingProvider)
    embedder.embed_documents.return_value = (tuple([0.1] * 384),)
    store = MagicMock(spec=KnowledgeArtifactStore)
    store.stage.return_value = StagedArtifactToken(
        staging_id="stage_ki",
        document_id=doc.document_id,
        document_type=doc.document_type,
        content_hash=doc.content_hash,
    )

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    result = await coordinator.ingest(doc)
    assert result.status == IngestionStatus.APPROVED
    assert len(repo.tx.persist_known_issue_calls) == 1
    assert repo.tx.persist_known_issue_calls[0] == ki_payload
    assert len(repo.tx.persist_document_calls) == 1
    assert len(repo.tx.persist_chunks_calls) == 1


@pytest.mark.asyncio
async def test_coordinator_compensation_query_failure_retains_artifact() -> None:
    """If is_document_hash_referenced query fails during compensation, retain artifact safely."""
    doc = create_sample_canonical_doc()
    repo = MockRepository(state=None, locked_state=None)
    # Fail during persist_chunks
    repo.tx.persist_chunks = AsyncMock(  # type: ignore[method-assign]
        side_effect=KnowledgePersistenceError("DB crashed during chunk insert")
    )
    # Reference check also fails (e.g. DB connection dropped)
    repo.is_document_hash_referenced = AsyncMock(  # type: ignore[method-assign]
        side_effect=KnowledgePersistenceError("Connection error during ref check")
    )

    chunker = MagicMock(spec=DeterministicChunker)
    chunker.chunk_document.return_value = (
        ChunkDraftDTO(
            chunk_id=f"{doc.document_id}_c0000",
            document_id=doc.document_id,
            chunk_index=0,
            content="Text",
        ),
    )
    embedder = AsyncMock(spec=EmbeddingProvider)
    embedder.embed_documents.return_value = (tuple([0.1] * 384),)
    store = MagicMock(spec=KnowledgeArtifactStore)
    token = StagedArtifactToken(
        staging_id="stage_comp_err",
        document_id=doc.document_id,
        document_type=doc.document_type,
        content_hash=doc.content_hash,
    )
    store.stage.return_value = token

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    with pytest.raises(KnowledgePersistenceError, match="DB crashed during chunk insert"):
        await coordinator.ingest(doc)

    store.promote.assert_called_once_with(token, doc)
    # Artifact must NOT be removed when reference state is unknown!
    store.remove_unreferenced.assert_not_called()


@pytest.mark.asyncio
async def test_coordinator_rejects_admission_source_input_dto() -> None:
    """Coordinator rejects AdmissionSourceInputDTO, accepting only CanonicalKnowledgeDocumentDTO."""
    source_input = AdmissionSourceInputDTO(
        source_name="guide.md",
        source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
        corpus_category=CorpusCategory.DOCUMENTATION,
        raw_bytes=b"# Guide\nSome bytes.",
    )
    coordinator = KnowledgeIngestionCoordinator(
        chunker=MagicMock(),
        embedding_provider=MagicMock(),
        artifact_store=MagicMock(),
        repository=MagicMock(),
    )
    with pytest.raises(
        KnowledgeIngestionError, match="requires a CanonicalKnowledgeDocumentDTO instance"
    ):
        await coordinator.ingest(source_input)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_coordinator_multi_batch_ordering_preserved() -> None:
    """Verify exact 0..N-1 ordering across multiple embedding batches (e.g. 70 drafts)."""
    doc = create_sample_canonical_doc()
    repo = MockRepository(state=None, locked_state=None)

    drafts = [
        ChunkDraftDTO(
            chunk_id=f"{doc.document_id}_c{i:04d}",
            document_id=doc.document_id,
            chunk_index=i,
            content=f"Draft content {i}",
        )
        for i in range(70)
    ]
    chunker = MagicMock(spec=DeterministicChunker)
    chunker.chunk_document.return_value = tuple(drafts)

    embedder = AsyncMock(spec=EmbeddingProvider)

    async def mock_embed(texts: list[str]) -> Sequence[tuple[float, ...]]:
        res: list[tuple[float, ...]] = []
        for t in texts:
            idx = int(t.split(" ")[-1])
            res.append(tuple([float(idx)] * 384))
        return tuple(res)

    embedder.embed_documents.side_effect = mock_embed

    store = MagicMock(spec=KnowledgeArtifactStore)
    store.stage.return_value = StagedArtifactToken(
        staging_id="stage_order_check",
        document_id=doc.document_id,
        document_type=doc.document_type,
        content_hash=doc.content_hash,
    )

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    result = await coordinator.ingest(doc)
    assert result.status == IngestionStatus.APPROVED
    assert result.chunk_count == 70

    persisted_chunks = repo.tx.persist_chunks_calls[0]
    assert len(persisted_chunks) == 70
    for idx, chunk in enumerate(persisted_chunks):
        assert chunk.chunk_index == idx
        assert chunk.chunk_id == f"{doc.document_id}_c{idx:04d}"
        assert chunk.embedding[0] == float(idx)


@pytest.mark.asyncio
async def test_coordinator_chunk_draft_to_embedded_chunk_dto_transformation() -> None:
    """ChunkDraftDTO transforms to EmbeddedChunkDTO with verified frozen attributes."""
    draft = ChunkDraftDTO(
        chunk_id="doc_transform1122_c0000",
        document_id="doc_transform1122",
        chunk_index=0,
        content="Test content transformation",
    )
    vec = tuple([0.5] * 384)
    embedded = EmbeddedChunkDTO(
        chunk_id=draft.chunk_id,
        document_id=draft.document_id,
        chunk_index=draft.chunk_index,
        content=draft.content,
        embedding=vec,
    )
    assert embedded.chunk_id == draft.chunk_id
    assert embedded.document_id == draft.document_id
    assert embedded.chunk_index == draft.chunk_index
    assert embedded.content == draft.content
    assert embedded.embedding == vec
    assert len(embedded.embedding) == 384

    with pytest.raises(ValidationError):
        embedded.chunk_id = "new_id"


@pytest.mark.asyncio
async def test_coordinator_embedding_validation_negative_infinity() -> None:
    """Embedding vectors containing negative infinity fail closed with EmbeddingInferenceError."""
    doc = create_sample_canonical_doc()
    repo = MockRepository(state=None, locked_state=None)

    chunker = MagicMock(spec=DeterministicChunker)
    chunker.chunk_document.return_value = (
        ChunkDraftDTO(
            chunk_id=f"{doc.document_id}_c0000",
            document_id=doc.document_id,
            chunk_index=0,
            content="Content",
        ),
    )

    neg_inf_vec = [0.1] * 383 + [-float("inf")]
    embedder_neg_inf = AsyncMock(spec=EmbeddingProvider)
    embedder_neg_inf.embed_documents.return_value = (tuple(neg_inf_vec),)

    store = MagicMock(spec=KnowledgeArtifactStore)
    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder_neg_inf,
        artifact_store=store,
        repository=repo,
    )
    with pytest.raises(EmbeddingInferenceError, match="contains non-finite values"):
        await coordinator.ingest(doc)


@pytest.mark.asyncio
async def test_coordinator_embedding_provider_failure_opens_no_transaction() -> None:
    """If embedding provider raises an error, no write transaction is ever opened."""
    doc = create_sample_canonical_doc()
    repo = MockRepository(state=None, locked_state=None)
    repo.document_transaction = MagicMock()  # type: ignore[method-assign]

    chunker = MagicMock(spec=DeterministicChunker)
    chunker.chunk_document.return_value = (
        ChunkDraftDTO(
            chunk_id=f"{doc.document_id}_c0000",
            document_id=doc.document_id,
            chunk_index=0,
            content="Content",
        ),
    )

    embedder = AsyncMock(spec=EmbeddingProvider)
    embedder.embed_documents.side_effect = EmbeddingInferenceError("Inference engine crashed")

    store = MagicMock(spec=KnowledgeArtifactStore)
    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    with pytest.raises(EmbeddingInferenceError, match="Inference engine crashed"):
        await coordinator.ingest(doc)

    store.stage.assert_not_called()
    repo.document_transaction.assert_not_called()
    assert len(repo.tx.persist_document_calls) == 0


@pytest.mark.asyncio
async def test_coordinator_general_document_creates_no_structured_rows() -> None:
    """General doc with structured_payload=None persists no runbook or known issue."""
    doc = create_sample_canonical_doc(structured_payload=None)
    repo = MockRepository(state=None, locked_state=None)

    chunker = MagicMock(spec=DeterministicChunker)
    chunker.chunk_document.return_value = (
        ChunkDraftDTO(
            chunk_id=f"{doc.document_id}_c0000",
            document_id=doc.document_id,
            chunk_index=0,
            content="Doc text",
        ),
    )
    embedder = AsyncMock(spec=EmbeddingProvider)
    embedder.embed_documents.return_value = (tuple([0.1] * 384),)
    store = MagicMock(spec=KnowledgeArtifactStore)
    store.stage.return_value = StagedArtifactToken(
        staging_id="stage_general",
        document_id=doc.document_id,
        document_type=doc.document_type,
        content_hash=doc.content_hash,
    )

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    result = await coordinator.ingest(doc)
    assert result.status == IngestionStatus.APPROVED
    assert len(repo.tx.persist_document_calls) == 1
    assert len(repo.tx.persist_chunks_calls) == 1
    # Structured tables must NOT be called
    assert len(repo.tx.persist_runbook_calls) == 0
    assert len(repo.tx.persist_known_issue_calls) == 0


@pytest.mark.asyncio
async def test_coordinator_cleanup_failure_handled_safely() -> None:
    """If remove_unreferenced raises an exception during compensation, it is
    handled safely."""
    doc = create_sample_canonical_doc()
    repo = MockRepository(state=None, locked_state=None, is_referenced=False)
    repo.tx.persist_chunks = AsyncMock(  # type: ignore[method-assign]
        side_effect=KnowledgePersistenceError("Primary DB failure")
    )

    chunker = MagicMock(spec=DeterministicChunker)
    chunker.chunk_document.return_value = (
        ChunkDraftDTO(
            chunk_id=f"{doc.document_id}_c0000",
            document_id=doc.document_id,
            chunk_index=0,
            content="Text",
        ),
    )
    embedder = AsyncMock(spec=EmbeddingProvider)
    embedder.embed_documents.return_value = (tuple([0.1] * 384),)
    store = MagicMock(spec=KnowledgeArtifactStore)
    token = StagedArtifactToken(
        staging_id="stage_cleanup_err",
        document_id=doc.document_id,
        document_type=doc.document_type,
        content_hash=doc.content_hash,
    )
    store.stage.return_value = token
    store.remove_unreferenced.side_effect = OSError("Filesystem locked")

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    with pytest.raises(KnowledgePersistenceError, match="Primary DB failure"):
        await coordinator.ingest(doc)

    store.promote.assert_called_once_with(token, doc)
    store.remove_unreferenced.assert_called_once_with(
        doc.document_type, doc.document_id, doc.content_hash
    )


@pytest.mark.asyncio
async def test_coordinator_compensation_removes_exact_content_hash_only() -> None:
    """Compensation removes only exact content-addressed hash, never physical paths."""
    doc = create_sample_canonical_doc()
    repo = MockRepository(state=None, locked_state=None, is_referenced=False)
    repo.tx.persist_chunks = AsyncMock(  # type: ignore[method-assign]
        side_effect=KnowledgePersistenceError("DB failed")
    )

    chunker = MagicMock(spec=DeterministicChunker)
    chunker.chunk_document.return_value = (
        ChunkDraftDTO(
            chunk_id=f"{doc.document_id}_c0000",
            document_id=doc.document_id,
            chunk_index=0,
            content="Text",
        ),
    )
    embedder = AsyncMock(spec=EmbeddingProvider)
    embedder.embed_documents.return_value = (tuple([0.1] * 384),)
    store = MagicMock(spec=KnowledgeArtifactStore)
    token = StagedArtifactToken(
        staging_id="stage_comp_args",
        document_id=doc.document_id,
        document_type=doc.document_type,
        content_hash=doc.content_hash,
    )
    store.stage.return_value = token

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    with pytest.raises(KnowledgePersistenceError, match="DB failed"):
        await coordinator.ingest(doc)

    args, _kwargs = store.remove_unreferenced.call_args
    assert args == (doc.document_type, doc.document_id, doc.content_hash)
    for arg in args:
        assert isinstance(arg, str)
        assert "/" not in arg and "\\" not in arg


@pytest.mark.asyncio
async def test_coordinator_fast_path_bypasses_all_expensive_operations() -> None:
    """When document content hash matches DB state, all expensive operations are bypassed."""
    doc = create_sample_canonical_doc()
    state = DocumentStateDTO(
        document_id=doc.document_id,
        content_hash=doc.content_hash,
        version=5,
    )
    repo = MockRepository(state=state, locked_state=state)
    chunker = MagicMock(spec=DeterministicChunker)
    embedder = AsyncMock(spec=EmbeddingProvider)
    store = MagicMock(spec=KnowledgeArtifactStore)

    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=embedder,
        artifact_store=store,
        repository=repo,
    )

    result = await coordinator.ingest(doc)

    assert result.status == IngestionStatus.UNCHANGED
    assert result.version == 5
    assert result.chunk_count == 0

    chunker.chunk_document.assert_not_called()
    embedder.embed_documents.assert_not_called()
    store.stage.assert_not_called()
    store.promote.assert_not_called()
    store.discard_staged.assert_not_called()
    store.remove_unreferenced.assert_not_called()
    assert len(repo.tx.persist_document_calls) == 0
    assert len(repo.tx.persist_chunks_calls) == 0
    assert len(repo.tx.persist_runbook_calls) == 0
    assert len(repo.tx.persist_known_issue_calls) == 0
