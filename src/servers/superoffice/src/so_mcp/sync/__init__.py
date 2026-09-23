"""SuperOffice Codebase Synchronization and Mirroring Engine.

Transfers custom scripts (ejscript), screen definitions, and extra tables
from SuperOffice into a local, user-configured directory.
"""

from so_mcp.sync.contracts import (
    HierarchyNodeDTO,
    ScriptRecordDTO,
    SyncManifestDTO,
    SyncManifestEntryDTO,
    SyncResultDTO,
)
from so_mcp.sync.service import SuperOfficeCodebaseSyncService

__all__ = [
    "HierarchyNodeDTO",
    "ScriptRecordDTO",
    "SuperOfficeCodebaseSyncService",
    "SyncManifestDTO",
    "SyncManifestEntryDTO",
    "SyncResultDTO",
]
