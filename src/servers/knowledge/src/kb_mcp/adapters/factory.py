"""Factory for creating Knowledge PostgreSQL database engine and runtime composition."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool

from kb_mcp.adapters.fastembed_provider import FastEmbedEmbeddingProvider
from kb_mcp.adapters.postgres_repository import PostgresKnowledgeRepository
from kb_mcp.contracts.constants import DEFAULT_EMBEDDING_MODEL
from kb_mcp.contracts.errors import (
    EmbeddingModelInitializationError,
    KnowledgeRuntimeInitializationError,
)
from kb_mcp.services.knowledge_service import KnowledgeApplicationService

if TYPE_CHECKING:
    from kb_mcp.settings import KnowledgeServerSettings

logger = logging.getLogger(__name__)


def create_knowledge_engine(settings: KnowledgeServerSettings) -> AsyncEngine:
    """Create a SQLAlchemy 2.0 AsyncEngine configured for Knowledge PostgreSQL retrieval.

    Never logs credentials or connection strings containing passwords.
    """
    if not settings.is_database_configured:
        raise KnowledgeRuntimeInitializationError(
            "Cannot create database engine: KNOWLEDGE_DATABASE_URL is not configured."
        )

    try:
        url = settings.get_async_database_url()
    except Exception as exc:
        logger.error("Failed to parse or normalize Knowledge database URL: %s", type(exc).__name__)
        raise KnowledgeRuntimeInitializationError(
            f"Invalid Knowledge database URL configuration: {exc}"
        ) from exc

    try:
        engine = create_async_engine(
            url,
            poolclass=AsyncAdaptedQueuePool,
            pool_size=settings.pool_size,
            max_overflow=settings.max_overflow,
            pool_recycle=settings.pool_recycle_seconds,
            pool_pre_ping=settings.pool_pre_ping,
        )
        logger.info(
            "knowledge_postgres_engine_created",
            extra={
                "backend": "postgresql",
                "pool_pre_ping": settings.pool_pre_ping,
                "pool_size": settings.pool_size,
            },
        )
        return engine
    except Exception as exc:
        logger.error(
            "Failed to initialize Knowledge PostgreSQL AsyncEngine: %s", type(exc).__name__
        )
        raise KnowledgeRuntimeInitializationError(
            f"Failed to create Knowledge database engine: {type(exc).__name__}"
        ) from exc


def create_knowledge_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a configured session factory bound to the async engine."""
    return async_sessionmaker(bind=engine, expire_on_commit=False)


def create_knowledge_repository(
    settings: KnowledgeServerSettings,
    *,
    session_factory: async_sessionmaker[AsyncSession] | AsyncEngine,
) -> PostgresKnowledgeRepository:
    """Create a configured PostgresKnowledgeRepository."""
    return PostgresKnowledgeRepository(
        session_factory=session_factory,
        timeout_seconds=float(settings.timeout_seconds),
        max_results_ceiling=settings.max_search_results_ceiling,
    )


def create_embedding_provider(
    settings: KnowledgeServerSettings,
    *,
    model_instance: Any | None = None,
) -> FastEmbedEmbeddingProvider:
    """Create a configured FastEmbedEmbeddingProvider.

    Ensures the model name strictly matches the approved BAAI/bge-small-en-v1.5 model.
    """
    if settings.embedding_model != DEFAULT_EMBEDDING_MODEL:
        raise EmbeddingModelInitializationError(
            f"Unsupported embedding model '{settings.embedding_model}'. "
            f"Only '{DEFAULT_EMBEDDING_MODEL}' is approved."
        )

    try:
        provider = FastEmbedEmbeddingProvider(
            model_name=settings.embedding_model,
            cache_dir=settings.embedding_cache_dir,
            model_instance=model_instance,
        )
        logger.info(
            "fastembed_embedding_provider_created",
            extra={
                "model_name": settings.embedding_model,
                "dimension": 384,
            },
        )
        return provider
    except Exception as exc:
        logger.error("Failed to initialize FastEmbedEmbeddingProvider: %s", type(exc).__name__)
        if isinstance(
            exc, (EmbeddingModelInitializationError, KnowledgeRuntimeInitializationError)
        ):
            raise
        raise KnowledgeRuntimeInitializationError(
            f"Failed to initialize embedding provider: {type(exc).__name__}"
        ) from exc


@dataclass
class KnowledgeRuntimeContext:
    """Container managing configured Knowledge runtime components and lifecycle."""

    service: KnowledgeApplicationService
    repository: PostgresKnowledgeRepository
    embedding_provider: FastEmbedEmbeddingProvider
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    async def close(self) -> None:
        """Cleanly dispose of runtime resources upon server shutdown."""
        logger.info("Disposing Knowledge PostgreSQL database engine")
        await self.engine.dispose()


def compose_knowledge_runtime(
    settings: KnowledgeServerSettings,
    *,
    engine: AsyncEngine | None = None,
    embedding_provider: FastEmbedEmbeddingProvider | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    model_instance: Any | None = None,
) -> KnowledgeRuntimeContext:
    """Compose the complete configured Knowledge runtime with repository, provider, and service."""
    if not settings.is_database_configured:
        raise KnowledgeRuntimeInitializationError(
            "Cannot compose Knowledge runtime: KNOWLEDGE_DATABASE_URL is not configured."
        )

    active_engine = engine or create_knowledge_engine(settings)
    active_session_factory = session_factory or create_knowledge_session_factory(active_engine)
    active_repo = create_knowledge_repository(settings, session_factory=active_session_factory)
    active_provider = embedding_provider or create_embedding_provider(
        settings, model_instance=model_instance
    )
    active_service = KnowledgeApplicationService(
        repository=active_repo,
        embedding_provider=active_provider,
    )

    return KnowledgeRuntimeContext(
        service=active_service,
        repository=active_repo,
        embedding_provider=active_provider,
        engine=active_engine,
        session_factory=active_session_factory,
    )
