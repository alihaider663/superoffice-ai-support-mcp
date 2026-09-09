"""Unit tests for FastEmbedEmbeddingProvider and EmbeddingProvider protocol."""

import math
import os
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from kb_mcp.adapters.fastembed_provider import FastEmbedEmbeddingProvider
from kb_mcp.contracts.constants import DEFAULT_EMBEDDING_MODEL, EMBEDDING_DIMENSION
from kb_mcp.contracts.errors import (
    EmbeddingDimensionError,
    EmbeddingInferenceError,
    EmbeddingInputError,
    EmbeddingModelInitializationError,
)
from kb_mcp.contracts.interfaces import EmbeddingProvider
from kb_mcp.settings import KnowledgeServerSettings


class FakeTextEmbedding:
    """Mock FastEmbed model for deterministic offline unit tests."""

    def __init__(
        self,
        *,
        dimension: int = EMBEDDING_DIMENSION,
        raise_on_query: Exception | None = None,
        raise_on_passage: Exception | None = None,
        return_nan: bool = False,
        return_pos_inf: bool = False,
        return_neg_inf: bool = False,
        return_count_mismatch: bool = False,
    ) -> None:
        self.dimension = dimension
        self.raise_on_query = raise_on_query
        self.raise_on_passage = raise_on_passage
        self.return_nan = return_nan
        self.return_pos_inf = return_pos_inf
        self.return_neg_inf = return_neg_inf
        self.return_count_mismatch = return_count_mismatch

    def _make_vector(self, seed: float) -> list[float]:
        vec = [seed + (i * 0.001) for i in range(self.dimension)]
        if self.return_nan and len(vec) > 0:
            vec[0] = float("nan")
        elif self.return_pos_inf and len(vec) > 0:
            vec[0] = float("inf")
        elif self.return_neg_inf and len(vec) > 0:
            vec[0] = float("-inf")
        return vec

    def query_embed(self, query: str | Any, **kwargs: Any) -> Any:  # noqa: ARG002
        if self.raise_on_query:
            raise self.raise_on_query
        yield self._make_vector(0.1)

    def passage_embed(self, texts: Any, **kwargs: Any) -> Any:  # noqa: ARG002
        if self.raise_on_passage:
            raise self.raise_on_passage
        texts_list = list(texts)
        if self.return_count_mismatch:
            for i in range(max(0, len(texts_list) - 1)):
                yield self._make_vector(float(i + 1))
            return
        for i in range(len(texts_list)):
            yield self._make_vector(float(i + 1))


@pytest.fixture
def provider() -> FastEmbedEmbeddingProvider:
    """Fixture providing a FastEmbedEmbeddingProvider with a healthy fake model."""
    fake_model = FakeTextEmbedding()
    return FastEmbedEmbeddingProvider(model_instance=fake_model)


@pytest.mark.unit
async def test_implements_embedding_provider_protocol(
    provider: FastEmbedEmbeddingProvider,
) -> None:
    """Verify FastEmbedEmbeddingProvider satisfies runtime_checkable EmbeddingProvider."""
    assert isinstance(provider, EmbeddingProvider)


@pytest.mark.unit
async def test_query_returns_exactly_384_finite_floats(
    provider: FastEmbedEmbeddingProvider,
) -> None:
    """Verify embed_query returns immutable tuple of exactly 384 finite floats."""
    result = await provider.embed_query("PostgreSQL connection timeout")
    assert isinstance(result, tuple)
    assert len(result) == EMBEDDING_DIMENSION
    assert len(result) == 384
    assert all(isinstance(val, float) for val in result)
    assert all(math.isfinite(val) for val in result)


@pytest.mark.unit
async def test_document_batch_preserves_order(
    provider: FastEmbedEmbeddingProvider,
) -> None:
    """Verify document embedding preserves input sequence order."""
    texts = [
        "Database connection pool exhausted",
        "IIS worker process recycling event",
        "Disk latency exceeded threshold",
    ]
    results = await provider.embed_documents(texts)
    assert isinstance(results, tuple)
    assert len(results) == 3
    for vec in results:
        assert isinstance(vec, tuple)
        assert len(vec) == 384
        assert all(math.isfinite(val) for val in vec)

    # First float reflects sequence order seed in FakeTextEmbedding
    assert results[0][0] == pytest.approx(1.0, abs=0.01)
    assert results[1][0] == pytest.approx(2.0, abs=0.01)
    assert results[2][0] == pytest.approx(3.0, abs=0.01)


@pytest.mark.unit
async def test_multiple_documents_return_matching_count(
    provider: FastEmbedEmbeddingProvider,
) -> None:
    """Verify returned embedding count exactly matches input document count."""
    texts = [f"Synthetic document text {i}" for i in range(10)]
    results = await provider.embed_documents(texts)
    assert len(results) == 10


@pytest.mark.unit
async def test_empty_document_batch_returns_empty_tuple(
    provider: FastEmbedEmbeddingProvider,
) -> None:
    """Verify empty document input returns empty tuple without calling model."""
    results = await provider.embed_documents([])
    assert results == ()


@pytest.mark.unit
@pytest.mark.parametrize("invalid_query", ["", "   ", " \t\n ", None, 12345])
async def test_whitespace_and_invalid_query_rejected(
    provider: FastEmbedEmbeddingProvider,
    invalid_query: Any,
) -> None:
    """Verify empty, whitespace-only, or non-string query raises EmbeddingInputError."""
    with pytest.raises(EmbeddingInputError):
        await provider.embed_query(invalid_query)


@pytest.mark.unit
@pytest.mark.parametrize(
    "invalid_docs",
    [
        None,
        "not_a_sequence_of_strings",
        ["valid doc", ""],
        ["valid doc", "   "],
        ["valid doc", None],
        ["valid doc", 42],
    ],
)
async def test_invalid_document_input_rejected(
    provider: FastEmbedEmbeddingProvider,
    invalid_docs: Any,
) -> None:
    """Verify empty items or invalid types in document batch raise EmbeddingInputError."""
    with pytest.raises(EmbeddingInputError):
        await provider.embed_documents(invalid_docs)


@pytest.mark.unit
async def test_wrong_embedding_dimension_on_query_fails_closed() -> None:
    """Verify dimension mismatch on query raises EmbeddingDimensionError."""
    bad_model = FakeTextEmbedding(dimension=256)
    bad_provider = FastEmbedEmbeddingProvider(model_instance=bad_model)
    with pytest.raises(EmbeddingDimensionError) as exc_info:
        await bad_provider.embed_query("Query with invalid output dimension")
    assert exc_info.value.details.get("expected") == 384
    assert exc_info.value.details.get("actual") == 256


@pytest.mark.unit
async def test_wrong_embedding_dimension_on_document_fails_closed() -> None:
    """Verify dimension mismatch on documents raises EmbeddingDimensionError."""
    bad_model = FakeTextEmbedding(dimension=512)
    bad_provider = FastEmbedEmbeddingProvider(model_instance=bad_model)
    with pytest.raises(EmbeddingDimensionError) as exc_info:
        await bad_provider.embed_documents(["Valid document text"])
    assert exc_info.value.details.get("expected") == 384
    assert exc_info.value.details.get("actual") == 512


@pytest.mark.unit
async def test_nan_fails_closed() -> None:
    """Verify NaN values in query or documents raise EmbeddingInferenceError."""
    nan_model = FakeTextEmbedding(return_nan=True)
    nan_provider = FastEmbedEmbeddingProvider(model_instance=nan_model)

    with pytest.raises(EmbeddingInferenceError, match="non-finite"):
        await nan_provider.embed_query("Query returning NaN")

    with pytest.raises(EmbeddingInferenceError, match="non-finite"):
        await nan_provider.embed_documents(["Doc returning NaN"])


@pytest.mark.unit
async def test_positive_infinity_fails_closed() -> None:
    """Verify positive Infinity in embedding raises EmbeddingInferenceError."""
    inf_model = FakeTextEmbedding(return_pos_inf=True)
    inf_provider = FastEmbedEmbeddingProvider(model_instance=inf_model)

    with pytest.raises(EmbeddingInferenceError, match="non-finite"):
        await inf_provider.embed_query("Query returning +Inf")

    with pytest.raises(EmbeddingInferenceError, match="non-finite"):
        await inf_provider.embed_documents(["Doc returning +Inf"])


@pytest.mark.unit
async def test_negative_infinity_fails_closed() -> None:
    """Verify negative Infinity in embedding raises EmbeddingInferenceError."""
    ninf_model = FakeTextEmbedding(return_neg_inf=True)
    ninf_provider = FastEmbedEmbeddingProvider(model_instance=ninf_model)

    with pytest.raises(EmbeddingInferenceError, match="non-finite"):
        await ninf_provider.embed_query("Query returning -Inf")

    with pytest.raises(EmbeddingInferenceError, match="non-finite"):
        await ninf_provider.embed_documents(["Doc returning -Inf"])


@pytest.mark.unit
async def test_model_exception_maps_to_typed_safe_error() -> None:
    """Verify underlying model inference exceptions map to EmbeddingInferenceError."""
    crash_model = FakeTextEmbedding(
        raise_on_query=RuntimeError("Internal ONNX inference crash"),
        raise_on_passage=RuntimeError("Internal ONNX passage crash"),
    )
    crash_provider = FastEmbedEmbeddingProvider(model_instance=crash_model)

    with pytest.raises(EmbeddingInferenceError) as query_exc:
        await crash_provider.embed_query("Query that crashes ONNX")
    assert "FastEmbed query inference failed" in query_exc.value.message

    with pytest.raises(EmbeddingInferenceError) as doc_exc:
        await crash_provider.embed_documents(["Doc that crashes ONNX"])
    assert "FastEmbed document inference failed" in doc_exc.value.message


@pytest.mark.unit
async def test_document_count_mismatch_fails_closed() -> None:
    """Verify generator returning fewer vectors than inputs raises EmbeddingInferenceError."""
    mismatch_model = FakeTextEmbedding(return_count_mismatch=True)
    mismatch_provider = FastEmbedEmbeddingProvider(model_instance=mismatch_model)

    with pytest.raises(EmbeddingInferenceError, match="Embedding count mismatch"):
        await mismatch_provider.embed_documents(["Doc 1", "Doc 2", "Doc 3"])


@pytest.mark.unit
def test_unapproved_model_rejected_on_initialization() -> None:
    """Verify initialization with unapproved model raises error."""
    with pytest.raises(EmbeddingModelInitializationError) as exc_info:
        FastEmbedEmbeddingProvider(model_name="unapproved/model-768")
    assert "Unsupported embedding model" in exc_info.value.message


@pytest.mark.unit
def test_model_init_exception_maps_to_typed_error() -> None:
    """Verify TextEmbedding constructor failure maps to EmbeddingModelInitializationError."""
    with patch(
        "kb_mcp.adapters.fastembed_provider.TextEmbedding",
        side_effect=RuntimeError("Failed to load ONNX runtime library"),
    ):
        with pytest.raises(EmbeddingModelInitializationError) as exc_info:
            FastEmbedEmbeddingProvider()
        assert "Failed to initialize FastEmbed model" in exc_info.value.message


@pytest.mark.unit
async def test_provider_does_not_return_numpy_or_generator(
    provider: FastEmbedEmbeddingProvider,
) -> None:
    """Verify provider returns immutable tuple of floats, never NumPy or generators."""
    query_result = await provider.embed_query("Check return types")
    assert type(query_result) is tuple
    assert type(query_result[0]) is float

    doc_result = await provider.embed_documents(["Check return types doc"])
    assert type(doc_result) is tuple
    assert type(doc_result[0]) is tuple
    assert type(doc_result[0][0]) is float


@pytest.mark.unit
def test_knowledge_server_settings_validates_embedding_model() -> None:
    """Verify settings only permits the approved embedding model."""
    valid_settings = KnowledgeServerSettings(embedding_model=DEFAULT_EMBEDDING_MODEL)
    assert valid_settings.embedding_model == DEFAULT_EMBEDDING_MODEL

    with pytest.raises(ValidationError):
        KnowledgeServerSettings(embedding_model="openai/text-embedding-3-small")


@pytest.mark.unit
def test_fastembed_environment_defaults_guard() -> None:
    """Verify OpenBLAS/OMP thread guard uses setdefault and preserves operator settings."""
    # If key is already set, setdefault must NOT overwrite it
    test_key = "OPENBLAS_NUM_THREADS"
    original_val = os.environ.get(test_key)
    try:
        os.environ[test_key] = "4"
        # setdefault on existing key returns existing value
        result = os.environ.setdefault(test_key, "1")
        assert result == "4"
        assert os.environ[test_key] == "4"
    finally:
        if original_val is not None:
            os.environ[test_key] = original_val
        else:
            os.environ.pop(test_key, None)

    # Provider public contract and constants remain intact
    fake_model = FakeTextEmbedding()
    p = FastEmbedEmbeddingProvider(model_instance=fake_model)
    assert p._model_name == DEFAULT_EMBEDDING_MODEL
    assert isinstance(p, EmbeddingProvider)
