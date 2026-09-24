"""Unit tests for CodebaseIntelligenceService sanitization and error boundaries."""

import pytest

from platform_security.sanitization import RecursiveOutputSanitizer
from so_mcp.codebase.contracts import (
    CodebaseFileRequestDTO,
    CodebaseSearchCriteriaDTO,
    ScreenActionSummaryDTO,
    ScreenDetailsDTO,
    ScreenElementSummaryDTO,
    ScreenLifecycleScriptsDTO,
)
from so_mcp.codebase.repository import FakeCodebaseRepository
from so_mcp.codebase.service import CodebaseIntelligenceService


@pytest.fixture
def fake_service() -> CodebaseIntelligenceService:
    """Create CodebaseIntelligenceService backed by FakeCodebaseRepository."""
    files = {
        "crmscripts/auth.crmscript": (
            '# Integration script\nString apiKey = "sk_live_1234567890abcdef123456";\n'
            'String customerPhone = "+47 12 34 56 78";\n'
        ),
        "screens/Edit/actions/save.crmscript": (
            '# Save action\nString email = "support@superoffice.com";\n'
        ),
    }
    screens = {
        "Edit": ScreenDetailsDTO(
            screen_id=25,
            screen_name="Edit",
            title="Edit Customer Details (+47 12 34 56 78)",
            relative_directory="screens/Edit",
            lifecycle_scripts=ScreenLifecycleScriptsDTO(),
            action_buttons=(
                ScreenActionSummaryDTO(
                    name="save",
                    title="Save Changes",
                    script_path="screens/Edit/actions/save.crmscript",
                    script_size_bytes=100,
                ),
            ),
            element_count=1,
            elements=(
                ScreenElementSummaryDTO(
                    element_id=5,
                    name="phone",
                    type_name="string",
                    creation_script_path=None,
                    creation_script_size_bytes=0,
                ),
            ),
        )
    }
    repo = FakeCodebaseRepository(files=files, screens=screens)
    sanitizer = RecursiveOutputSanitizer()
    return CodebaseIntelligenceService(repository=repo, sanitizer=sanitizer)


@pytest.mark.asyncio
async def test_search_scrubs_pii_in_excerpts(fake_service: CodebaseIntelligenceService) -> None:
    """search_codebase scrubs phone numbers and API keys from excerpts."""
    res = await fake_service.search_codebase(CodebaseSearchCriteriaDTO(query="customerPhone"))
    assert res.returned_count == 1
    excerpt = res.items[0].line_excerpt
    assert "+47 12 34 56 78" not in excerpt
    assert "[REDACTED_PHONE]" in excerpt or "[REDACTED" in excerpt


@pytest.mark.asyncio
async def test_get_file_scrubs_pii_and_secrets(fake_service: CodebaseIntelligenceService) -> None:
    """get_codebase_file scrubs api keys, tokens, and phone numbers from content."""
    res = await fake_service.get_codebase_file(
        CodebaseFileRequestDTO(relative_path="crmscripts/auth.crmscript")
    )
    assert "sk_live_1234567890abcdef123456" not in res.content
    assert "+47 12 34 56 78" not in res.content
    assert "[REDACTED_API_KEY]" in res.content
    assert "[REDACTED_PHONE]" in res.content or "[REDACTED" in res.content


@pytest.mark.asyncio
async def test_get_screen_details_scrubs_pii(fake_service: CodebaseIntelligenceService) -> None:
    """get_screen_details scrubs sensitive information from title."""
    res = await fake_service.get_screen_details("Edit")
    assert res is not None
    assert "+47 12 34 56 78" not in res.title
    assert "[REDACTED_PHONE]" in res.title or "[REDACTED" in res.title


@pytest.mark.asyncio
async def test_get_screen_details_nonexistent_returns_none(
    fake_service: CodebaseIntelligenceService,
) -> None:
    """Non-existent screen name returns None cleanly."""
    res = await fake_service.get_screen_details("NonExistentScreen")
    assert res is None
