"""Factory for instantiating CodebaseIntelligenceService from server settings."""

from pathlib import Path

from so_mcp.codebase.repository import FakeCodebaseRepository, LocalCodebaseRepository
from so_mcp.codebase.service import CodebaseIntelligenceService
from so_mcp.settings import SuperOfficeServerSettings


def create_codebase_intelligence_service(
    settings: SuperOfficeServerSettings | None = None,
) -> CodebaseIntelligenceService:
    """Create a CodebaseIntelligenceService backed by the configured local mirror directory."""
    effective_settings = settings or SuperOfficeServerSettings()
    mirror_path = effective_settings.codebase_local_path

    if mirror_path:
        local_dir = Path(mirror_path).resolve()
        if local_dir.is_dir():
            repo = LocalCodebaseRepository(local_dir)
            return CodebaseIntelligenceService(repo)

    # If mirror_path does not exist or is unconfigured, return a safe fallback repository
    return CodebaseIntelligenceService(FakeCodebaseRepository())
