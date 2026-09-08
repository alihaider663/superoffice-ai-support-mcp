"""Constants and architectural invariants for the Knowledge Base MCP server."""

from typing import Final

# Frozen architecture invariant: 384-dimensional vector embedding
EMBEDDING_DIMENSION: Final[int] = 384

# Approved local embedding model
DEFAULT_EMBEDDING_MODEL: Final[str] = "BAAI/bge-small-en-v1.5"
