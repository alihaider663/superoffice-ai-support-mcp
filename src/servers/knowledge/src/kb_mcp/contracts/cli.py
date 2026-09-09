"""Contracts, exit codes, and DTOs for the internal Knowledge Ingestion CLI.

Gate 7D.5E: Local Operator CLI & Full Knowledge Ingestion E2E.
"""

from enum import IntEnum
from typing import Literal

from pydantic import ConfigDict, Field

from platform_core.models import PlatformBaseModel


class CliExitCode(IntEnum):
    """Standardized process exit codes for the Knowledge Ingestion CLI."""

    SUCCESS = 0
    VALIDATION_ERROR = 2
    CONFIG_ERROR = 3
    RUNTIME_UNAVAILABLE = 4
    PERSISTENCE_ERROR = 5


class DryRunResultDTO(PlatformBaseModel):
    """Immutable result of a non-mutating dry-run ingestion evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["DRY_RUN_VALID"] = "DRY_RUN_VALID"
    document_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Deterministic document identifier",
    )
    source_reference: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Validated logical provenance reference",
    )
    document_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Canonical document type classification",
    )
    corpus_category: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Corpus category classification",
    )
    content_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="Deterministic SHA-256 content hash",
    )
    predicted_chunk_count: int = Field(
        ...,
        ge=1,
        description="Predicted number of chunks produced by deterministic chunking",
    )
    structured_record_type: str | None = Field(
        default=None,
        description="Structured payload kind if runbook or known issue, else None",
    )
