"""Constants and architectural invariants for the Knowledge Base MCP server."""

from typing import Final

# Frozen architecture invariant: 384-dimensional vector embedding
EMBEDDING_DIMENSION: Final[int] = 384

# Approved local embedding model
DEFAULT_EMBEDDING_MODEL: Final[str] = "BAAI/bge-small-en-v1.5"

# ============================================================================
# Ingestion Size Limits & Boundaries (Gate 7D.5B / Local-v1)
# ============================================================================

MAX_SOURCE_FILE_BYTES: Final[int] = 2_097_152  # 2 MiB
MAX_CANONICAL_TEXT_BYTES: Final[int] = 524_288  # 512 KiB
MIN_SOURCE_TEXT_BYTES: Final[int] = 10

# Mass-PII fail-closed boundary
MAX_REDACTABLE_PII_OCCURRENCES: Final[int] = 10

# Structured Runbook bounds
RUNBOOK_ID_MIN_LENGTH: Final[int] = 1
RUNBOOK_ID_MAX_LENGTH: Final[int] = 64
RUNBOOK_TITLE_MIN_LENGTH: Final[int] = 1
RUNBOOK_TITLE_MAX_LENGTH: Final[int] = 255
RUNBOOK_PROBLEM_DESC_MIN_CHARS: Final[int] = 1
RUNBOOK_PROBLEM_DESC_MAX_CHARS: Final[int] = 8192
RUNBOOK_MIN_STEPS: Final[int] = 1
RUNBOOK_MAX_STEPS: Final[int] = 30
RUNBOOK_STEP_MAX_LENGTH: Final[int] = 1000
RUNBOOK_SOURCE_REF_MAX_LENGTH: Final[int] = 128
RUNBOOK_PRODUCT_MAX_LENGTH: Final[int] = 100
RUNBOOK_VERIFIED_VERSION_MAX_LENGTH: Final[int] = 50

# Structured Known Issue bounds
KNOWN_ISSUE_ID_MIN_LENGTH: Final[int] = 1
KNOWN_ISSUE_ID_MAX_LENGTH: Final[int] = 64
KNOWN_ISSUE_TITLE_MIN_LENGTH: Final[int] = 1
KNOWN_ISSUE_TITLE_MAX_LENGTH: Final[int] = 255
KNOWN_ISSUE_SYMPTOM_MIN_CHARS: Final[int] = 1
KNOWN_ISSUE_SYMPTOM_MAX_CHARS: Final[int] = 8192
KNOWN_ISSUE_ROOT_CAUSE_MAX_CHARS: Final[int] = 8192
KNOWN_ISSUE_WORKAROUND_MAX_CHARS: Final[int] = 8192
KNOWN_ISSUE_SOURCE_REF_MAX_LENGTH: Final[int] = 128
KNOWN_ISSUE_FIX_REF_MAX_LENGTH: Final[int] = 128
KNOWN_ISSUE_MAX_AFFECTED_PRODUCTS: Final[int] = 20
KNOWN_ISSUE_PRODUCT_MAX_LENGTH: Final[int] = 100
KNOWN_ISSUE_MAX_AFFECTED_VERSIONS: Final[int] = 20
KNOWN_ISSUE_VERSION_MAX_LENGTH: Final[int] = 50
KNOWN_ISSUE_CATEGORY_MAX_LENGTH: Final[int] = 50
