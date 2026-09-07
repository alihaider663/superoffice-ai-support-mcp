"""SuperOffice warning-log bounded candidate-file locator (Gate 7A.4B1)."""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from diag_mcp.adapters.app_log_resolver import ApplicationLogLocationDTO
from diag_mcp.contracts.errors import LogSearchError
from diag_mcp.settings import DiagnosticsServerSettings


@dataclass(frozen=True, slots=True)
class WarningLogCandidateMetadata:
    """Internal metadata for a single located warning-log candidate file (Section 17).

    Contains internal file references and filesystem metadata only.
    Never exposed directly to AI-facing public tools without sanitization.
    """

    file_path: Path
    filename: str
    size_bytes: int
    last_modified_utc: datetime


@dataclass(frozen=True, slots=True)
class WarningLogCandidateBatch:
    """Bounded batch of located warning-log candidates with truncation semantics."""

    candidates: tuple[WarningLogCandidateMetadata, ...]
    total_matching_files: int
    returned_count: int
    is_truncated: bool
    parent_directory: Path
    filename_prefix: str


def _inspect_entry(
    entry: os.DirEntry[str],
    filename_prefix: str,
    resolved_parent: Path,
) -> tuple[float, str, Path, int, datetime] | None:
    """Inspect a directory entry and return candidate metadata tuple if valid, else None."""
    if not entry.name.startswith(filename_prefix):
        return None

    try:
        if entry.is_symlink() or Path(entry.path).is_symlink():
            return None
        if not entry.is_file(follow_symlinks=False):
            return None

        st = entry.stat(follow_symlinks=False)
        entry_path = Path(entry.path)
        if entry_path.resolve().parent != resolved_parent:
            return None

        mtime = st.st_mtime
        mtime_utc = datetime.fromtimestamp(mtime, tz=UTC)
        return (mtime, entry.name, entry_path, st.st_size, mtime_utc)
    except OSError:
        return None


class WarningLogCandidateLocator:
    """Locates candidate warning-log files matching a parent directory and filename prefix.

    Strictly enforces:
    - Direct children only (zero recursion into subdirectories) (Section 14)
    - Regular files physically represented inside the parent directory (Section 14, 21)
    - Symlink / junction / reparse point escape protection (Section 21)
    - Basename begins with exact prefix without assuming file extension (Section 9, 14)
    - Newest-first sorting by LastWriteTime (mtime descending) (Section 18)
    - Bounded candidate selection (canonical max: 3 files) (Section 19)
    - Empty valid directory returns empty batch (not an error) (Section 20)
    - Read-only, metadata-only inspection (zero file content reads/modifications) (Section 22)
    """

    def __init__(
        self,
        settings: DiagnosticsServerSettings | None = None,
        *,
        max_files: int | None = None,
    ) -> None:
        cfg = settings or DiagnosticsServerSettings()
        self._max_files = max_files if max_files is not None else cfg.application_max_files

    def locate_candidates(
        self,
        parent_directory: Path,
        filename_prefix: str,
        *,
        max_files: int | None = None,
    ) -> WarningLogCandidateBatch:
        """Scan direct children of parent_directory matching filename_prefix.

        Args:
            parent_directory: Validated absolute parent directory.
            filename_prefix: Validated leading filename prefix (e.g. 'warning').
            max_files: Optional override for candidate file limit.

        Returns:
            WarningLogCandidateBatch: Bounded tuple of candidate file metadata.

        Raises:
            LogSearchError: If directory is relative, missing, or inaccessible.
        """
        if not isinstance(parent_directory, Path):
            parent_directory = Path(parent_directory)

        if not parent_directory.is_absolute():
            raise LogSearchError(
                "Warning log parent directory configuration is invalid.",
                error_code="APPLICATION_LOG_PATH_INVALID",
            )

        if not parent_directory.exists() or not parent_directory.is_dir():
            raise LogSearchError(
                "Warning log parent directory does not exist or is inaccessible.",
                error_code="APPLICATION_LOG_PATH_INACCESSIBLE",
            )

        try:
            resolved_parent = parent_directory.resolve()
        except OSError:
            raise LogSearchError(
                "Warning log parent directory cannot be accessed.",
                error_code="APPLICATION_LOG_PATH_INACCESSIBLE",
            ) from None

        effective_max = max_files if max_files is not None else self._max_files
        raw_candidates: list[tuple[float, str, Path, int, datetime]] = []

        try:
            with os.scandir(parent_directory) as entries:
                for entry in entries:
                    cand = _inspect_entry(entry, filename_prefix, resolved_parent)
                    if cand is not None:
                        raw_candidates.append(cand)
        except (OSError, PermissionError):
            raise LogSearchError(
                "Warning log parent directory cannot be accessed.",
                error_code="APPLICATION_LOG_PATH_INACCESSIBLE",
            ) from None

        # Sort newest-first by LastWriteTime, filename ascending secondary (Section 18)
        raw_candidates.sort(key=lambda item: (-item[0], item[1]))

        total_matching = len(raw_candidates)
        bounded_items = raw_candidates[:effective_max]
        is_truncated = total_matching > effective_max

        candidate_metas = tuple(
            WarningLogCandidateMetadata(
                file_path=item[2],
                filename=item[1],
                size_bytes=item[3],
                last_modified_utc=item[4],
            )
            for item in bounded_items
        )

        return WarningLogCandidateBatch(
            candidates=candidate_metas,
            total_matching_files=total_matching,
            returned_count=len(candidate_metas),
            is_truncated=is_truncated,
            parent_directory=parent_directory,
            filename_prefix=filename_prefix,
        )

    def locate_from_location(
        self,
        location: ApplicationLogLocationDTO,
        *,
        max_files: int | None = None,
    ) -> WarningLogCandidateBatch:
        """Locate candidate warning-log files using a resolved ApplicationLogLocationDTO."""
        return self.locate_candidates(
            parent_directory=location.parent_directory,
            filename_prefix=location.filename_prefix,
            max_files=max_files,
        )
