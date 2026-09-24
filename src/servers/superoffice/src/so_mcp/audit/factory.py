"""Factory for creating SuperOffice ticket audit services and repositories."""

import logging

from sqlalchemy.ext.asyncio import AsyncEngine

from so_mcp.audit.repository import (
    FakeTicketAuditRepository,
    MssqlTicketAuditRepository,
    TicketAuditRepositoryProtocol,
)
from so_mcp.audit.service import TicketAuditService
from so_mcp.settings import SuperOfficeCodebaseSyncSettings
from so_mcp.sync.mssql_extractor import create_mssql_sync_engine

logger = logging.getLogger(__name__)


def create_ticket_audit_service(
    settings: SuperOfficeCodebaseSyncSettings | None = None,
    engine: AsyncEngine | None = None,
    repository: TicketAuditRepositoryProtocol | None = None,
) -> TicketAuditService:
    """Create TicketAuditService with MSSQL repository or provided test repository."""
    if repository is not None:
        return TicketAuditService(repository=repository)

    if engine is not None:
        return TicketAuditService(repository=MssqlTicketAuditRepository(engine))

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
        repo: TicketAuditRepositoryProtocol = MssqlTicketAuditRepository(mssql_engine)
        return TicketAuditService(repository=repo)
    except Exception as exc:
        logger.warning(
            "Could not initialize MSSQL ticket audit engine (%s). Using fallback repository.", exc
        )
        return TicketAuditService(repository=FakeTicketAuditRepository())
