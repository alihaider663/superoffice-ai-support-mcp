"""Unit tests for DeterministicChunker and token counting (Gate 7D.5D)."""

import pytest
from pydantic import ValidationError

from kb_mcp.contracts.errors import KnowledgeChunkingError
from kb_mcp.contracts.ingestion import (
    CanonicalKnowledgeDocumentDTO,
    ChunkDraftDTO,
    CorpusCategory,
)
from kb_mcp.ingestion.chunking import _RE_TOKEN, DeterministicChunker, count_tokens


def test_count_tokens_basic() -> None:
    """Token counting accurately counts words, punctuation, and handles whitespace."""
    assert count_tokens("") == 0
    assert count_tokens("   \n\t  ") == 0
    assert count_tokens("Hello world") == 2
    assert count_tokens("Hello, world!") == 4  # Hello, ,, world, !
    assert count_tokens("SuperOffice CRM 10.2") == 5  # SuperOffice, CRM, 10, ., 2


def test_chunk_short_document() -> None:
    """Short documents fitting within CHUNK_TARGET_TOKENS produce a single chunk."""
    chunker = DeterministicChunker()
    doc = CanonicalKnowledgeDocumentDTO(
        document_id="doc_0123456789abcdef01234567",
        title="Short Guide",
        document_type="documentation",
        source_reference="docs://short-guide",
        canonical_content="# Short Guide\n\nThis is a short guide for SuperOffice CRM.",
        content_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        corpus_category=CorpusCategory.DOCUMENTATION,
    )

    chunks = chunker.chunk_document(doc)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert isinstance(chunk, ChunkDraftDTO)
    assert chunk.document_id == doc.document_id
    assert chunk.chunk_id == f"{doc.document_id}_c0000"
    assert chunk.chunk_index == 0
    assert chunk.content == doc.canonical_content


def test_chunking_deterministic_and_reproducible() -> None:
    """Running chunker multiple times produces identical chunks with exact IDs."""
    chunker = DeterministicChunker()
    content = (
        "# Title\n\n" + "Paragraph with information about CRM configuration and settings.\n\n" * 50
    )
    doc = CanonicalKnowledgeDocumentDTO(
        document_id="doc_aabbccddeeff001122334455",
        title="Config Guide",
        document_type="documentation",
        source_reference="docs://config-guide",
        canonical_content=content,
        content_hash="aabbccddeeff001122334455aabbccddeeff001122334455aabbccddeeff0011",
        corpus_category=CorpusCategory.DOCUMENTATION,
    )

    run1 = chunker.chunk_document(doc)
    run2 = chunker.chunk_document(doc)

    assert len(run1) == len(run2)
    for c1, c2 in zip(run1, run2, strict=True):
        assert c1.chunk_id == c2.chunk_id
        assert c1.chunk_index == c2.chunk_index
        assert c1.content == c2.content


def test_heading_aware_splitting() -> None:
    """Headings (#, ##, ###) act as natural chunk boundaries when target size is reached."""
    chunker = DeterministicChunker(
        target_tokens=30,
        max_tokens=50,
        overlap_tokens=10,
    )

    section_1 = "# Section One\n\n" + ("Detailed words here about database connections. " * 3)
    section_2 = "## Section Two\n\n" + ("Detailed words here about timeout troubleshooting. " * 3)
    full_content = f"{section_1}\n\n{section_2}"

    doc = CanonicalKnowledgeDocumentDTO(
        document_id="doc_headings1122334455667788",
        title="Headings Guide",
        document_type="documentation",
        source_reference="docs://headings-guide",
        canonical_content=full_content,
        content_hash="1122334455667788112233445566778811223344556677881122334455667788",
        corpus_category=CorpusCategory.DOCUMENTATION,
    )

    chunks = chunker.chunk_document(doc)
    assert len(chunks) >= 2
    assert chunks[0].chunk_index == 0
    assert chunks[0].chunk_id == f"{doc.document_id}_c0000"
    assert "Section One" in chunks[0].content
    assert chunks[1].chunk_index == 1
    assert chunks[1].chunk_id == f"{doc.document_id}_c0001"


def test_chunking_empty_content_raises_error() -> None:
    """Attempting to chunk empty or whitespace-only content raises KnowledgeChunkingError."""
    chunker = DeterministicChunker()
    # Bypass Pydantic field validation using model_construct to test chunker safety
    doc = CanonicalKnowledgeDocumentDTO.model_construct(
        document_id="doc_empty112233445566778899",
        title="Empty Doc",
        document_type="documentation",
        source_reference="docs://empty-doc",
        canonical_content="   \n\t  \n  ",
        content_hash="9988776655443322110099887766554433221100998877665544332211009988",
        corpus_category=CorpusCategory.DOCUMENTATION,
    )

    with pytest.raises(KnowledgeChunkingError) as exc_info:
        chunker.chunk_document(doc)
    assert "empty or whitespace-only" in str(exc_info.value)


def test_chunking_invalid_type_raises_type_error() -> None:
    """Passing a non-CanonicalKnowledgeDocumentDTO raises TypeError."""
    chunker = DeterministicChunker()
    with pytest.raises(
        TypeError, match="DeterministicChunker requires CanonicalKnowledgeDocumentDTO"
    ):
        chunker.chunk_document("not a document")  # type: ignore[arg-type]


def test_exceeding_max_chunks_raises_error() -> None:
    """Documents that would produce more than MAX_CHUNKS_PER_DOCUMENT fail closed."""
    chunker = DeterministicChunker(
        target_tokens=10,
        max_tokens=15,
        overlap_tokens=2,
    )

    # Generate content that will exceed 100 chunks with target_tokens=10
    huge_content = "\n\n".join(
        f"## Section {i}\n\nWord1 word2 word3 word4 word5 word6 word7 word8 word9 word10."
        for i in range(120)
    )
    doc = CanonicalKnowledgeDocumentDTO(
        document_id="doc_huge11223344556677889900",
        title="Huge Doc",
        document_type="documentation",
        source_reference="docs://huge-doc",
        canonical_content=huge_content,
        content_hash="abcdef11223344556677889900abcdef11223344556677889900abcdef112233",
        corpus_category=CorpusCategory.DOCUMENTATION,
    )

    with pytest.raises(KnowledgeChunkingError) as exc_info:
        chunker.chunk_document(doc)
    assert "exceeding the maximum allowed limit" in str(exc_info.value)


def test_chunk_parameters_custom_validation() -> None:
    """Invalid chunker configuration parameters raise ValueError."""
    with pytest.raises(ValueError, match="target_tokens must be positive"):
        DeterministicChunker(target_tokens=0)

    with pytest.raises(ValueError, match="max_tokens must be >= target_tokens"):
        DeterministicChunker(target_tokens=100, max_tokens=50)

    with pytest.raises(ValueError, match="overlap_tokens must be non-negative and < target_tokens"):
        DeterministicChunker(target_tokens=100, overlap_tokens=100)


def test_long_section_sliding_window_split() -> None:
    """Long section exceeding max_tokens (500) is split deterministically using sliding window."""
    chunker = DeterministicChunker(
        target_tokens=50,
        max_tokens=60,
        overlap_tokens=10,
    )
    # 120 words under a single heading
    section_text = "# Long Section\n\n" + " ".join(f"word{i}" for i in range(120))
    doc = CanonicalKnowledgeDocumentDTO(
        document_id="doc_longsec11223344556677",
        title="Long Section Doc",
        document_type="documentation",
        source_reference="docs://long-section",
        canonical_content=section_text,
        content_hash="1122334455667788990011223344556677889900112233445566778899001122",
        corpus_category=CorpusCategory.DOCUMENTATION,
    )

    chunks = chunker.chunk_document(doc)
    assert len(chunks) >= 2
    for idx, c in enumerate(chunks):
        assert c.chunk_index == idx
        assert c.chunk_id == f"{doc.document_id}_c{idx:04d}"
        assert len(c.chunk_id) <= 64
        assert count_tokens(c.content) <= 60


def test_plain_text_split_paragraphs() -> None:
    """Plain text without headings is split on paragraph boundaries deterministically."""
    chunker = DeterministicChunker(
        target_tokens=30,
        max_tokens=40,
        overlap_tokens=5,
    )
    paragraphs = [
        "Paragraph zero has several introductory words describing the system architecture.",
        "Paragraph one goes into details about how PostgreSQL stores documents and chunks.",
        "Paragraph two discusses FastEmbed local embeddings with 384 dimensions.",
        "Paragraph three covers advisory locking and transaction boundaries in Knowledge MCP.",
    ]
    plain_content = "\n\n".join(paragraphs)
    doc = CanonicalKnowledgeDocumentDTO(
        document_id="doc_plain1122334455667788",
        title="Plain Doc",
        document_type="documentation",
        source_reference="docs://plain-doc",
        canonical_content=plain_content,
        content_hash="3344556677889900112233445566778899001122334455667788990011223344",
        corpus_category=CorpusCategory.DOCUMENTATION,
    )

    chunks = chunker.chunk_document(doc)
    assert len(chunks) >= 2
    for idx, c in enumerate(chunks):
        assert c.chunk_index == idx
        assert c.chunk_id == f"{doc.document_id}_c{idx:04d}"
        assert len(c.chunk_id) <= 64


def test_chunk_identity_and_no_path_influence_or_randomness() -> None:
    """Chunk identity is stable, <=64 chars, and unaffected by filesystem path or randomness."""
    chunker = DeterministicChunker()
    content = (
        "# Main Guide\n\n"
        "This is static content for identity validation.\n\n"
        "## Subtopic\n\n"
        "Subtopic text."
    )

    doc_a = CanonicalKnowledgeDocumentDTO(
        document_id="doc_stable11223344556677",
        title="Doc A",
        document_type="documentation",
        source_reference="docs://path/a/guide.md",
        canonical_content=content,
        content_hash="5566778899001122334455667788990011223344556677889900112233445566",
        corpus_category=CorpusCategory.DOCUMENTATION,
    )
    doc_b = CanonicalKnowledgeDocumentDTO(
        document_id="doc_stable11223344556677",
        title="Doc B (Different Title and Ref)",
        document_type="documentation",
        source_reference="docs://completely/different/path/guide.md",
        canonical_content=content,
        content_hash="5566778899001122334455667788990011223344556677889900112233445566",
        corpus_category=CorpusCategory.DOCUMENTATION,
    )

    chunks_a = chunker.chunk_document(doc_a)
    chunks_b = chunker.chunk_document(doc_b)

    assert len(chunks_a) == len(chunks_b)
    for ca, cb in zip(chunks_a, chunks_b, strict=True):
        assert ca.chunk_id == cb.chunk_id
        assert ca.chunk_index == cb.chunk_index
        assert ca.content == cb.content
        assert len(ca.chunk_id) <= 64
        assert not any(sym in ca.chunk_id for sym in ["/", "\\", ":", " "])


def test_heading_boundaries_h3_level() -> None:
    """Markdown ### heading boundaries are recognized and split appropriately."""
    chunker = DeterministicChunker(target_tokens=30, max_tokens=50, overlap_tokens=10)
    sec1 = "### Sub-sub Section One\n\nWord1 word2 word3 word4 word5 word6 word7 word8 word9."
    sec2 = "### Sub-sub Section Two\n\nWordA wordB wordC wordD wordE wordF wordG wordH wordI."
    doc = CanonicalKnowledgeDocumentDTO(
        document_id="doc_h3heading1122334455",
        title="H3 Doc",
        document_type="documentation",
        source_reference="docs://h3-doc",
        canonical_content=f"{sec1}\n\n{sec2}",
        content_hash="33" * 32,
        corpus_category=CorpusCategory.DOCUMENTATION,
    )
    chunks = chunker.chunk_document(doc)
    assert len(chunks) == 2
    assert "Sub-sub Section One" in chunks[0].content
    assert "Sub-sub Section Two" in chunks[1].content
    assert chunks[0].chunk_index == 0
    assert chunks[1].chunk_index == 1


def test_sliding_window_exact_overlap_tokens() -> None:
    """Oversized section split verifies exact 64 lexical token overlap."""
    chunker = DeterministicChunker(
        target_tokens=450,
        max_tokens=500,
        overlap_tokens=64,
    )
    # Generate 700 distinct words under one heading
    words = [f"tok{i}" for i in range(700)]
    doc = CanonicalKnowledgeDocumentDTO(
        document_id="doc_overlap112233445566",
        title="Overlap Doc",
        document_type="documentation",
        source_reference="docs://overlap-doc",
        canonical_content="# Heading\n\n" + " ".join(words),
        content_hash="44" * 32,
        corpus_category=CorpusCategory.DOCUMENTATION,
    )
    chunks = chunker.chunk_document(doc)
    assert len(chunks) >= 2
    tokens_c0 = count_tokens(chunks[0].content)
    assert tokens_c0 == 450

    c0_toks = _RE_TOKEN.findall(chunks[0].content)
    c1_toks = _RE_TOKEN.findall(chunks[1].content)
    # Overlap must be exact 64 lexical token units
    assert c0_toks[-64:] == c1_toks[:64]


def test_chunks_never_exceed_max_tokens_ceiling() -> None:
    """Every produced chunk across mixed content strictly respects max_tokens=500."""
    chunker = DeterministicChunker()
    sections = [
        "# Heading 1\n\n" + " ".join(f"wA{i}" for i in range(300)),
        "## Heading 2\n\n" + " ".join(f"wB{i}" for i in range(800)),
        "### Heading 3\n\n" + " ".join(f"wC{i}" for i in range(250)),
    ]
    doc = CanonicalKnowledgeDocumentDTO(
        document_id="doc_ceiling112233445566",
        title="Ceiling Doc",
        document_type="documentation",
        source_reference="docs://ceiling-doc",
        canonical_content="\n\n".join(sections),
        content_hash="55" * 32,
        corpus_category=CorpusCategory.DOCUMENTATION,
    )
    chunks = chunker.chunk_document(doc)
    assert len(chunks) > 1
    for c in chunks:
        assert count_tokens(c.content) <= 500


def test_boundary_exactly_100_chunks_accepted() -> None:
    """Document that produces exactly 100 chunks is accepted without exceeding ceiling."""
    chunker = DeterministicChunker(
        target_tokens=10,
        max_tokens=15,
        overlap_tokens=2,
        max_chunks=100,
    )
    sections = [f"## Section {i}\n\n" + " ".join(f"word{j}" for j in range(8)) for i in range(100)]
    doc = CanonicalKnowledgeDocumentDTO(
        document_id="doc_exact100chunks1122",
        title="Exact 100 Chunks",
        document_type="documentation",
        source_reference="docs://exact-100",
        canonical_content="\n\n".join(sections),
        content_hash="66" * 32,
        corpus_category=CorpusCategory.DOCUMENTATION,
    )
    chunks = chunker.chunk_document(doc)
    assert len(chunks) == 100
    assert chunks[0].chunk_index == 0
    assert chunks[99].chunk_index == 99
    assert chunks[99].chunk_id == f"{doc.document_id}_c0099"


def test_chunk_ids_and_indices_unique_and_sequential() -> None:
    """All chunk IDs are unique, <=64 chars, and chunk indices are strictly monotonic 0..N-1."""
    chunker = DeterministicChunker(target_tokens=20, max_tokens=25, overlap_tokens=5)
    paragraphs = [
        f"Paragraph {i} contains some words for verification of uniqueness." for i in range(25)
    ]
    doc = CanonicalKnowledgeDocumentDTO(
        document_id="doc_uniqueidx112233445",
        title="Unique Index Doc",
        document_type="documentation",
        source_reference="docs://unique-idx",
        canonical_content="\n\n".join(paragraphs),
        content_hash="77" * 32,
        corpus_category=CorpusCategory.DOCUMENTATION,
    )
    chunks = chunker.chunk_document(doc)
    assert len(chunks) >= 10
    seen_ids: set[str] = set()
    for expected_idx, c in enumerate(chunks):
        assert c.chunk_index == expected_idx
        assert c.chunk_id == f"{doc.document_id}_c{expected_idx:04d}"
        assert len(c.chunk_id) <= 64
        assert c.chunk_id not in seen_ids
        seen_ids.add(c.chunk_id)


def test_chunk_draft_dto_frozen_and_no_embedding_field() -> None:
    """ChunkDraftDTO strictly forbids embedding field and is immutable."""
    draft = ChunkDraftDTO(
        chunk_id="doc_123_c0000",
        document_id="doc_123",
        chunk_index=0,
        content="Sample text",
    )
    assert not hasattr(draft, "embedding")

    with pytest.raises(ValidationError):
        draft.content = "New text"

    with pytest.raises(ValidationError):
        ChunkDraftDTO(
            chunk_id="doc_123_c0000",
            document_id="doc_123",
            chunk_index=0,
            content="Sample text",
            embedding=(0.1,) * 384,  # type: ignore[call-arg]
        )


def test_chunking_deterministic_across_different_instances() -> None:
    """Multiple independent DeterministicChunker instances produce identical results."""
    chunker1 = DeterministicChunker()
    chunker2 = DeterministicChunker()

    doc = CanonicalKnowledgeDocumentDTO(
        document_id="doc_instances112233445",
        title="Instances Doc",
        document_type="documentation",
        source_reference="docs://instances-doc",
        canonical_content=(
            "# Title\n\nContent for cross-instance determinism.\n\n## Sub\n\nMore content."
        ),
        content_hash="88" * 32,
        corpus_category=CorpusCategory.DOCUMENTATION,
    )

    res1 = chunker1.chunk_document(doc)
    res2 = chunker2.chunk_document(doc)

    assert res1 == res2
