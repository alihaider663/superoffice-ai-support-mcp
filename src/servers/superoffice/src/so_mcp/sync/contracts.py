"""Domain contracts and Data Transfer Objects for Codebase Synchronization."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HierarchyNodeDTO(BaseModel):
    """Represents a node in the SuperOffice script folder hierarchy."""

    model_config = ConfigDict(frozen=True)

    id: int
    parent_id: int | None = None
    name: str
    full_path: str = ""


class ScriptRecordDTO(BaseModel):
    """Represents an extracted SuperOffice CRMScript entity."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    description: str = ""
    body: str = ""
    updated: str = ""
    hierarchy_id: int | None = None
    hierarchy_path: str = ""
    include_id: str | None = None


class ScreenRecordDTO(BaseModel):
    """Represents an extracted screen definition including scripts, actions, and elements."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    table_name: str = "screen_definition"
    description: str = ""
    id_string: str = ""
    screen_key: str = ""
    load_script_body: str = ""
    load_post_cgi_script_body: str = ""
    load_final_script_body: str = ""
    creation_script: str = ""
    actions: list[dict[str, Any]] = Field(default_factory=list)
    elements: list[dict[str, Any]] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


class ExtraTableSchemaDTO(BaseModel):
    """Represents a custom extra table (y_*) schema definition and fields."""

    model_config = ConfigDict(frozen=True)

    id: int
    table_name: str
    fields: list[dict[str, Any]] = Field(default_factory=list)


class SyncManifestEntryDTO(BaseModel):
    """Manifest record for a synced file."""

    model_config = ConfigDict(frozen=True)

    entity_type: str  # "script", "screen", "schema", "config"
    entity_id: int
    name: str
    relative_path: str
    sha256: str
    size_bytes: int
    updated: str | None = None
    warnings: list[str] = Field(default_factory=list)


class SyncManifestDTO(BaseModel):
    """Complete summary manifest of a codebase synchronization run."""

    model_config = ConfigDict(frozen=True)

    generated_at: str
    source_mode: str  # "http" or "mssql"
    target_dir: str
    total_scripts: int = 0
    total_screens: int = 0
    total_extra_tables: int = 0
    entries: list[SyncManifestEntryDTO] = Field(default_factory=list)


class SyncResultDTO(BaseModel):
    """Result returned by the codebase synchronization service."""

    model_config = ConfigDict(frozen=True)

    success: bool
    manifest: SyncManifestDTO
    error_message: str | None = None
