"""Unit tests for synthetic sample Knowledge corpus definitions and seeder invariants."""

import hashlib
import inspect
import re
from collections.abc import Sequence
from unittest.mock import AsyncMock, MagicMock

import pytest

from kb_mcp.contracts.errors import (
    EmbeddingDimensionError,
    EmbeddingInputError,
)
from kb_mcp.contracts.interfaces import EmbeddingProvider
from kb_mcp.server import create_knowledge_mcp_server
from tests.fixtures.knowledge.sample_corpus import (
    compute_content_hash,
    get_sample_chunks,
    get_sample_documents,
    get_sample_known_issues,
    get_sample_runbooks,
)
from tests.fixtures.knowledge.sample_seeder import seed_sample_knowledge_corpus


class MockEmbeddingProvider(EmbeddingProvider):
    """Mock embedding provider returning deterministic 384-dimensional vectors."""

    def __init__(self, dimension: int = 384, return_count: int | None = None) -> None:
        self.dimension = dimension
        self.return_count = return_count
        self.embed_documents_call_count = 0
        self.last_documents_input: list[str] = []

    async def embed_query(self, _query: str) -> tuple[float, ...]:
        return tuple(0.01 * i for i in range(self.dimension))

    async def embed_documents(self, documents: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        self.embed_documents_call_count += 1
        self.last_documents_input = list(documents)
        count = self.return_count if self.return_count is not None else len(documents)
        return tuple(tuple(0.01 * (i % 50) for i in range(self.dimension)) for _ in range(count))


# ============================================================================
# 1. Corpus Size and Identification Invariants (Sections 5, 6, 7)
# ============================================================================
def test_sample_corpus_counts() -> None:
    """Sample corpus must define exactly 3 documents, 6 chunks, 3 runbooks, 3 known issues."""
    docs = get_sample_documents()
    chunks = get_sample_chunks()
    runbooks = get_sample_runbooks()
    known_issues = get_sample_known_issues()

    assert len(docs) == 3
    assert len(chunks) == 6
    assert len(runbooks) == 3
    assert len(known_issues) == 3


def test_sample_identifiers_pattern() -> None:
    """All sample identifiers must begin with approved 'sample-' prefix."""
    for doc in get_sample_documents():
        assert doc.document_id.startswith("sample-doc-")
    for chunk in get_sample_chunks():
        assert chunk.chunk_id.startswith("sample-chunk-")
        assert chunk.document_id.startswith("sample-doc-")
    for rb in get_sample_runbooks():
        assert rb.runbook_id.startswith("sample-rb-")
    for ki in get_sample_known_issues():
        assert ki.issue_id.startswith("sample-ki-")


def test_sample_source_references_format() -> None:
    """All source references must be logical sample:// URIs without filesystem or DB paths."""
    approved_refs = {
        "sample://knowledge/postgresql-connection-timeout",
        "sample://knowledge/api-authentication-failure",
        "sample://knowledge/iis-application-pool-unavailable",
    }
    for doc in get_sample_documents():
        assert doc.source_reference in approved_refs
        assert not any(p in doc.source_reference for p in ("C:", "F:", "\\", "/var/", "table"))
    for rb in get_sample_runbooks():
        assert rb.source_reference in approved_refs
        assert not any(p in doc.source_reference for p in ("C:", "F:", "\\", "/var/", "table"))
    for ki in get_sample_known_issues():
        assert ki.source_reference in approved_refs
        assert not any(p in doc.source_reference for p in ("C:", "F:", "\\", "/var/", "table"))


# ============================================================================
# 2. Content Safety & Integrity Invariants (Sections 4, 11, 37)
# ============================================================================
def test_no_customer_or_secret_data() -> None:
    """Sample content must be synthetic and contain no credentials or customer PII."""
    forbidden_patterns = [
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),  # Email
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),  # IP address
        re.compile(r"\beyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\b"),  # Real JWT
        re.compile(r"\bpassword\s*[:=]\s*\S+", re.IGNORECASE),  # Password assignment
        re.compile(r"\bBearer\s+ey", re.IGNORECASE),  # Bearer token
        re.compile(r"\bSO_CS\b", re.IGNORECASE),  # Real SuperOffice CS path
        re.compile(r"\bsuperoffice\.com\b", re.IGNORECASE),  # Production domain
    ]
    all_texts: list[str] = []
    for doc in get_sample_documents():
        all_texts.extend([doc.title, doc.canonical_content])
    for chunk in get_sample_chunks():
        all_texts.append(chunk.content)
    for rb in get_sample_runbooks():
        all_texts.extend(
            [rb.title, rb.problem_description, *rb.diagnostic_steps, *rb.remediation_steps]
        )
    for ki in get_sample_known_issues():
        all_texts.extend([ki.title, ki.symptom_summary, ki.root_cause_summary, ki.workaround or ""])

    for text in all_texts:
        for pat in forbidden_patterns:
            assert not pat.search(text), (
                f"Found forbidden pattern '{pat.pattern}' in sample text: {text}"
            )


def test_document_content_hash_matches_canonical() -> None:
    """Document content_hash must equal deterministic SHA-256 of canonical_content."""
    for doc in get_sample_documents():
        expected_hash = hashlib.sha256(doc.canonical_content.encode("utf-8")).hexdigest().lower()
        assert doc.content_hash == expected_hash
        assert doc.content_hash == compute_content_hash(doc.canonical_content)
        assert doc.version == 1


def test_document_chunk_cardinality_and_indexing() -> None:
    """Each document must have exactly 2 chunks with deterministic indices 0 and 1."""
    docs = get_sample_documents()
    chunks = get_sample_chunks()

    for doc in docs:
        doc_chunks = [c for c in chunks if c.document_id == doc.document_id]
        assert len(doc_chunks) == 2, f"Document {doc.document_id} has {len(doc_chunks)} chunks"
        assert [c.chunk_index for c in doc_chunks] == [0, 1]
        assert doc_chunks[0].content in doc.canonical_content
        assert doc_chunks[1].content in doc.canonical_content


# ============================================================================
# 3. Seeder Invariants & Validation (Sections 19, 21, 22, 23)
# ============================================================================
@pytest.mark.asyncio
async def test_seeder_calls_embed_documents_batch() -> None:
    """Seeder must call embed_documents in a single batch for all 6 chunk contents."""
    provider = MockEmbeddingProvider(dimension=384)
    mock_engine = MagicMock()
    mock_conn = AsyncMock()
    mock_engine.begin.return_value.__aenter__.return_value = mock_conn

    counts = await seed_sample_knowledge_corpus(mock_engine, embedding_provider=provider)

    assert counts == {"documents": 3, "chunks": 6, "runbooks": 3, "known_issues": 3}
    assert provider.embed_documents_call_count == 1
    assert len(provider.last_documents_input) == 6

    # Verify execution within engine transaction
    mock_engine.begin.assert_called_once()
    assert mock_conn.execute.call_count == 3 + 6 + 3 + 3  # docs + chunks + runbooks + known_issues


@pytest.mark.asyncio
async def test_seeder_fails_on_vector_count_mismatch() -> None:
    """Seeder must fail closed and raise if provider returns wrong number of vectors."""
    provider = MockEmbeddingProvider(dimension=384, return_count=5)  # Expected 6
    mock_engine = MagicMock()

    with pytest.raises(EmbeddingInputError, match="vector count mismatch"):
        await seed_sample_knowledge_corpus(mock_engine, embedding_provider=provider)

    mock_engine.begin.assert_not_called()


@pytest.mark.asyncio
async def test_seeder_fails_on_vector_dimension_mismatch() -> None:
    """Seeder must fail closed and raise if provider returns non-384 dimensional vectors."""
    provider = MockEmbeddingProvider(dimension=512)  # Expected 384
    mock_engine = MagicMock()

    with pytest.raises(EmbeddingDimensionError) as exc_info:
        await seed_sample_knowledge_corpus(mock_engine, embedding_provider=provider)

    assert exc_info.value.details is not None
    assert exc_info.value.details["expected"] == 384
    assert exc_info.value.details["actual"] == 512
    mock_engine.begin.assert_not_called()


@pytest.mark.asyncio
async def test_seeder_fails_on_non_finite_vector() -> None:
    """Seeder must fail closed if any vector component is NaN or Infinite."""
    provider = MockEmbeddingProvider(dimension=384)
    orig_embed = provider.embed_documents

    async def embed_with_nan(docs: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        res = await orig_embed(docs)
        mutable = [list(v) for v in res]
        mutable[2][10] = float("nan")
        return tuple(tuple(v) for v in mutable)

    provider.embed_documents = embed_with_nan  # type: ignore[assignment]
    mock_engine = MagicMock()

    with pytest.raises(EmbeddingInputError, match="non-finite"):
        await seed_sample_knowledge_corpus(mock_engine, embedding_provider=provider)

    mock_engine.begin.assert_not_called()


@pytest.mark.asyncio
async def test_seeder_transaction_rollback_on_db_error() -> None:
    """If database write fails, the async context manager must exit with error for rollback."""
    provider = MockEmbeddingProvider(dimension=384)
    mock_engine = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = RuntimeError("Database connection severed during chunk write")
    mock_engine.begin.return_value.__aenter__.return_value = mock_conn

    with pytest.raises(RuntimeError, match="Database connection severed"):
        await seed_sample_knowledge_corpus(mock_engine, embedding_provider=provider)

    mock_engine.begin.assert_called_once()


@pytest.mark.asyncio
async def test_seeder_idempotent_multiple_runs() -> None:
    """Calling seeder repeatedly returns identical counts without modifying non-sample scope."""
    provider = MockEmbeddingProvider(dimension=384)
    mock_engine = MagicMock()
    mock_conn = AsyncMock()
    mock_engine.begin.return_value.__aenter__.return_value = mock_conn

    run1 = await seed_sample_knowledge_corpus(mock_engine, embedding_provider=provider)
    run2 = await seed_sample_knowledge_corpus(mock_engine, embedding_provider=provider)

    assert run1 == run2 == {"documents": 3, "chunks": 6, "runbooks": 3, "known_issues": 3}


# ============================================================================
# 4. Public MCP Surface Invariants (Sections 25, 26, 41)
# ============================================================================
@pytest.mark.asyncio
async def test_no_admin_or_seed_tools_added_to_public_mcp() -> None:
    """Public Knowledge MCP server must expose exactly 3 approved tools."""
    server = create_knowledge_mcp_server()
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}
    expected_tools = {"search_knowledge", "get_runbook", "find_known_issues"}
    assert tool_names == expected_tools
    assert "seed_samples" not in tool_names
    assert "add_document" not in tool_names
    assert "upload_runbook" not in tool_names
    assert "insert_knowledge" not in tool_names


def test_seeder_interface_has_no_arbitrary_input() -> None:
    """Sample seeder must accept only (engine, embedding_provider) - no arbitrary file/text args."""
    sig = inspect.signature(seed_sample_knowledge_corpus)
    param_names = list(sig.parameters.keys())
    assert param_names == ["engine", "embedding_provider"]
