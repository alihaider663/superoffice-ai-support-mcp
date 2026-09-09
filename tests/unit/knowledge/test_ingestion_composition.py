"""Unit tests for Knowledge Ingestion pipeline composition.

Gate 7D.5E: Component wiring and isolation verification.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from kb_mcp.contracts.errors import (
    KnowledgeArtifactError,
    KnowledgeRuntimeInitializationError,
)
from kb_mcp.ingestion.chunking import DeterministicChunker
from kb_mcp.ingestion.composition import (
    IngestionPipelineContext,
    compose_dry_run_pipeline,
    compose_ingestion_pipeline,
)
from kb_mcp.ingestion.orchestrator import KnowledgeIngestionCoordinator
from kb_mcp.ingestion.service import KnowledgeAdmissionService
from kb_mcp.settings import KnowledgeServerSettings


def test_compose_dry_run_pipeline_returns_isolated_instances() -> None:
    """compose_dry_run_pipeline should return admission service and chunker without persistence."""
    admission_service, chunker = compose_dry_run_pipeline()

    assert isinstance(admission_service, KnowledgeAdmissionService)
    assert isinstance(chunker, DeterministicChunker)


def test_compose_ingestion_pipeline_fails_without_database_url(tmp_path: Path) -> None:
    """compose_ingestion_pipeline must fail when database_url is unconfigured."""
    settings = KnowledgeServerSettings(
        database_url=None,
        artifact_root=tmp_path / "artifacts",
    )

    with pytest.raises(
        KnowledgeRuntimeInitializationError, match="KNOWLEDGE_DATABASE_URL is not configured"
    ):
        compose_ingestion_pipeline(settings)


def test_compose_ingestion_pipeline_fails_without_artifact_root() -> None:
    """compose_ingestion_pipeline must fail when artifact_root is unconfigured."""
    settings = KnowledgeServerSettings(
        database_url=SecretStr("postgresql://test:test@localhost:5432/test"),
        artifact_root=None,
    )

    with pytest.raises(KnowledgeArtifactError) as exc_info:
        compose_ingestion_pipeline(settings)
    assert exc_info.value.error_code == "ARTIFACT_ROOT_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_compose_ingestion_pipeline_wires_all_components(tmp_path: Path) -> None:
    """compose_ingestion_pipeline should wire coordinator with all required dependencies."""
    settings = KnowledgeServerSettings(
        database_url=SecretStr("postgresql://test:test@localhost:5432/test"),
        artifact_root=tmp_path / "artifacts",
    )

    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()
    mock_session_factory = MagicMock()
    mock_repo = MagicMock()
    mock_store = MagicMock()
    mock_provider = MagicMock()

    with (
        patch("kb_mcp.ingestion.composition.create_knowledge_engine", return_value=mock_engine),
        patch(
            "kb_mcp.ingestion.composition.create_knowledge_session_factory",
            return_value=mock_session_factory,
        ),
        patch(
            "kb_mcp.ingestion.composition.create_knowledge_ingestion_repository",
            return_value=mock_repo,
        ),
        patch("kb_mcp.ingestion.composition.create_embedding_provider", return_value=mock_provider),
        patch(
            "kb_mcp.ingestion.composition.FilesystemKnowledgeArtifactStore", return_value=mock_store
        ),
        patch(
            "kb_mcp.ingestion.composition.validate_artifact_root",
            return_value=tmp_path / "artifacts",
        ),
    ):
        ctx = compose_ingestion_pipeline(settings)

        assert isinstance(ctx, IngestionPipelineContext)
        assert isinstance(ctx.admission_service, KnowledgeAdmissionService)
        assert isinstance(ctx.chunker, DeterministicChunker)
        assert isinstance(ctx.coordinator, KnowledgeIngestionCoordinator)
        assert ctx.repository is mock_repo
        assert ctx.artifact_store is mock_store
        assert ctx.embedding_provider is mock_provider
        assert ctx.engine is mock_engine
        assert ctx.session_factory is mock_session_factory

        await ctx.close()
        mock_engine.dispose.assert_awaited_once()
