"""Factory for creating SuperOffice metadata services and repositories."""

import logging

from sqlalchemy.ext.asyncio import AsyncEngine

from so_mcp.metadata.repository import (
    FakeMetadataRepository,
    MetadataRepositoryProtocol,
    MssqlMetadataRepository,
)
from so_mcp.metadata.service import SuperOfficeMetadataService
from so_mcp.settings import SuperOfficeCodebaseSyncSettings
from so_mcp.sync.mssql_extractor import create_mssql_sync_engine

logger = logging.getLogger(__name__)


def create_metadata_service(
    settings: SuperOfficeCodebaseSyncSettings | None = None,
    engine: AsyncEngine | None = None,
    repository: MetadataRepositoryProtocol | None = None,
) -> SuperOfficeMetadataService:
    """Create SuperOfficeMetadataService with MSSQL repository or provided test repository."""
    if repository is not None:
        return SuperOfficeMetadataService(repository=repository)

    if engine is not None:
        return SuperOfficeMetadataService(repository=MssqlMetadataRepository(engine))

    cfg = settings or SuperOfficeCodebaseSyncSettings()

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
        repo: MetadataRepositoryProtocol = MssqlMetadataRepository(mssql_engine)
        return SuperOfficeMetadataService(repository=repo)
    except Exception as exc:
        logger.warning(
            "Could not initialize MSSQL metadata engine (%s). Using fallback repository.", exc
        )
        return SuperOfficeMetadataService(repository=FakeMetadataRepository())
