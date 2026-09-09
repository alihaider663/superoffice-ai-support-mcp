"""FastEmbed adapter implementing the EmbeddingProvider protocol."""

import asyncio
import math
import os
from collections.abc import Sequence
from typing import Any

# Prevent OpenBLAS/ONNX thread allocation exhaustion on Windows
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from fastembed import TextEmbedding

from kb_mcp.contracts.constants import DEFAULT_EMBEDDING_MODEL, EMBEDDING_DIMENSION
from kb_mcp.contracts.errors import (
    EmbeddingDimensionError,
    EmbeddingInferenceError,
    EmbeddingInputError,
    EmbeddingModelInitializationError,
)
from kb_mcp.contracts.interfaces import EmbeddingProvider
from platform_observability.logging import get_logger

logger = get_logger(__name__)


class FastEmbedEmbeddingProvider(EmbeddingProvider):
    """FastEmbed implementation of the EmbeddingProvider protocol using ONNX Runtime.

    Executes inference locally using the approved BAAI/bge-small-en-v1.5 model.
    Inference is offloaded to a worker thread via asyncio.to_thread
    to keep the event loop responsive.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        cache_dir: str | None = None,
        threads: int | None = None,
        local_files_only: bool = False,
        model_instance: Any | None = None,
    ) -> None:
        if model_name != DEFAULT_EMBEDDING_MODEL:
            raise EmbeddingModelInitializationError(
                f"Unsupported embedding model '{model_name}'. "
                f"Only '{DEFAULT_EMBEDDING_MODEL}' is approved."
            )
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._threads = threads
        self._local_files_only = local_files_only

        if model_instance is not None:
            self._model = model_instance
        else:
            try:
                self._model = TextEmbedding(
                    model_name=model_name,
                    cache_dir=cache_dir,
                    threads=threads,
                    local_files_only=local_files_only,
                )
            except Exception as exc:
                logger.error(
                    "fastembed_model_init_failed",
                    model=model_name,
                    error=type(exc).__name__,
                )
                raise EmbeddingModelInitializationError(
                    f"Failed to initialize FastEmbed model '{model_name}': {type(exc).__name__}"
                ) from exc

    async def embed_query(self, text: str) -> tuple[float, ...]:
        """Generate a dense vector embedding for a search query string.

        Args:
            text: Non-empty search query string.

        Returns:
            Tuple of floats representing the dense vector embedding (length 384).

        Raises:
            EmbeddingInputError: If query text is empty, whitespace-only, or invalid.
            EmbeddingInferenceError: If inference fails or produces non-finite values.
            EmbeddingDimensionError: If embedding dimension does not match 384.
        """
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingInputError("Query text cannot be empty or whitespace-only.")

        return await asyncio.to_thread(self._sync_embed_query, text)

    def _sync_embed_query(self, text: str) -> tuple[float, ...]:
        """Execute FastEmbed query embedding synchronously."""
        try:
            embeddings_gen = self._model.query_embed(text)
            raw_vec = next(iter(embeddings_gen))
        except Exception as exc:
            logger.error(
                "fastembed_query_inference_failed",
                model=self._model_name,
                error=type(exc).__name__,
            )
            raise EmbeddingInferenceError(
                f"FastEmbed query inference failed: {type(exc).__name__}"
            ) from exc

        return self._validate_and_convert_vector(raw_vec)

    async def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Generate dense vector embeddings for a sequence of document/chunk texts.

        Preserves input ordering. Empty input sequence returns ().

        Args:
            texts: Sequence of non-empty document strings.

        Returns:
            Tuple of embedding tuples, each of length 384.

        Raises:
            EmbeddingInputError: If any document is empty, whitespace-only, or invalid.
            EmbeddingInferenceError: If inference fails or count does not match.
            EmbeddingDimensionError: If any embedding dimension does not match 384.
        """
        if not isinstance(texts, Sequence) or isinstance(texts, (str, bytes)):
            raise EmbeddingInputError("Documents must be provided as a sequence of strings.")

        if len(texts) == 0:
            return ()

        for idx, item in enumerate(texts):
            if not isinstance(item, str) or not item.strip():
                raise EmbeddingInputError(
                    f"Document text at index {idx} cannot be empty or whitespace-only."
                )

        return await asyncio.to_thread(self._sync_embed_documents, texts)

    def _sync_embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Execute FastEmbed document batch embedding synchronously."""
        try:
            embeddings_gen = self._model.passage_embed(texts)
            raw_vecs = list(embeddings_gen)
        except Exception as exc:
            logger.error(
                "fastembed_document_inference_failed",
                model=self._model_name,
                batch_size=len(texts),
                error=type(exc).__name__,
            )
            raise EmbeddingInferenceError(
                f"FastEmbed document inference failed: {type(exc).__name__}"
            ) from exc

        if len(raw_vecs) != len(texts):
            raise EmbeddingInferenceError(
                f"Embedding count mismatch: expected {len(texts)}, got {len(raw_vecs)}."
            )

        return tuple(self._validate_and_convert_vector(vec) for vec in raw_vecs)

    def _validate_and_convert_vector(self, raw_vec: Any) -> tuple[float, ...]:
        """Validate vector length and values, converting to immutable float tuple."""
        try:
            vec_list = [float(val) for val in raw_vec]
        except (TypeError, ValueError) as exc:
            raise EmbeddingInferenceError("Failed to convert embedding values to float.") from exc

        if len(vec_list) != EMBEDDING_DIMENSION:
            raise EmbeddingDimensionError(
                actual_dimension=len(vec_list),
                expected_dimension=EMBEDDING_DIMENSION,
            )

        for val in vec_list:
            if not math.isfinite(val):
                raise EmbeddingInferenceError(
                    "Embedding vector contains non-finite values (NaN or Infinity)."
                )

        return tuple(vec_list)
