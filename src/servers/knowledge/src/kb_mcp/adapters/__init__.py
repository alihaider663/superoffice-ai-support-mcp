"""Knowledge MCP Adapter Layer exports."""

from kb_mcp.adapters.factory import (
    KnowledgeRuntimeContext,
    compose_knowledge_runtime,
    create_embedding_provider,
    create_knowledge_engine,
    create_knowledge_repository,
    create_knowledge_session_factory,
)
from kb_mcp.adapters.fastembed_provider import FastEmbedEmbeddingProvider
from kb_mcp.adapters.filesystem_artifact_store import (
    FilesystemKnowledgeArtifactStore,
    validate_artifact_root,
)
from kb_mcp.adapters.postgres_repository import PostgresKnowledgeRepository
from kb_mcp.adapters.supabase_repository import SupabaseKnowledgeRepository

__all__ = [
    "FastEmbedEmbeddingProvider",
    "FilesystemKnowledgeArtifactStore",
    "KnowledgeRuntimeContext",
    "PostgresKnowledgeRepository",
    "SupabaseKnowledgeRepository",
    "compose_knowledge_runtime",
    "create_embedding_provider",
    "create_knowledge_engine",
    "create_knowledge_repository",
    "create_knowledge_session_factory",
    "validate_artifact_root",
]
