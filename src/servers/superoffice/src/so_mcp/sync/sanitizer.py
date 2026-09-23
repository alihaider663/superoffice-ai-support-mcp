"""Security sanitizer for file names, hierarchy path segments, and target directories."""

import re
from pathlib import Path

# Characters prohibited in filenames on Windows and POSIX systems
_ILLEGAL_CHARACTERS_RE = re.compile(r'[\x00-\x1f\\/:*?"<>|]')
# Windows reserved filenames (case-insensitive)
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
)


class PathTraversalSecurityError(Exception):
    """Raised when a resolved path escapes the configured root directory."""


def sanitize_filename(name: str, fallback: str = "unnamed") -> str:
    """Sanitize an untrusted name for safe usage as a single file name.

    Replaces illegal filesystem characters, trims whitespace/dots, and prevents
    Windows reserved device names.
    """
    if not name:
        return fallback

    # Replace illegal characters with underscore
    cleaned = _ILLEGAL_CHARACTERS_RE.sub("_", name.strip())

    # Strip leading/trailing dots and spaces (Windows does not support trailing dots/spaces)
    cleaned = cleaned.strip(". ")

    if not cleaned:
        return fallback

    # Check for Windows reserved names
    stem = cleaned.split(".")[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"

    return cleaned


def sanitize_path_segment(segment: str, fallback: str = "general") -> str:
    """Sanitize a directory segment name."""
    return sanitize_filename(segment, fallback=fallback)


def build_safe_target_path(
    base_dir: Path,
    relative_segments: list[str],
    filename: str,
) -> Path:
    """Deterministically assemble and validate a filesystem path.

    Enforces that the resolved target path is strictly contained within base_dir.
    Raises PathTraversalSecurityError if directory traversal is detected.
    """
    resolved_base = base_dir.resolve()

    clean_segments = [
        sanitize_path_segment(s) for s in relative_segments if s and s not in (".", "..")
    ]
    clean_filename = sanitize_filename(filename)

    target_path = resolved_base.joinpath(*clean_segments, clean_filename)
    resolved_target = target_path.resolve()

    # Invariant: Must strictly reside within base_dir
    try:
        resolved_target.relative_to(resolved_base)
    except ValueError:
        msg = (
            f"Path traversal detected: Target '{resolved_target}' "
            f"escapes base directory '{resolved_base}'"
        )
        raise PathTraversalSecurityError(msg) from None

    return target_path
