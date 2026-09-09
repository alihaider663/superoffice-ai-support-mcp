"""Runtime composition and wiring for Knowledge ingestion and dry-run pipelines.

Gate 7D.5E: Internal pipeline composition isolating in-memory dry-run from full persistence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from kb_mcp.adapters.factory import (
    create_embedding_provider,
    create_knowledge_engine,
    create_knowledge_ingestion_repository,
    create_knowledge_session_factory,
)
from kb_mcp.adapters.filesystem_artifact_store import (
    FilesystemKnowledgeArtifactStore,
    validate_artifact_root,
)
from kb_mcp.contracts.errors import (
    KnowledgeArtifactError,
    KnowledgeRuntimeInitializationError,
)
from kb_mcp.ingestion.chunking import DeterministicChunker
from kb_mcp.ingestion.orchestrator import KnowledgeIngestionCoordinator
from kb_mcp.ingestion.service import KnowledgeAdmissionService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import (
        AsyncEngine,
        AsyncSession,
        async_sessionmaker,
    )

    from kb_mcp.contracts.interfaces import (
        EmbeddingProvider,
        KnowledgeArtifactStore,
        KnowledgeIngestionRepository,
    )
    from kb_mcp.settings import KnowledgeServerSettings

logger = logging.getLogger(__name__)


def compose_dry_run_pipeline() -> tuple[KnowledgeAdmissionService, DeterministicChunker]:
    """Compose purely in-memory pipeline for dry-run evaluation.

    Guarantees:
    - Zero PostgreSQL connectivity or queries.
    - Zero filesystem artifact staging or storage.
    - Zero FastEmbed model initialization, tokenization, or embedding inference.
    """
    admission_service = KnowledgeAdmissionService()
    chunker = DeterministicChunker()
    return admission_service, chunker


@dataclass
class IngestionPipelineContext:
    """Container managing configured Knowledge ingestion components and lifecycle."""

    admission_service: KnowledgeAdmissionService
    chunker: DeterministicChunker
    coordinator: KnowledgeIngestionCoordinator
    repository: KnowledgeIngestionRepository
    artifact_store: KnowledgeArtifactStore
    embedding_provider: EmbeddingProvider
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    async def close(self) -> None:
        """Cleanly dispose of database engine and underlying connection pool."""
        logger.info("Disposing Knowledge Ingestion PostgreSQL database engine")
        await self.engine.dispose()


def compose_ingestion_pipeline(
    settings: KnowledgeServerSettings,
    *,
    engine: AsyncEngine | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    repository: KnowledgeIngestionRepository | None = None,
    artifact_store: KnowledgeArtifactStore | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    model_instance: Any | None = None,
) -> IngestionPipelineContext:
    """Compose the full ingestion pipeline with transactional persistence and artifact storage."""
    if not settings.is_database_configured:
        raise KnowledgeRuntimeInitializationError(
            "Cannot compose Knowledge ingestion pipeline: KNOWLEDGE_DATABASE_URL is not configured."
        )

    if settings.artifact_root is None or not str(settings.artifact_root).strip():
        raise KnowledgeArtifactError(
            "Cannot compose Knowledge ingestion pipeline: "
            "KNOWLEDGE_ARTIFACT_ROOT is not configured.",
            error_code="ARTIFACT_ROOT_NOT_CONFIGURED",
        )

    # Validate artifact root security boundaries (rejects scratch, git root, relative paths)
    validate_artifact_root(settings.artifact_root)

    active_engine = engine or create_knowledge_engine(settings)
    active_session_factory = session_factory or create_knowledge_session_factory(active_engine)
    active_repo = repository or create_knowledge_ingestion_repository(
        settings, session_factory=active_session_factory
    )
    active_artifact_store = artifact_store or FilesystemKnowledgeArtifactStore(
        artifact_root=settings.artifact_root
    )
    active_embedding_provider = embedding_provider or create_embedding_provider(
        settings, model_instance=model_instance
    )

    admission_service = KnowledgeAdmissionService()
    chunker = DeterministicChunker()
    coordinator = KnowledgeIngestionCoordinator(
        chunker=chunker,
        embedding_provider=active_embedding_provider,
        artifact_store=active_artifact_store,
        repository=active_repo,
    )

    return IngestionPipelineContext(
        admission_service=admission_service,
        chunker=chunker,
        coordinator=coordinator,
        repository=active_repo,
        artifact_store=active_artifact_store,
        embedding_provider=active_embedding_provider,
        engine=active_engine,
        session_factory=active_session_factory,
    )
