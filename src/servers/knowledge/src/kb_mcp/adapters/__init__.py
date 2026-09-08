"""Knowledge MCP Adapter Layer exports."""

from kb_mcp.adapters.fastembed_provider import FastEmbedEmbeddingProvider
from kb_mcp.adapters.postgres_repository import PostgresKnowledgeRepository
from kb_mcp.adapters.supabase_repository import SupabaseKnowledgeRepository

__all__ = [
    "FastEmbedEmbeddingProvider",
    "PostgresKnowledgeRepository",
    "SupabaseKnowledgeRepository",
]
