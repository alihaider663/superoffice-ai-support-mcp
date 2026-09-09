"""Deterministic heading-aware document chunking for Knowledge ingestion.

Gate 7D.5D: Local-v1 Deterministic Chunker.
"""

from __future__ import annotations

import re
from typing import Final

from kb_mcp.contracts.constants import (
    CHUNK_MAX_TOKENS,
    CHUNK_OVERLAP_TOKENS,
    CHUNK_TARGET_TOKENS,
    MAX_CHUNKS_PER_DOCUMENT,
)
from kb_mcp.contracts.errors import KnowledgeChunkingError
from kb_mcp.contracts.ingestion import (
    CanonicalKnowledgeDocumentDTO,
    ChunkDraftDTO,
)

# Regex matching words and individual punctuation symbols for lexical token estimation
_RE_TOKEN: Final[re.Pattern[str]] = re.compile(r"\w+|[^\w\s]", re.UNICODE)

# Regex matching markdown headings (#, ##, ###) at the start of a line
_RE_HEADING: Final[re.Pattern[str]] = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)


def count_tokens(text: str) -> int:
    """Deterministic lexical token count estimate (words and punctuation symbols).

    These represent deterministic Local-v1 chunking token units / estimates,
    providing model-agnostic, stable lexical boundary sizing.
    """
    return len(_RE_TOKEN.findall(text))


class DeterministicChunker:
    """Deterministic, heading-aware chunker producing ordered ChunkDraftDTO instances.

    Pure-function component:
    - Never accesses database or filesystem.
    - Never accesses embedding model or external APIs.
    - Purely deterministic: same input + constants = byte-identical ordered chunks.
    """

    def __init__(
        self,
        target_tokens: int = CHUNK_TARGET_TOKENS,
        max_tokens: int = CHUNK_MAX_TOKENS,
        overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
        max_chunks: int = MAX_CHUNKS_PER_DOCUMENT,
    ) -> None:
        if target_tokens <= 0:
            raise ValueError(f"target_tokens must be positive, got {target_tokens}")
        if max_tokens < target_tokens:
            raise ValueError(
                f"max_tokens must be >= target_tokens ({max_tokens} < {target_tokens})"
            )
        if overlap_tokens < 0 or overlap_tokens >= target_tokens:
            raise ValueError(
                f"overlap_tokens must be non-negative and < target_tokens ({overlap_tokens})"
            )
        if max_chunks <= 0:
            raise ValueError(f"max_chunks must be positive, got {max_chunks}")

        self._target_tokens = target_tokens
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens
        self._max_chunks = max_chunks

    def chunk_document(
        self,
        document: CanonicalKnowledgeDocumentDTO,
    ) -> tuple[ChunkDraftDTO, ...]:
        """Chunk an approved CanonicalKnowledgeDocumentDTO into ordered ChunkDraftDTOs.

        Args:
            document: Approved CanonicalKnowledgeDocumentDTO.

        Returns:
            Tuple of ordered ChunkDraftDTOs.

        Raises:
            TypeError: If document is not CanonicalKnowledgeDocumentDTO.
            KnowledgeChunkingError: If document content is empty, yields 0 chunks,
                or exceeds max_chunks ceiling.
        """
        if not isinstance(document, CanonicalKnowledgeDocumentDTO):
            raise TypeError(
                f"DeterministicChunker requires CanonicalKnowledgeDocumentDTO, "
                f"got '{type(document).__name__}'."
            )

        content = document.canonical_content
        if not content or not content.strip():
            raise KnowledgeChunkingError(
                "Cannot chunk document with empty or whitespace-only canonical content.",
                error_code="EMPTY_CANONICAL_CONTENT",
            )

        # Extract semantic sections
        raw_sections = self._partition_into_sections(content)

        # Break any oversized section using sliding window
        chunk_texts: list[str] = []
        for sec in raw_sections:
            sec_token_count = count_tokens(sec)
            if sec_token_count <= self._max_tokens:
                clean_sec = sec.strip()
                if clean_sec:
                    chunk_texts.append(clean_sec)
            else:
                sub_chunks = self._split_token_window(sec)
                chunk_texts.extend(sub_chunks)

        if not chunk_texts:
            raise KnowledgeChunkingError(
                "No chunks were generated from canonical content.",
                error_code="NO_CHUNKS_GENERATED",
            )

        if len(chunk_texts) > self._max_chunks:
            raise KnowledgeChunkingError(
                f"Document chunking produced {len(chunk_texts)} chunks, exceeding the "
                f"maximum allowed limit of {self._max_chunks} chunks.",
                error_code="CHUNK_LIMIT_EXCEEDED",
                details={"chunk_count": len(chunk_texts), "max_allowed": self._max_chunks},
            )

        # Form deterministic ChunkDraftDTO instances
        drafts: list[ChunkDraftDTO] = []
        seen_ids: set[str] = set()

        for idx, text_block in enumerate(chunk_texts):
            chunk_id = f"{document.document_id}_c{idx:04d}"
            if chunk_id in seen_ids:
                raise KnowledgeChunkingError(
                    f"Duplicate chunk identifier generated: '{chunk_id}'.",
                    error_code="DUPLICATE_CHUNK_ID",
                )
            seen_ids.add(chunk_id)

            drafts.append(
                ChunkDraftDTO(
                    chunk_id=chunk_id,
                    document_id=document.document_id,
                    chunk_index=idx,
                    content=text_block,
                )
            )

        return tuple(drafts)

    def _partition_into_sections(self, text: str) -> list[str]:
        """Partition text into semantic sections based on headings or paragraphs."""
        heading_matches = list(_RE_HEADING.finditer(text))

        if heading_matches:
            sections: list[str] = []
            # Text preceding the first heading
            if heading_matches[0].start() > 0:
                pre = text[: heading_matches[0].start()].strip()
                if pre:
                    sections.append(pre)

            # Each heading and its following body
            for i, match in enumerate(heading_matches):
                start = match.start()
                end = heading_matches[i + 1].start() if i + 1 < len(heading_matches) else len(text)
                sec = text[start:end].strip()
                if sec:
                    sections.append(sec)
            return sections

        # Plain text without headings: partition on paragraph boundaries
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        sections = []
        buf: list[str] = []
        buf_tokens = 0

        for p in paragraphs:
            p_tokens = count_tokens(p)
            if buf_tokens + p_tokens <= self._target_tokens:
                buf.append(p)
                buf_tokens += p_tokens
            else:
                if buf:
                    sections.append("\n\n".join(buf))
                    buf = []
                    buf_tokens = 0
                if p_tokens <= self._max_tokens:
                    buf.append(p)
                    buf_tokens = p_tokens
                else:
                    sections.append(p)

        if buf:
            sections.append("\n\n".join(buf))

        return sections if sections else [text.strip()]

    def _split_token_window(self, text: str) -> list[str]:
        """Deterministically split text into sliding-window token chunks."""
        tokens = list(_RE_TOKEN.finditer(text))
        if not tokens:
            return []

        if len(tokens) <= self._max_tokens:
            clean = text.strip()
            return [clean] if clean else []

        chunks: list[str] = []
        start_idx = 0
        total_tokens = len(tokens)
        step = max(1, self._target_tokens - self._overlap_tokens)

        while start_idx < total_tokens:
            end_idx = min(start_idx + self._target_tokens, total_tokens)
            char_start = tokens[start_idx].start()
            char_end = tokens[end_idx - 1].end()
            chunk_text = text[char_start:char_end].strip()
            if chunk_text:
                chunks.append(chunk_text)

            if end_idx >= total_tokens:
                break
            start_idx += step

        return chunks
