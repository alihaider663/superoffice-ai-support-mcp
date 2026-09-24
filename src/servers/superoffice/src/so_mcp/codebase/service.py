"""Application service for SuperOffice codebase intelligence and script inspection."""

import logging

from platform_security.interfaces import OutputSanitizer
from platform_security.sanitization import RecursiveOutputSanitizer
from so_mcp.codebase.contracts import (
    CodebaseFileContentDTO,
    CodebaseFileRequestDTO,
    CodebaseSearchCriteriaDTO,
    CodebaseSearchItemDTO,
    CodebaseSearchResultDTO,
    ScreenDetailsDTO,
)
from so_mcp.codebase.repository import CodebaseRepositoryProtocol

logger = logging.getLogger(__name__)


class CodebaseIntelligenceService:
    """Service providing safe codebase search and script inspection with PII redaction."""

    def __init__(
        self,
        repository: CodebaseRepositoryProtocol,
        sanitizer: OutputSanitizer | None = None,
    ) -> None:
        self._repository = repository
        self._sanitizer = sanitizer or RecursiveOutputSanitizer()

    def _sanitize_string(self, text: str | None) -> str:
        if not text:
            return ""
        sanitized = self._sanitizer.sanitize(text)
        return str(sanitized) if sanitized is not None else ""

    async def search_codebase(self, criteria: CodebaseSearchCriteriaDTO) -> CodebaseSearchResultDTO:
        """Search mirrored scripts and screens with sanitized excerpts."""
        raw_result = await self._repository.search_codebase(criteria)
        sanitized_items: list[CodebaseSearchItemDTO] = []
        for item in raw_result.items:
            sanitized_excerpt = (
                self._sanitize_string(item.line_excerpt) if item.line_excerpt else None
            )
            sanitized_items.append(
                CodebaseSearchItemDTO(
                    relative_path=item.relative_path,
                    file_type=item.file_type,
                    screen_name=item.screen_name,
                    line_number=item.line_number,
                    line_excerpt=sanitized_excerpt,
                    size_bytes=item.size_bytes,
                )
            )

        return CodebaseSearchResultDTO(
            query=raw_result.query,
            target_type=raw_result.target_type,
            returned_count=len(sanitized_items),
            is_truncated=raw_result.is_truncated,
            items=tuple(sanitized_items),
        )

    async def get_codebase_file(self, request: CodebaseFileRequestDTO) -> CodebaseFileContentDTO:
        """Read a script or definition file with PII/secret redaction applied."""
        raw_file = await self._repository.get_codebase_file(request)
        sanitized_content = self._sanitize_string(raw_file.content)
        return CodebaseFileContentDTO(
            relative_path=raw_file.relative_path,
            total_lines=raw_file.total_lines,
            start_line=raw_file.start_line,
            end_line=raw_file.end_line,
            is_truncated=raw_file.is_truncated,
            content=sanitized_content,
            sha256=raw_file.sha256,
        )

    async def get_screen_details(self, screen_name_or_id: str) -> ScreenDetailsDTO | None:
        """Retrieve screen layout, buttons, and elements."""
        details = await self._repository.get_screen_details(screen_name_or_id)
        if details is None:
            return None

        # Sanitize title if needed
        clean_title = self._sanitize_string(details.title) if details.title else None
        return ScreenDetailsDTO(
            screen_id=details.screen_id,
            screen_name=details.screen_name,
            title=clean_title,
            relative_directory=details.relative_directory,
            lifecycle_scripts=details.lifecycle_scripts,
            action_buttons=details.action_buttons,
            element_count=details.element_count,
            elements=details.elements,
        )
