"""Filesystem implementation of KnowledgeArtifactStore for safe approved-artifact storage.

Gate 7D.5C: Content-addressed immutable artifact storage and staging.
"""

import hashlib
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Final

from kb_mcp.contracts.constants import (
    ALLOWED_DOCUMENT_TYPES,
    CONTENT_HASH_HEX_LENGTH,
    DOCUMENT_ID_HASH_CHARS,
    DOCUMENT_ID_PREFIX,
    MAX_CANONICAL_TEXT_BYTES,
)
from kb_mcp.contracts.errors import KnowledgeArtifactError
from kb_mcp.contracts.ingestion import (
    ApprovedArtifactRecord,
    CanonicalKnowledgeDocumentDTO,
    StagedArtifactToken,
)

logger = logging.getLogger(__name__)

# Strict validation regexes
_RE_DOC_ID: Final[re.Pattern[str]] = re.compile(
    rf"^{DOCUMENT_ID_PREFIX}[0-9a-f]{{{DOCUMENT_ID_HASH_CHARS}}}$"
)
_RE_CONTENT_HASH: Final[re.Pattern[str]] = re.compile(rf"^[0-9a-f]{{{CONTENT_HASH_HEX_LENGTH}}}$")
_RE_STAGING_ID: Final[re.Pattern[str]] = re.compile(
    rf"^{DOCUMENT_ID_PREFIX}[0-9a-f]{{{DOCUMENT_ID_HASH_CHARS}}}_[0-9a-f]{{32}}\.tmp$"
)


def _normalize_resolved_path(path: Path) -> Path:
    """Safely normalize resolved paths, stripping Windows extended-length prefix if present."""
    path_str = str(path)
    if path_str.startswith("\\\\?\\") or path_str.startswith("//?/"):
        return Path(path_str[4:])
    return path


def _detect_git_root() -> Path | None:
    """Safely detect the project Git root by looking upward from this source file."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists():
            return parent
    return None


def validate_artifact_root(
    root: Path | str | None,
    git_root: Path | None = None,
) -> Path:
    """Validate that the configured artifact root satisfies strict security constraints.

    Constraints:
    - Must be configured (non-None, non-empty)
    - Must be an absolute path
    - Canonical resolved path must not be inside scratch
    - Canonical resolved path must not be the Git repository root or inside Git tree
    - Must not be a filesystem drive root

    Args:
        root: Candidate artifact root path.
        git_root: Optional explicit Git repository root for testing containment.

    Returns:
        Resolved canonical Path.

    Raises:
        KnowledgeArtifactError: If unconfigured or invalid.
    """
    if root is None:
        raise KnowledgeArtifactError(
            "Knowledge artifact root is not configured.",
            error_code="ARTIFACT_ROOT_NOT_CONFIGURED",
        )

    if isinstance(root, str):
        cleaned = root.strip()
        if not cleaned:
            raise KnowledgeArtifactError(
                "Knowledge artifact root is not configured.",
                error_code="ARTIFACT_ROOT_NOT_CONFIGURED",
            )
        candidate = Path(cleaned)
    else:
        candidate = root

    if not candidate.is_absolute():
        raise KnowledgeArtifactError(
            "Artifact root must be an absolute path.",
            error_code="ARTIFACT_ROOT_INVALID",
        )

    try:
        resolved = _normalize_resolved_path(candidate.resolve())
    except Exception as exc:
        raise KnowledgeArtifactError(
            "Failed to resolve artifact root path.",
            error_code="ARTIFACT_ROOT_INVALID",
        ) from exc

    # Reject filesystem drive roots (e.g. C:\ or /)
    if resolved == resolved.parent:
        raise KnowledgeArtifactError(
            "Artifact root cannot be a filesystem drive root.",
            error_code="ARTIFACT_ROOT_INVALID",
        )

    # Reject scratch directory
    parts_lower = [p.lower() for p in resolved.parts]
    if "scratch" in parts_lower or "antigravity-ide/scratch" in str(resolved).lower().replace(
        "\\", "/"
    ):
        raise KnowledgeArtifactError(
            "Artifact root cannot be located in scratch directory.",
            error_code="ARTIFACT_ROOT_INVALID",
        )

    # Reject project Git repository root and inner tree
    effective_git_root = git_root if git_root is not None else _detect_git_root()
    if effective_git_root is not None:
        try:
            resolved_git = _normalize_resolved_path(effective_git_root.resolve())
            if (
                resolved == resolved_git
                or resolved_git in resolved.parents
                or resolved.is_relative_to(resolved_git)
            ):
                raise KnowledgeArtifactError(
                    "Artifact root cannot be inside project Git repository.",
                    error_code="ARTIFACT_ROOT_INVALID",
                )
        except KnowledgeArtifactError:
            raise
        except Exception:
            pass

    return resolved


class FilesystemKnowledgeArtifactStore:
    """Safe, isolated filesystem adapter for knowledge artifact staging and approved storage.

    Layout:
      <artifact_root>/staging/<document_id>_<uuid>.tmp
      <artifact_root>/approved/<document_type>/<document_id>/<content_hash>.md
    """

    def __init__(
        self,
        artifact_root: Path | str | None = None,
        git_root: Path | None = None,
    ) -> None:
        """Initialize the store with a validated root, or unconfigured state."""
        self._git_root = git_root
        if artifact_root is not None:
            self._root: Path | None = validate_artifact_root(artifact_root, git_root=git_root)
            self._staging_dir: Path | None = self._root / "staging"
            self._approved_dir: Path | None = self._root / "approved"
            self._staging_dir.mkdir(parents=True, exist_ok=True)
            self._approved_dir.mkdir(parents=True, exist_ok=True)
        else:
            self._root = None
            self._staging_dir = None
            self._approved_dir = None

    def _ensure_configured(self) -> tuple[Path, Path, Path]:
        """Ensure the artifact store is configured and return (root, staging_dir, approved_dir)."""
        if self._root is None or self._staging_dir is None or self._approved_dir is None:
            raise KnowledgeArtifactError(
                "Knowledge artifact root is not configured.",
                error_code="ARTIFACT_ROOT_NOT_CONFIGURED",
            )
        return self._root, self._staging_dir, self._approved_dir

    def stage(self, document: CanonicalKnowledgeDocumentDTO) -> StagedArtifactToken:
        """Stage an approved canonical document to temporary staging storage.

        Args:
            document: Approved canonical document DTO.

        Returns:
            StagedArtifactToken referencing the staged artifact.

        Raises:
            KnowledgeArtifactError: If staging fails or bounds exceeded.
        """
        if not isinstance(document, CanonicalKnowledgeDocumentDTO):
            raise TypeError(
                f"Artifact storage requires an approved CanonicalKnowledgeDocumentDTO, "
                f"got '{type(document).__name__}'."
            )

        _, staging_dir, _ = self._ensure_configured()

        # Validate invariants
        if document.document_type not in ALLOWED_DOCUMENT_TYPES:
            raise KnowledgeArtifactError(
                f"Invalid document type '{document.document_type}'.",
                error_code="ARTIFACT_STAGE_FAILED",
            )

        if not _RE_DOC_ID.match(document.document_id):
            raise KnowledgeArtifactError(
                "Invalid document identifier format.",
                error_code="ARTIFACT_STAGE_FAILED",
            )

        if not _RE_CONTENT_HASH.match(document.content_hash):
            raise KnowledgeArtifactError(
                "Invalid content hash format.",
                error_code="ARTIFACT_STAGE_FAILED",
            )

        # Verify content hash matches canonical content exactly
        expected_hash = (
            hashlib.sha256(document.canonical_content.encode("utf-8")).hexdigest().lower()
        )
        if expected_hash != document.content_hash:
            raise KnowledgeArtifactError(
                "Content hash verification failed during staging.",
                error_code="ARTIFACT_HASH_MISMATCH",
            )

        encoded_bytes = document.canonical_content.encode("utf-8")
        if len(encoded_bytes) > MAX_CANONICAL_TEXT_BYTES:
            raise KnowledgeArtifactError(
                f"Canonical content size ({len(encoded_bytes)} bytes) exceeds maximum "
                f"allowed limit of {MAX_CANONICAL_TEXT_BYTES} bytes.",
                error_code="ARTIFACT_STAGE_FAILED",
            )

        # Staging file creation
        staging_id = f"{document.document_id}_{uuid.uuid4().hex}.tmp"
        staged_path = staging_dir / staging_id

        # Verify containment
        try:
            resolved_staged = _normalize_resolved_path(staged_path.resolve())
            resolved_staging_dir = _normalize_resolved_path(staging_dir.resolve())
            if (
                resolved_staging_dir not in resolved_staged.parents
                and not resolved_staged.is_relative_to(resolved_staging_dir)
            ):
                raise KnowledgeArtifactError(
                    "Staging path escapes staging directory.",
                    error_code="ARTIFACT_STAGE_FAILED",
                )
        except KnowledgeArtifactError:
            raise
        except Exception as exc:
            raise KnowledgeArtifactError(
                "Path resolution error during staging.",
                error_code="ARTIFACT_STAGE_FAILED",
            ) from exc

        try:
            with staged_path.open("xb") as f:
                f.write(encoded_bytes)
                f.flush()
        except Exception as exc:
            raise KnowledgeArtifactError(
                "Failed to write temporary staged artifact.",
                error_code="ARTIFACT_STAGE_FAILED",
            ) from exc

        logger.info(
            "knowledge_artifact_staged",
            extra={
                "operation": "stage",
                "document_id": document.document_id,
                "document_type": document.document_type,
                "content_hash_prefix": document.content_hash[:8],
                "status": "STAGED",
            },
        )

        return StagedArtifactToken(
            staging_id=staging_id,
            document_id=document.document_id,
            document_type=document.document_type,
            content_hash=document.content_hash,
        )

    def _verify_staged_content(self, staged_path: Path, expected_hash: str) -> bytes:
        """Verify that the staged artifact exists and matches expected content hash."""
        if not staged_path.is_file():
            raise KnowledgeArtifactError(
                "Staged artifact file does not exist or was already discarded.",
                error_code="ARTIFACT_PROMOTION_FAILED",
            )

        try:
            staged_bytes = staged_path.read_bytes()
        except Exception as exc:
            raise KnowledgeArtifactError(
                "Failed to read staged artifact for verification.",
                error_code="ARTIFACT_PROMOTION_FAILED",
            ) from exc

        actual_hash = hashlib.sha256(staged_bytes).hexdigest().lower()
        if actual_hash != expected_hash:
            staged_path.unlink(missing_ok=True)
            raise KnowledgeArtifactError(
                "Staged artifact content hash does not match expected hash.",
                error_code="ARTIFACT_HASH_MISMATCH",
            )
        return staged_bytes

    def _resolve_and_verify_dest(
        self, approved_dir: Path, document: CanonicalKnowledgeDocumentDTO
    ) -> Path:
        """Construct destination path and verify containment under approved_dir."""
        target_dir = approved_dir / document.document_type / document.document_id
        dest_path = target_dir / f"{document.content_hash}.md"

        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            resolved_dest = _normalize_resolved_path(dest_path.resolve())
            resolved_approved = _normalize_resolved_path(approved_dir.resolve())
            if resolved_approved not in resolved_dest.parents and not resolved_dest.is_relative_to(
                resolved_approved
            ):
                raise KnowledgeArtifactError(
                    "Artifact destination escapes approved storage directory.",
                    error_code="ARTIFACT_PROMOTION_FAILED",
                )
        except KnowledgeArtifactError:
            raise
        except Exception as exc:
            raise KnowledgeArtifactError(
                "Path resolution error during promotion.",
                error_code="ARTIFACT_PROMOTION_FAILED",
            ) from exc

        return dest_path

    def _handle_existing_artifact(
        self,
        dest_path: Path,
        staged_path: Path,
        staged_bytes: bytes,
        document: CanonicalKnowledgeDocumentDTO,
    ) -> ApprovedArtifactRecord:
        """Handle idempotent or contradictory existing approved artifact."""
        try:
            dest_bytes = dest_path.read_bytes()
            dest_hash = hashlib.sha256(dest_bytes).hexdigest().lower()
        except Exception as exc:
            raise KnowledgeArtifactError(
                "Failed to inspect existing artifact.",
                error_code="ARTIFACT_PROMOTION_FAILED",
            ) from exc

        if dest_hash == document.content_hash and dest_bytes == staged_bytes:
            staged_path.unlink(missing_ok=True)
            logger.info(
                "knowledge_artifact_promoted_idempotent",
                extra={
                    "operation": "promote",
                    "document_id": document.document_id,
                    "document_type": document.document_type,
                    "content_hash_prefix": document.content_hash[:8],
                    "status": "EXISTING_IDENTICAL",
                },
            )
            return ApprovedArtifactRecord(
                document_type=document.document_type,
                document_id=document.document_id,
                content_hash=document.content_hash,
            )

        raise KnowledgeArtifactError(
            "Artifact already exists with contradictory content.",
            error_code="ARTIFACT_HASH_MISMATCH",
        )

    def promote(
        self,
        token: StagedArtifactToken,
        document: CanonicalKnowledgeDocumentDTO,
    ) -> ApprovedArtifactRecord:
        """Atomically promote a staged artifact to content-addressed approved storage."""
        if not isinstance(token, StagedArtifactToken):
            raise TypeError(f"Expected StagedArtifactToken, got '{type(token).__name__}'.")
        if not isinstance(document, CanonicalKnowledgeDocumentDTO):
            raise TypeError(
                f"Expected CanonicalKnowledgeDocumentDTO, got '{type(document).__name__}'."
            )

        _, staging_dir, approved_dir = self._ensure_configured()

        if (
            token.document_id != document.document_id
            or token.document_type != document.document_type
            or token.content_hash != document.content_hash
        ):
            raise KnowledgeArtifactError(
                "Staged token parameters do not match canonical document.",
                error_code="ARTIFACT_PROMOTION_FAILED",
            )

        if not _RE_STAGING_ID.match(token.staging_id):
            raise KnowledgeArtifactError(
                "Invalid staging token identifier format.",
                error_code="ARTIFACT_PROMOTION_FAILED",
            )

        staged_path = staging_dir / token.staging_id
        staged_bytes = self._verify_staged_content(staged_path, document.content_hash)
        dest_path = self._resolve_and_verify_dest(approved_dir, document)

        if dest_path.exists():
            return self._handle_existing_artifact(dest_path, staged_path, staged_bytes, document)

        try:
            try:
                os.link(staged_path, dest_path)
                staged_path.unlink(missing_ok=True)
            except OSError as link_err:
                if isinstance(link_err, FileExistsError):
                    raise
                # Fallback for filesystems that do not support hardlinks (e.g. FAT or cross-device)
                with dest_path.open("xb") as f:
                    f.write(staged_bytes)
                    f.flush()
                staged_path.unlink(missing_ok=True)
        except FileExistsError:
            return self._handle_existing_artifact(dest_path, staged_path, staged_bytes, document)
        except Exception as exc:
            raise KnowledgeArtifactError(
                "Atomic artifact promotion failed.",
                error_code="ARTIFACT_PROMOTION_FAILED",
            ) from exc

        logger.info(
            "knowledge_artifact_promoted",
            extra={
                "operation": "promote",
                "document_id": document.document_id,
                "document_type": document.document_type,
                "content_hash_prefix": document.content_hash[:8],
                "status": "PROMOTED",
            },
        )

        return ApprovedArtifactRecord(
            document_type=document.document_type,
            document_id=document.document_id,
            content_hash=document.content_hash,
        )

    def discard_staged(self, token: StagedArtifactToken) -> bool:
        """Discard/remove a temporary staged artifact.

        Args:
            token: StagedArtifactToken to remove.

        Returns:
            True if removed, False if already absent.

        Raises:
            KnowledgeArtifactError: If staging_id is invalid.
        """
        if not isinstance(token, StagedArtifactToken):
            raise TypeError(f"Expected StagedArtifactToken, got '{type(token).__name__}'.")

        _, staging_dir, _ = self._ensure_configured()

        if not _RE_STAGING_ID.match(token.staging_id):
            raise KnowledgeArtifactError(
                "Invalid staging token identifier format.",
                error_code="ARTIFACT_CLEANUP_FAILED",
            )

        staged_path = staging_dir / token.staging_id
        try:
            resolved = _normalize_resolved_path(staged_path.resolve())
            resolved_staging = _normalize_resolved_path(staging_dir.resolve())
            if (
                resolved_staging not in resolved.parents
                and resolved != resolved_staging
                and not resolved.is_relative_to(resolved_staging)
            ):
                raise KnowledgeArtifactError(
                    "Staging path escapes staging directory.",
                    error_code="ARTIFACT_CLEANUP_FAILED",
                )
        except KnowledgeArtifactError:
            raise
        except Exception as exc:
            raise KnowledgeArtifactError(
                "Path resolution error during staging cleanup.",
                error_code="ARTIFACT_CLEANUP_FAILED",
            ) from exc

        if staged_path.is_file():
            staged_path.unlink()
            return True

        return False

    def remove_unreferenced(
        self,
        document_type: str,
        document_id: str,
        content_hash: str,
    ) -> bool:
        """Safely remove a verified unreferenced approved artifact.

        Args:
            document_type: Allowlisted document type.
            document_id: Validated deterministic document identifier.
            content_hash: Validated 64-char lowercase hex content hash.

        Returns:
            True if removed, False if already absent.

        Raises:
            KnowledgeArtifactError: If identifier parameters are invalid or outside root.
        """
        _, _, approved_dir = self._ensure_configured()

        if document_type not in ALLOWED_DOCUMENT_TYPES:
            raise KnowledgeArtifactError(
                f"Invalid document type '{document_type}'.",
                error_code="ARTIFACT_CLEANUP_FAILED",
            )

        if not _RE_DOC_ID.match(document_id):
            raise KnowledgeArtifactError(
                "Invalid document identifier format.",
                error_code="ARTIFACT_CLEANUP_FAILED",
            )

        if not _RE_CONTENT_HASH.match(content_hash):
            raise KnowledgeArtifactError(
                "Invalid content hash format.",
                error_code="ARTIFACT_CLEANUP_FAILED",
            )

        doc_dir = approved_dir / document_type / document_id
        target_path = doc_dir / f"{content_hash}.md"

        try:
            resolved_target = _normalize_resolved_path(target_path.resolve())
            resolved_approved = _normalize_resolved_path(approved_dir.resolve())
            if (
                resolved_approved not in resolved_target.parents
                and not resolved_target.is_relative_to(resolved_approved)
            ):
                raise KnowledgeArtifactError(
                    "Target artifact path escapes approved storage directory.",
                    error_code="ARTIFACT_CLEANUP_FAILED",
                )
        except KnowledgeArtifactError:
            raise
        except Exception as exc:
            raise KnowledgeArtifactError(
                "Path resolution error during artifact removal.",
                error_code="ARTIFACT_CLEANUP_FAILED",
            ) from exc

        if target_path.is_file():
            target_path.unlink()
            # Clean up empty parent directory if no other versions exist
            try:
                if doc_dir.is_dir() and not any(doc_dir.iterdir()):
                    doc_dir.rmdir()
            except Exception:
                pass
            return True

        return False

    def enumerate_approved_artifacts(self) -> list[ApprovedArtifactRecord]:
        """Enumerate all approved artifact records currently in storage for reconciliation.

        Scans the approved hierarchy:
          approved/<document_type>/<document_id>/<content_hash>.md

        Returns:
            List of approved artifact records without exposing physical paths.
        """
        _, _, approved_dir = self._ensure_configured()

        records: list[ApprovedArtifactRecord] = []
        if not approved_dir.exists():
            return records

        for type_entry in approved_dir.iterdir():
            if not type_entry.is_dir() or type_entry.name not in ALLOWED_DOCUMENT_TYPES:
                continue

            for doc_entry in type_entry.iterdir():
                if not doc_entry.is_dir() or not _RE_DOC_ID.match(doc_entry.name):
                    continue

                for file_entry in doc_entry.iterdir():
                    if not file_entry.is_file() or not file_entry.name.endswith(".md"):
                        continue

                    hash_part = file_entry.name[:-3]
                    if _RE_CONTENT_HASH.match(hash_part):
                        records.append(
                            ApprovedArtifactRecord(
                                document_type=type_entry.name,
                                document_id=doc_entry.name,
                                content_hash=hash_part,
                            )
                        )

        records.sort(key=lambda r: (r.document_type, r.document_id, r.content_hash))
        return records

    def cleanup_stale_staging(self, max_age_seconds: int = 3600) -> int:
        """Safely remove orphaned staging files older than the specified age threshold.

        Only files strictly matching the internal staging filename contract are candidates.

        Args:
            max_age_seconds: Threshold age in seconds (default: 3600).

        Returns:
            Count of cleaned stale staging files.
        """
        _, staging_dir, _ = self._ensure_configured()

        if not staging_dir.exists():
            return 0

        now = time.time()
        cleaned_count = 0

        for entry in staging_dir.iterdir():
            if entry.is_file() and _RE_STAGING_ID.match(entry.name):
                try:
                    mtime = entry.stat().st_mtime
                    if now - mtime > max_age_seconds:
                        entry.unlink()
                        cleaned_count += 1
                except Exception:
                    pass

        return cleaned_count
