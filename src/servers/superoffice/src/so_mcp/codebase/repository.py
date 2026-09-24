"""Local filesystem repository for SuperOffice mirrored scripts, screens, and definitions."""

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Protocol

from so_mcp.codebase.contracts import (
    CodebaseFileContentDTO,
    CodebaseFileRequestDTO,
    CodebaseSearchCriteriaDTO,
    CodebaseSearchItemDTO,
    CodebaseSearchResultDTO,
    ScreenActionSummaryDTO,
    ScreenDetailsDTO,
    ScreenElementSummaryDTO,
    ScreenLifecycleScriptsDTO,
)
from so_mcp.sync.sanitizer import PathTraversalSecurityError

logger = logging.getLogger(__name__)


class CodebaseRepositoryProtocol(Protocol):
    """Protocol for accessing mirrored SuperOffice codebase artifacts."""

    async def search_codebase(self, criteria: CodebaseSearchCriteriaDTO) -> CodebaseSearchResultDTO:
        """Search mirrored scripts and screen definitions."""
        ...

    async def get_codebase_file(self, request: CodebaseFileRequestDTO) -> CodebaseFileContentDTO:
        """Read a file with line-range windowing and path traversal protection."""
        ...

    async def get_screen_details(self, screen_name_or_id: str) -> ScreenDetailsDTO | None:
        """Inspect structural details, elements, and button actions of a screen."""
        ...


def _matches_target_type(target_type: str, rel_path: str) -> bool:
    """Determine if a mirrored file matches the requested target filter."""
    if target_type == "crmscript":
        return rel_path.startswith("crmscripts/")
    if target_type == "screen":
        return (
            rel_path.startswith("screens/")
            and "/actions/" not in rel_path
            and "/elements/" not in rel_path
        )
    if target_type == "action":
        return "/actions/" in rel_path
    if target_type == "element":
        return "/elements/" in rel_path
    return True


def _scan_file_excerpt(
    full_path: Path, query: str, regex: re.Pattern[str] | None
) -> tuple[int | None, str | None]:
    """Scan file lines for matching query, returning 1-indexed line and truncated excerpt."""
    try:
        with full_path.open("r", encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(f, start=1):
                if (regex and regex.search(line)) or (query.lower() in line.lower()):
                    return idx, line.strip()[:150]
    except Exception:
        pass
    return None, None


def _resolve_screen_dir(screens_root: Path, clean_input: str) -> tuple[Path | None, str]:
    """Locate a screen directory by name (case-insensitive) or screen ID."""
    direct_dir = screens_root / clean_input
    if direct_dir.is_dir():
        return direct_dir, clean_input

    for child in screens_root.iterdir():
        if child.is_dir() and child.name.lower() == clean_input.lower():
            return child, child.name

    if clean_input.isdigit():
        def_file = screens_root / "screen_definition.json"
        if def_file.is_file():
            try:
                defs = json.loads(def_file.read_text(encoding="utf-8"))
                for d in defs:
                    if str(d.get("id")) == clean_input:
                        candidate = screens_root / str(d.get("name"))
                        if candidate.is_dir():
                            return candidate, candidate.name
            except Exception:
                pass
    return None, clean_input


def _read_screen_actions(
    target_dir: Path, codebase_root: Path
) -> tuple[ScreenActionSummaryDTO, ...]:
    """Collect button action scripts for a screen."""
    actions_dir = target_dir / "actions"
    if not actions_dir.is_dir():
        return ()
    actions: list[ScreenActionSummaryDTO] = []
    for f in sorted(actions_dir.glob("*.crmscript")):
        rel_f = str(f.relative_to(codebase_root)).replace("\\", "/")
        actions.append(
            ScreenActionSummaryDTO(
                name=f.stem,
                title=f"{f.stem.capitalize()} Action",
                script_path=rel_f,
                script_size_bytes=f.stat().st_size,
            )
        )
    return tuple(actions)


def _read_screen_elements(
    target_dir: Path, codebase_root: Path
) -> tuple[ScreenElementSummaryDTO, ...]:
    """Collect element creation scripts for a screen."""
    elements_dir = target_dir / "elements"
    if not elements_dir.is_dir():
        return ()
    elements: list[ScreenElementSummaryDTO] = []
    for f in sorted(elements_dir.glob("*.crmscript")):
        rel_f = str(f.relative_to(codebase_root)).replace("\\", "/")
        elements.append(
            ScreenElementSummaryDTO(
                element_id=None,
                name=f.stem,
                type_name="element_script",
                creation_script_path=rel_f,
                creation_script_size_bytes=f.stat().st_size,
            )
        )
    return tuple(elements)


class LocalCodebaseRepository:
    """Production implementation reading from the local mirrored codebase directory."""

    def __init__(self, codebase_root: Path) -> None:
        self._codebase_root = codebase_root.resolve()
        self._manifest_cache: list[dict[str, Any]] | None = None

    @property
    def codebase_root(self) -> Path:
        return self._codebase_root

    def _resolve_safe_path(self, relative_path: str) -> Path:
        """Deterministically resolve relative path and verify it stays within codebase root."""
        if "\x00" in relative_path:
            raise PathTraversalSecurityError("Null bytes prohibited in path")

        # Normalize separators
        clean_rel = relative_path.replace("\\", "/").strip().lstrip("/")
        if not clean_rel:
            raise PathTraversalSecurityError("Empty relative path")

        parts = [p for p in clean_rel.split("/") if p and p != "."]
        if any(p == ".." for p in parts):
            raise PathTraversalSecurityError(f"Path traversal '..' detected in '{relative_path}'")

        target = self._codebase_root.joinpath(*parts).resolve()
        try:
            target.relative_to(self._codebase_root)
        except ValueError:
            raise PathTraversalSecurityError(
                f"Path '{relative_path}' escapes codebase root '{self._codebase_root}'"
            ) from None

        return target

    def _load_manifest_entries(self) -> list[dict[str, Any]]:
        """Load and cache entries from manifest.json if present."""
        if self._manifest_cache is not None:
            return self._manifest_cache

        manifest_path = self._codebase_root / "manifest.json"
        if manifest_path.is_file():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                entries = data.get("entries", [])
                if isinstance(entries, list):
                    self._manifest_cache = entries
                    return entries
            except Exception as exc:
                logger.warning("Failed to parse manifest.json at %s: %s", manifest_path, exc)

        # Fallback: scan filesystem directory
        discovered: list[dict[str, Any]] = []
        for p in self._codebase_root.rglob("*"):
            if p.is_file() and p.name != "manifest.json":
                try:
                    rel = str(p.relative_to(self._codebase_root)).replace("\\", "/")
                    f_type = "unknown"
                    if rel.startswith("crmscripts/"):
                        f_type = "crmscript"
                    elif "/actions/" in rel:
                        f_type = "screen_action"
                    elif "/elements/" in rel:
                        f_type = "screen_element"
                    elif rel.startswith("screens/"):
                        f_type = "screen"
                    elif rel.startswith("schema/"):
                        f_type = "schema"
                    discovered.append(
                        {
                            "relative_path": rel,
                            "file_type": f_type,
                            "size_bytes": p.stat().st_size,
                        }
                    )
                except Exception:
                    continue

        self._manifest_cache = discovered
        return discovered

    async def search_codebase(self, criteria: CodebaseSearchCriteriaDTO) -> CodebaseSearchResultDTO:
        """Search across mirrored scripts and screens."""
        query = criteria.query.strip()
        target_type = criteria.target_type
        screen_scope = criteria.screen_name.strip().lower() if criteria.screen_name else None
        limit = criteria.limit

        regex = None
        try:
            regex = re.compile(re.escape(query), re.IGNORECASE)
        except Exception:
            regex = None

        entries = self._load_manifest_entries()
        items: list[CodebaseSearchItemDTO] = []

        for entry in entries:
            rel_path = str(entry.get("relative_path", "")).replace("\\", "/")
            f_type = str(entry.get("file_type", "file"))
            size_b = int(entry.get("size_bytes", 0))

            if not _matches_target_type(target_type, rel_path):
                continue

            screen_name = None
            if rel_path.startswith("screens/"):
                parts = rel_path.split("/")
                if len(parts) > 1:
                    screen_name = parts[1]
                    if screen_scope and screen_name.lower() != screen_scope:
                        continue

            path_matched = query.lower() in rel_path.lower()
            matching_line: int | None = None
            line_excerpt: str | None = None

            if rel_path.endswith((".crmscript", ".json", ".txt")):
                full_path = self._codebase_root / rel_path
                if full_path.is_file():
                    matching_line, line_excerpt = _scan_file_excerpt(full_path, query, regex)

            if path_matched or matching_line is not None:
                items.append(
                    CodebaseSearchItemDTO(
                        relative_path=rel_path,
                        file_type=f_type,
                        screen_name=screen_name,
                        line_number=matching_line,
                        line_excerpt=line_excerpt,
                        size_bytes=size_b,
                    )
                )

            if len(items) >= limit:
                break

        is_truncated = len(items) == limit
        return CodebaseSearchResultDTO(
            query=query,
            target_type=target_type,
            returned_count=len(items),
            is_truncated=is_truncated,
            items=tuple(items),
        )

    async def get_codebase_file(self, request: CodebaseFileRequestDTO) -> CodebaseFileContentDTO:
        """Read a mirrored script or definition file with bounded line windowing."""
        safe_path = self._resolve_safe_path(request.relative_path)
        if not safe_path.is_file():
            raise FileNotFoundError(f"File '{request.relative_path}' not found in codebase mirror.")

        start_line = max(1, request.start_line)
        end_line = max(start_line, request.end_line)

        # Enforce max 200 line window to prevent context blowup
        is_truncated = False
        if (end_line - start_line) >= 200:
            end_line = start_line + 199
            is_truncated = True

        try:
            raw_bytes = safe_path.read_bytes()
            sha256_hash = hashlib.sha256(raw_bytes).hexdigest()
            text_content = raw_bytes.decode("utf-8", errors="replace")
            all_lines = text_content.splitlines()
        except OSError as exc:
            raise OSError(f"Failed to read file '{request.relative_path}': {exc}") from exc

        total_lines = len(all_lines)
        if start_line > total_lines:
            sliced_lines: list[str] = []
        else:
            actual_end = min(end_line, total_lines)
            sliced_lines = all_lines[start_line - 1 : actual_end]

        content_slice = "\n".join(sliced_lines)
        clean_rel = str(safe_path.relative_to(self._codebase_root)).replace("\\", "/")

        return CodebaseFileContentDTO(
            relative_path=clean_rel,
            total_lines=total_lines,
            start_line=start_line,
            end_line=min(end_line, total_lines) if total_lines > 0 else 0,
            is_truncated=is_truncated or (end_line < total_lines),
            content=content_slice,
            sha256=sha256_hash,
        )

    async def get_screen_details(self, screen_name_or_id: str) -> ScreenDetailsDTO | None:
        """Inspect structural details, elements, and button actions of a screen."""
        clean_input = screen_name_or_id.strip()
        screens_root = self._codebase_root / "screens"
        if not screens_root.is_dir():
            return None

        target_dir, target_name = _resolve_screen_dir(screens_root, clean_input)
        if target_dir is None:
            return None

        screen_id: int | None = None
        title: str | None = None
        screen_json_path = target_dir / "screen.json"
        if screen_json_path.is_file():
            try:
                metadata = json.loads(screen_json_path.read_text(encoding="utf-8"))
                screen_id = metadata.get("id")
                title = metadata.get("title") or metadata.get("name")
            except Exception:
                pass

        def _get_rel(script_name: str) -> str | None:
            p = target_dir / script_name
            if p.is_file():
                return str(p.relative_to(self._codebase_root)).replace("\\", "/")
            return None

        lifecycle = ScreenLifecycleScriptsDTO(
            load_script=_get_rel("load_script.crmscript"),
            load_post_cgi=_get_rel("load_post_cgi.crmscript"),
            load_final=_get_rel("load_final.crmscript"),
            creation_script=_get_rel("creation_script.crmscript"),
        )
        actions_list = _read_screen_actions(target_dir, self._codebase_root)
        elements_list = _read_screen_elements(target_dir, self._codebase_root)
        rel_dir = str(target_dir.relative_to(self._codebase_root)).replace("\\", "/")

        return ScreenDetailsDTO(
            screen_id=screen_id,
            screen_name=target_name,
            title=title or target_name,
            relative_directory=rel_dir,
            lifecycle_scripts=lifecycle,
            action_buttons=actions_list,
            element_count=len(elements_list),
            elements=elements_list,
        )


class FakeCodebaseRepository:
    """In-memory repository for unit testing codebase search and file reading."""

    def __init__(
        self,
        files: dict[str, str] | None = None,
        screens: dict[str, ScreenDetailsDTO] | None = None,
    ) -> None:
        self.files = files or {}
        self.screens = screens or {}

    async def search_codebase(self, criteria: CodebaseSearchCriteriaDTO) -> CodebaseSearchResultDTO:
        items = []
        query = criteria.query.lower()
        for path, content in self.files.items():
            if query in path.lower() or query in content.lower():
                matching_line = None
                line_excerpt = ""
                for idx, line in enumerate(content.splitlines(), start=1):
                    if query in line.lower():
                        matching_line = idx
                        line_excerpt = line
                        break
                if not line_excerpt and content.splitlines():
                    line_excerpt = content.splitlines()[0]
                items.append(
                    CodebaseSearchItemDTO(
                        relative_path=path,
                        file_type="crmscript" if path.endswith(".crmscript") else "file",
                        screen_name=None,
                        line_number=matching_line,
                        line_excerpt=line_excerpt,
                        size_bytes=len(content.encode("utf-8")),
                    )
                )
            if len(items) >= criteria.limit:
                break
        return CodebaseSearchResultDTO(
            query=criteria.query,
            target_type=criteria.target_type,
            returned_count=len(items),
            is_truncated=len(items) == criteria.limit,
            items=tuple(items),
        )

    async def get_codebase_file(self, request: CodebaseFileRequestDTO) -> CodebaseFileContentDTO:
        if request.relative_path not in self.files:
            raise FileNotFoundError(f"File '{request.relative_path}' not found")
        content = self.files[request.relative_path]
        lines = content.splitlines()
        total = len(lines)
        start = max(1, request.start_line)
        end = min(request.end_line, total) if total > 0 else 0
        slice_content = "\n".join(lines[start - 1 : end]) if total > 0 else ""
        return CodebaseFileContentDTO(
            relative_path=request.relative_path,
            total_lines=total,
            start_line=start,
            end_line=end,
            is_truncated=end < total,
            content=slice_content,
            sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )

    async def get_screen_details(self, screen_name_or_id: str) -> ScreenDetailsDTO | None:
        for name, details in self.screens.items():
            matches_name = name.lower() == screen_name_or_id.lower()
            matches_id = str(details.screen_id) == screen_name_or_id
            if matches_name or matches_id:
                return details
        return None
