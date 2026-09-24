"""Factory for creating SuperOffice extra table services and repositories."""

import logging

from sqlalchemy.ext.asyncio import AsyncEngine

from so_mcp.contracts.errors import SuperOfficeIntegrationError
from so_mcp.extra_tables.repository import (
    ExtraTableRepositoryProtocol,
    LocalMirrorExtraTableRepository,
    MssqlExtraTableRepository,
)
from so_mcp.extra_tables.service import ExtraTableService
from so_mcp.settings import SuperOfficeCodebaseSyncSettings
from so_mcp.sync.mssql_extractor import create_mssql_sync_engine

logger = logging.getLogger(__name__)


def create_extra_table_service(
    settings: SuperOfficeCodebaseSyncSettings | None = None,
    engine: AsyncEngine | None = None,
    repository: ExtraTableRepositoryProtocol | None = None,
) -> ExtraTableService:
    """Create ExtraTableService with MSSQL repository or local mirror fallback."""
    if repository is not None:
        return ExtraTableService(repository=repository)

    if engine is not None:
        return ExtraTableService(repository=MssqlExtraTableRepository(engine))

    cfg = settings or SuperOfficeCodebaseSyncSettings()
    mirror_path = cfg.codebase_local_path
    schema_file = mirror_path / "schema" / "extra_tables.json"

    local_mirror_repo = (
        LocalMirrorExtraTableRepository(mirror_path) if schema_file.exists() else None
    )

    try:
        mssql_engine = create_mssql_sync_engine(
            host=cfg.mssql_host,
            port=cfg.mssql_port,
            database=cfg.mssql_database,
            user=cfg.mssql_user,
            password=cfg.mssql_password.get_secret_value(),
            trust_cert=cfg.mssql_trust_server_certificate,
            isolation_level="READ COMMITTED",
        )
        repo: ExtraTableRepositoryProtocol = MssqlExtraTableRepository(
            mssql_engine, fallback_repo=local_mirror_repo
        )
    except Exception as exc:
        logger.warning(
            "Could not initialize MSSQL extra table engine (%s). Checking local mirror.", exc
        )
        if local_mirror_repo is not None:
            repo = local_mirror_repo
        else:
            raise SuperOfficeIntegrationError(
                f"Extra table service could not be initialized: {exc}",
                error_code="SUPEROFFICE_SERVICE_UNCONFIGURED",
            ) from exc

    return ExtraTableService(repository=repo)
