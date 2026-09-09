"""Unit tests for PostgresKnowledgeIngestionRepository (Gate 7D.5D)."""

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import OperationalError

from kb_mcp.adapters.postgres_ingestion_repository import (
    ADVISORY_LOCK_SQL,
    DELETE_CHUNKS_SQL,
    GET_LOCKED_DOCUMENT_STATE_SQL,
    INSERT_CHUNK_SQL,
    PostgresKnowledgeIngestionRepository,
    _PostgresIngestionTransaction,
)
from kb_mcp.contracts.errors import KnowledgePersistenceError
from kb_mcp.contracts.ingestion import (
    CanonicalKnowledgeDocumentDTO,
    CorpusCategory,
    EmbeddedChunkDTO,
    SanitizedKnownIssuePayloadDTO,
    SanitizedRunbookPayloadDTO,
)


def create_sample_canonical_doc(
    document_id: str = "doc_testrepo112233445566",
) -> CanonicalKnowledgeDocumentDTO:
    return CanonicalKnowledgeDocumentDTO(
        document_id=document_id,
        title="Test Doc",
        document_type="documentation",
        source_reference=f"docs://{document_id}",
        canonical_content="# Test\n\nContent",
        content_hash="1122334455667788112233445566778811223344556677881122334455667788",
        corpus_category=CorpusCategory.DOCUMENTATION,
    )


@pytest.mark.asyncio
async def test_get_document_state_found() -> None:
    """get_document_state returns DocumentStateDTO when record exists."""
    mock_session = AsyncMock()
    mock_row = {
        "document_id": "doc_123",
        "content_hash": "a" * 64,
        "version": 2,
    }
    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = mock_row
    mock_session.execute.return_value = mock_result

    session_maker = MagicMock(return_value=mock_session)
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None

    repo = PostgresKnowledgeIngestionRepository(session_maker)
    state = await repo.get_document_state("doc_123")

    assert state is not None
    assert state.document_id == "doc_123"
    assert state.content_hash == "a" * 64
    assert state.version == 2


@pytest.mark.asyncio
async def test_get_document_state_not_found() -> None:
    """get_document_state returns None when record does not exist or doc_id is empty."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = None
    mock_session.execute.return_value = mock_result

    session_maker = MagicMock(return_value=mock_session)
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None

    repo = PostgresKnowledgeIngestionRepository(session_maker)
    assert await repo.get_document_state("doc_not_found") is None
    assert await repo.get_document_state("") is None


@pytest.mark.asyncio
async def test_get_document_state_error_mapping() -> None:
    """Database errors during get_document_state are mapped to KnowledgePersistenceError."""
    mock_session = AsyncMock()
    mock_session.execute.side_effect = OperationalError(
        "SELECT failed", params=None, orig=Exception("DB down")
    )

    session_maker = MagicMock(return_value=mock_session)
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None

    repo = PostgresKnowledgeIngestionRepository(session_maker)
    with pytest.raises(KnowledgePersistenceError) as exc_info:
        await repo.get_document_state("doc_err")
    assert "Failed to get document state" in str(exc_info.value)
    assert exc_info.value.details.get("document_id") == "doc_err"


@pytest.mark.asyncio
async def test_is_document_hash_referenced() -> None:
    """is_document_hash_referenced returns bool based on query result."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 1
    mock_session.execute.return_value = mock_result

    session_maker = MagicMock(return_value=mock_session)
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None

    repo = PostgresKnowledgeIngestionRepository(session_maker)
    assert await repo.is_document_hash_referenced("doc_123", "hash_abc") is True

    # Empty inputs return False without querying
    assert await repo.is_document_hash_referenced("", "hash_abc") is False
    assert await repo.is_document_hash_referenced("doc_123", "") is False

    mock_result.scalar.return_value = None
    assert await repo.is_document_hash_referenced("doc_123", "hash_abc") is False


@pytest.mark.asyncio
async def test_advisory_lock_derivation_and_transaction_flow() -> None:
    """Advisory lock key is derived as signed 64-bit int and locked inside transaction."""
    doc_id = "doc_test_lock_12345"
    expected_lock_key = int.from_bytes(
        hashlib.sha256(doc_id.encode("utf-8")).digest()[:8],
        byteorder="big",
        signed=True,
    )
    assert -(2**63) <= expected_lock_key <= (2**63 - 1)

    mock_session = AsyncMock()
    mock_begin_ctx = MagicMock()
    mock_begin_ctx.__aenter__ = AsyncMock()
    mock_begin_ctx.__aexit__ = AsyncMock()
    mock_session.begin = MagicMock(return_value=mock_begin_ctx)

    session_maker = MagicMock(return_value=mock_session)

    repo = PostgresKnowledgeIngestionRepository(session_maker)
    async with repo.document_transaction(doc_id) as tx:
        assert isinstance(tx, _PostgresIngestionTransaction)
        # Verify advisory lock statement was executed
        assert mock_session.execute.call_count >= 1
        lock_call = mock_session.execute.call_args_list[0]
        assert lock_call[0][0] == ADVISORY_LOCK_SQL
        assert lock_call[0][1] == {"lock_key": expected_lock_key}

    # Verify session was closed
    mock_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_transaction_inactive_guard() -> None:
    """Calling mutation methods outside active transaction raises KnowledgePersistenceError."""
    mock_session = AsyncMock()
    tx = _PostgresIngestionTransaction(mock_session, "doc_inactive")

    doc = create_sample_canonical_doc("doc_inactive")
    with pytest.raises(KnowledgePersistenceError, match="not active"):
        await tx.persist_document(doc, 1)

    with pytest.raises(KnowledgePersistenceError, match="not active"):
        await tx.persist_chunks([])

    with pytest.raises(KnowledgePersistenceError, match="not active"):
        await tx.get_locked_document_state()


@pytest.mark.asyncio
async def test_transaction_persist_runbook_json_serialization() -> None:
    """Runbook diagnostic and remediation steps are serialized to json strings."""
    mock_session = AsyncMock()
    tx = _PostgresIngestionTransaction(mock_session, "doc_rb")
    tx._activate()

    rb = SanitizedRunbookPayloadDTO(
        source_name="rb.json",
        runbook_id="rb_999",
        title="Test Runbook",
        problem_description="Problem",
        diagnostic_steps=("Check log", "Check CPU"),
        remediation_steps=("Restart service", "Notify lead"),
        source_reference="runbook://rb_999",
        canonical_text="text",
    )

    await tx.persist_runbook(rb)
    assert mock_session.execute.call_count == 1
    params = mock_session.execute.call_args[0][1]
    assert params["runbook_id"] == "rb_999"
    assert params["diagnostic_steps"] == '["Check log", "Check CPU"]'
    assert params["remediation_steps"] == '["Restart service", "Notify lead"]'


@pytest.mark.asyncio
async def test_transaction_persist_known_issue_json_serialization() -> None:
    """Known issue affected products and versions are serialized to json strings."""
    mock_session = AsyncMock()
    tx = _PostgresIngestionTransaction(mock_session, "doc_ki")
    tx._activate()

    ki = SanitizedKnownIssuePayloadDTO(
        source_name="ki.json",
        issue_id="ki_999",
        title="Test KI",
        symptom_summary="Symptom",
        root_cause_summary="Root cause",
        affected_products=("CRM", "Service"),
        affected_versions=("10.1", "10.2"),
        source_reference="known-issue://ki_999",
        canonical_text="text",
    )

    await tx.persist_known_issue(ki)
    assert mock_session.execute.call_count == 1
    params = mock_session.execute.call_args[0][1]
    assert params["issue_id"] == "ki_999"
    assert params["affected_products"] == '["CRM", "Service"]'
    assert params["affected_versions"] == '["10.1", "10.2"]'


@pytest.mark.asyncio
async def test_transaction_rollback_and_error_mapping() -> None:
    """Database exceptions during transaction block are mapped to KnowledgePersistenceError."""
    mock_session = AsyncMock()
    mock_begin_ctx = MagicMock()
    mock_begin_ctx.__aenter__ = AsyncMock()
    mock_begin_ctx.__aexit__ = AsyncMock(
        side_effect=OperationalError(
            "Commit failed", params=None, orig=Exception("Connection lost")
        )
    )
    mock_session.begin = MagicMock(return_value=mock_begin_ctx)

    session_maker = MagicMock(return_value=mock_session)
    repo = PostgresKnowledgeIngestionRepository(session_maker)

    with pytest.raises(KnowledgePersistenceError, match="Database transaction failed"):
        async with repo.document_transaction("doc_fail"):
            pass

    mock_session.close.assert_awaited_once()


def test_advisory_lock_keys_distinct_and_deterministic() -> None:
    """Same document yields same key; different documents yield distinct signed 64-bit keys."""
    doc_1 = "doc_alpha_11223344"
    doc_2 = "doc_beta_55667788"

    digest_1 = hashlib.sha256(doc_1.encode("utf-8")).digest()[:8]
    digest_2 = hashlib.sha256(doc_2.encode("utf-8")).digest()[:8]

    key_1a = int.from_bytes(digest_1, byteorder="big", signed=True)
    key_1b = int.from_bytes(digest_1, byteorder="big", signed=True)
    key_2 = int.from_bytes(digest_2, byteorder="big", signed=True)

    assert key_1a == key_1b
    assert key_1a != key_2
    for k in (key_1a, key_2):
        assert -(2**63) <= k <= (2**63 - 1)


@pytest.mark.asyncio
async def test_transaction_get_locked_document_state() -> None:
    """get_locked_document_state executes FOR UPDATE query within active transaction."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = {
        "document_id": "doc_locked_1",
        "content_hash": "b" * 64,
        "version": 4,
    }
    mock_session.execute.return_value = mock_result

    tx = _PostgresIngestionTransaction(mock_session, "doc_locked_1")
    tx._activate()

    state = await tx.get_locked_document_state()
    assert state is not None
    assert state.document_id == "doc_locked_1"
    assert state.content_hash == "b" * 64
    assert state.version == 4

    assert mock_session.execute.call_count == 1
    call_args = mock_session.execute.call_args
    assert call_args[0][0] == GET_LOCKED_DOCUMENT_STATE_SQL
    assert call_args[0][1] == {"document_id": "doc_locked_1"}


@pytest.mark.asyncio
async def test_transaction_persist_chunks_delete_and_insert() -> None:
    """persist_chunks executes DELETE followed by INSERT for each chunk."""
    mock_session = AsyncMock()
    tx = _PostgresIngestionTransaction(mock_session, "doc_chunks_test")
    tx._activate()

    chunk_1 = EmbeddedChunkDTO(
        chunk_id="doc_chunks_test_c0000",
        document_id="doc_chunks_test",
        chunk_index=0,
        content="Chunk 0 text",
        embedding=tuple([0.1] * 384),
    )
    chunk_2 = EmbeddedChunkDTO(
        chunk_id="doc_chunks_test_c0001",
        document_id="doc_chunks_test",
        chunk_index=1,
        content="Chunk 1 text",
        embedding=tuple([0.2] * 384),
    )

    await tx.persist_chunks([chunk_1, chunk_2])

    assert mock_session.execute.call_count == 3
    # Call 0: DELETE
    delete_call = mock_session.execute.call_args_list[0]
    assert delete_call[0][0] == DELETE_CHUNKS_SQL
    assert delete_call[0][1] == {"document_id": "doc_chunks_test"}

    # Call 1: INSERT chunk 0
    insert_call_1 = mock_session.execute.call_args_list[1]
    assert insert_call_1[0][0] == INSERT_CHUNK_SQL
    assert insert_call_1[0][1]["chunk_id"] == "doc_chunks_test_c0000"
    assert len(insert_call_1[0][1]["embedding"]) == 384

    # Call 2: INSERT chunk 1
    insert_call_2 = mock_session.execute.call_args_list[2]
    assert insert_call_2[0][0] == INSERT_CHUNK_SQL
    assert insert_call_2[0][1]["chunk_id"] == "doc_chunks_test_c0001"
