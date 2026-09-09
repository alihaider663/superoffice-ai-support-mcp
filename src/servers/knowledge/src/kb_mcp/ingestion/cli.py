"""Operator CLI for internal Knowledge Ingestion and dry-run evaluation.

Gate 7D.5E: Local Operator CLI & Full Knowledge Ingestion E2E.
Module: kb_mcp.ingestion.cli
Entrypoint: python -m kb_mcp.ingestion.cli [dry-run|ingest] [options]
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

# Prevent OpenBLAS/ONNX thread allocation exhaustion on Windows
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from sqlalchemy.exc import SQLAlchemyError

from kb_mcp.contracts.cli import CliExitCode, DryRunResultDTO
from kb_mcp.contracts.constants import (
    ALLOWED_DOCUMENT_TYPES,
    MAX_SOURCE_FILE_BYTES,
)
from kb_mcp.contracts.errors import (
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingInferenceError,
    EmbeddingModelInitializationError,
    KnowledgeAdmissionError,
    KnowledgeArtifactError,
    KnowledgeChunkingError,
    KnowledgeContentRejectedError,
    KnowledgePersistenceError,
    KnowledgeRuntimeInitializationError,
    KnowledgeSizeLimitExceededError,
    KnowledgeSourceFormatError,
)
from kb_mcp.contracts.ingestion import (
    AdmissionSourceInputDTO,
    CorpusCategory,
    IngestionResultDTO,
    IngestionSourceKind,
)
from kb_mcp.ingestion.canonical import build_canonical_document
from kb_mcp.ingestion.composition import (
    compose_dry_run_pipeline,
    compose_ingestion_pipeline,
)
from kb_mcp.settings import KnowledgeServerSettings

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

# Approved extension and source type definitions
_ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".md", ".markdown", ".txt", ".json"})
_GENERAL_DOC_EXTENSIONS: frozenset[str] = frozenset({".md", ".markdown", ".txt"})
_STRUCTURED_EXTENSIONS: frozenset[str] = frozenset({".json"})
_STRUCTURED_TYPES: frozenset[str] = frozenset({"runbook", "known_issue"})
_GENERAL_DOC_TYPES: frozenset[str] = frozenset({"documentation", "sop", "incident_pattern"})


class _CliArgumentError(Exception):
    """Internal exception raised when CLI arguments fail validation."""


class _IngestionArgumentParser(argparse.ArgumentParser):
    """Custom argument parser that does not directly exit on validation error."""

    def error(self, message: str) -> NoReturn:
        sys.stderr.write(f"CLI Error: {message}\n")
        raise _CliArgumentError(message)


def _build_argument_parser() -> _IngestionArgumentParser:
    """Construct the command-line argument parser with dry-run and ingest subcommands."""
    parser = _IngestionArgumentParser(
        prog="kb-ingest",
        description="SuperOffice AI Support — Knowledge Ingestion CLI",
        add_help=True,
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="subcommands",
        description="Valid ingestion operations",
        required=True,
    )

    def _add_common_arguments(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "-f",
            "--file",
            required=True,
            help="Path to local source document file (.md, .markdown, .txt, or .json)",
        )
        subparser.add_argument(
            "-t",
            "--type",
            required=True,
            choices=sorted(ALLOWED_DOCUMENT_TYPES),
            help=(
                "Mandatory document type: "
                "documentation, sop, incident_pattern, runbook, or known_issue"
            ),
        )
        subparser.add_argument(
            "-r",
            "--source-reference",
            default=None,
            help=(
                "Logical provenance URI. Required for .md, .markdown, .txt. "
                "Forbidden for structured .json files."
            ),
        )
        subparser.add_argument(
            "--json",
            action="store_true",
            default=False,
            help="Format CLI output as JSON",
        )

    dry_run_parser = subparsers.add_parser(
        "dry-run",
        help="Validate, sanitize, canonicalize, and chunk without DB, artifact store, or FastEmbed",
    )
    _add_common_arguments(dry_run_parser)

    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Execute full transactional knowledge ingestion pipeline",
    )
    _add_common_arguments(ingest_parser)

    return parser


def _route_source(
    file_path: Path,
    doc_type: str,
    source_reference: str | None,
) -> tuple[IngestionSourceKind, CorpusCategory, str | None]:
    """Validate extensions, route types to categories/kinds, and enforce provenance rules."""
    ext = file_path.suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise _CliArgumentError(
            f"Unsupported file extension '{ext}'. Allowed extensions: {sorted(_ALLOWED_EXTENSIONS)}"
        )

    if doc_type not in ALLOWED_DOCUMENT_TYPES:
        raise _CliArgumentError(
            f"Invalid source type '{doc_type}'. Allowed types: {sorted(ALLOWED_DOCUMENT_TYPES)}"
        )

    if ext in _GENERAL_DOC_EXTENSIONS:
        if doc_type in _STRUCTURED_TYPES:
            raise _CliArgumentError(
                f"Structured type '{doc_type}' requires a .json file, but got '{ext}'."
            )

        if not source_reference or not source_reference.strip():
            raise _CliArgumentError(
                f"--source-reference is strictly required for general documents ({ext}). "
                "Operator must provide explicit logical provenance."
            )

        source_ref = source_reference.strip()
        category = CorpusCategory(doc_type)
        kind = (
            IngestionSourceKind.TEXT_DOCUMENT
            if ext == ".txt"
            else IngestionSourceKind.MARKDOWN_DOCUMENT
        )
        return kind, category, source_ref

    if ext in _STRUCTURED_EXTENSIONS:
        if doc_type not in _STRUCTURED_TYPES:
            raise _CliArgumentError(
                f"General document type '{doc_type}' cannot be ingested from a .json file. "
                f"Expected general extension ({sorted(_GENERAL_DOC_EXTENSIONS)})."
            )

        if source_reference is not None:
            raise _CliArgumentError(
                f"--source-reference is not accepted for structured JSON input ({doc_type}). "
                "The validated JSON payload is the sole authority for canonical provenance."
            )

        category = CorpusCategory(doc_type)
        kind = (
            IngestionSourceKind.RUNBOOK_JSON
            if doc_type == "runbook"
            else IngestionSourceKind.KNOWN_ISSUE_JSON
        )
        return kind, category, None

    msg = f"Unhandled routing for file '{file_path.name}' with type '{doc_type}'."
    raise _CliArgumentError(msg)


def _read_source_file(file_path: Path) -> bytes:
    """Read local source file with bounded size check up to MAX_SOURCE_FILE_BYTES."""
    if not file_path.exists():
        raise _CliArgumentError(f"Source file does not exist: {file_path}")
    if not file_path.is_file():
        raise _CliArgumentError(f"Source path is not a regular file: {file_path}")

    file_size = file_path.stat().st_size
    if file_size > MAX_SOURCE_FILE_BYTES:
        raise KnowledgeSizeLimitExceededError(
            f"Source file size ({file_size} bytes) exceeds the maximum allowed limit "
            f"({MAX_SOURCE_FILE_BYTES} bytes / 2 MiB)."
        )

    with file_path.open("rb") as f:
        raw_bytes = f.read(MAX_SOURCE_FILE_BYTES + 1)

    if len(raw_bytes) > MAX_SOURCE_FILE_BYTES:
        raise KnowledgeSizeLimitExceededError(
            f"Source file content exceeds the maximum allowed limit "
            f"({MAX_SOURCE_FILE_BYTES} bytes / 2 MiB)."
        )

    return raw_bytes


def _execute_dry_run(
    source_input: AdmissionSourceInputDTO,
    source_reference: str | None,
) -> DryRunResultDTO:
    """Execute purely in-memory dry-run pipeline."""
    admission_service, chunker = compose_dry_run_pipeline()

    admitted = admission_service.admit_or_raise(source_input)
    if admitted.sanitized_payload is None:
        raise KnowledgeAdmissionError("Admitted decision missing sanitized payload.")
    sanitized_payload = admitted.sanitized_payload

    if source_reference is not None:
        canonical_doc = build_canonical_document(
            sanitized_payload,
            source_reference=source_reference,
        )
    else:
        canonical_doc = build_canonical_document(
            sanitized_payload,
        )

    chunk_drafts = chunker.chunk_document(canonical_doc)
    if not chunk_drafts:
        raise KnowledgeChunkingError(
            f"Dry-run evaluation produced 0 chunks for document {canonical_doc.document_id}."
        )

    structured_type = (
        canonical_doc.document_type
        if canonical_doc.document_type in ("runbook", "known_issue")
        else None
    )

    return DryRunResultDTO(
        status="DRY_RUN_VALID",
        document_id=canonical_doc.document_id,
        source_reference=canonical_doc.source_reference,
        document_type=canonical_doc.document_type,
        corpus_category=canonical_doc.corpus_category.value,
        content_hash=canonical_doc.content_hash,
        predicted_chunk_count=len(chunk_drafts),
        structured_record_type=structured_type,
    )


async def _execute_ingest(
    source_input: AdmissionSourceInputDTO,
    source_reference: str | None,
    settings: KnowledgeServerSettings,
) -> IngestionResultDTO:
    """Execute full transactional ingestion pipeline."""
    context = compose_ingestion_pipeline(settings)
    try:
        admitted = context.admission_service.admit_or_raise(source_input)
        if admitted.sanitized_payload is None:
            raise KnowledgeAdmissionError("Admitted decision missing sanitized payload.")
        sanitized_payload = admitted.sanitized_payload

        if source_reference is not None:
            canonical_doc = build_canonical_document(
                sanitized_payload,
                source_reference=source_reference,
            )
        else:
            canonical_doc = build_canonical_document(
                sanitized_payload,
            )

        return await context.coordinator.ingest(canonical_doc)
    finally:
        await context.close()


def _print_dry_run_output(dry_run_dto: DryRunResultDTO, json_output: bool) -> None:
    """Format and print dry-run result."""
    if json_output:
        print(dry_run_dto.model_dump_json(indent=2))
    else:
        print(
            f"DRY RUN SUCCESS:\n"
            f"  Document ID:     {dry_run_dto.document_id}\n"
            f"  Source Ref:      {dry_run_dto.source_reference}\n"
            f"  Type:            {dry_run_dto.document_type}\n"
            f"  Category:        {dry_run_dto.corpus_category}\n"
            f"  Content Hash:    {dry_run_dto.content_hash}\n"
            f"  Predicted Chunks: {dry_run_dto.predicted_chunk_count}\n"
            f"  Status:          {dry_run_dto.status}"
        )


def _print_ingest_output(result: IngestionResultDTO, json_output: bool) -> None:
    """Format and print real ingest result."""
    if json_output:
        print(result.model_dump_json(indent=2))
    else:
        print(
            f"INGESTION SUCCESS:\n"
            f"  Document ID:     {result.document_id}\n"
            f"  Source Ref:      {result.source_reference}\n"
            f"  Content Hash:    {result.content_hash}\n"
            f"  Version:         {result.version}\n"
            f"  Chunks:          {result.chunk_count}\n"
            f"  Status:          {result.status.value}"
        )


def _map_exception_to_exit_code(exc: Exception) -> int:
    """Translate caught exceptions into standardized process exit codes."""
    code: CliExitCode = CliExitCode.PERSISTENCE_ERROR
    if isinstance(
        exc,
        (
            _CliArgumentError,
            KnowledgeAdmissionError,
            KnowledgeContentRejectedError,
            KnowledgeSizeLimitExceededError,
            KnowledgeSourceFormatError,
            KnowledgeChunkingError,
            ValueError,
        ),
    ):
        sys.stderr.write(f"Validation Error: {exc}\n")
        code = CliExitCode.VALIDATION_ERROR
    elif isinstance(exc, KnowledgeRuntimeInitializationError):
        msg = str(exc)
        if "not configured" in msg.lower() or "invalid knowledge database url" in msg.lower():
            sys.stderr.write(f"Configuration Error: {exc}\n")
            code = CliExitCode.CONFIG_ERROR
        elif "embedding" in msg.lower() or "model" in msg.lower():
            sys.stderr.write(f"Runtime Unavailable: {exc}\n")
            code = CliExitCode.RUNTIME_UNAVAILABLE
        elif "database" in msg.lower() or "engine" in msg.lower():
            sys.stderr.write(f"Persistence Error: {exc}\n")
            code = CliExitCode.PERSISTENCE_ERROR
        else:
            sys.stderr.write(f"Runtime Error: {exc}\n")
            code = CliExitCode.RUNTIME_UNAVAILABLE
    elif isinstance(exc, KnowledgeArtifactError):
        msg = str(exc)
        if "not configured" in msg.lower() or exc.error_code == "ARTIFACT_ROOT_NOT_CONFIGURED":
            sys.stderr.write(f"Configuration Error: {exc}\n")
            code = CliExitCode.CONFIG_ERROR
        else:
            sys.stderr.write(f"Persistence Error: {exc}\n")
            code = CliExitCode.PERSISTENCE_ERROR
    elif isinstance(
        exc,
        (
            EmbeddingModelInitializationError,
            EmbeddingInferenceError,
            EmbeddingDimensionError,
            EmbeddingError,
        ),
    ):
        sys.stderr.write(f"Runtime Unavailable: {exc}\n")
        code = CliExitCode.RUNTIME_UNAVAILABLE
    elif isinstance(exc, (KnowledgePersistenceError, SQLAlchemyError)):
        sys.stderr.write(f"Persistence Error: {exc}\n")
        code = CliExitCode.PERSISTENCE_ERROR
    else:
        logger.error("Unexpected CLI ingestion error: %s", type(exc).__name__)
        sys.stderr.write(f"Persistence Error: {type(exc).__name__}\n")
        code = CliExitCode.PERSISTENCE_ERROR

    return int(code)


async def async_main(argv: Sequence[str] | None = None) -> int:
    """Asynchronous programmatic entrypoint for Knowledge Ingestion operations."""
    parser = _build_argument_parser()

    try:
        parsed_args = parser.parse_args(argv)
    except _CliArgumentError:
        return int(CliExitCode.VALIDATION_ERROR)
    except SystemExit as err:
        return int(err.code) if isinstance(err.code, int) else int(CliExitCode.VALIDATION_ERROR)

    try:
        file_path = Path(parsed_args.file)
        source_kind, corpus_category, validated_ref = _route_source(
            file_path=file_path,
            doc_type=parsed_args.type,
            source_reference=parsed_args.source_reference,
        )
        raw_bytes = _read_source_file(file_path)

        source_input = AdmissionSourceInputDTO(
            source_name=file_path.name,
            source_kind=source_kind,
            corpus_category=corpus_category,
            raw_bytes=raw_bytes,
            source_reference=validated_ref,
        )

        if parsed_args.command == "dry-run":
            dto = _execute_dry_run(source_input, validated_ref)
            _print_dry_run_output(dto, parsed_args.json)
            return int(CliExitCode.SUCCESS)

        if parsed_args.command == "ingest":
            settings = KnowledgeServerSettings()
            result = await _execute_ingest(source_input, validated_ref, settings)
            _print_ingest_output(result, parsed_args.json)
            return int(CliExitCode.SUCCESS)

        sys.stderr.write(f"Unknown command '{parsed_args.command}'.\n")
        return int(CliExitCode.VALIDATION_ERROR)

    except Exception as exc:
        return _map_exception_to_exit_code(exc)


def main(argv: Sequence[str] | None = None) -> int:
    """Synchronous programmatic and process entrypoint for Knowledge Ingestion operations."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(lambda: asyncio.run(async_main(argv)))
            return future.result()

    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    sys.exit(main())
