"""Contracts and DTOs for SuperOffice codebase intelligence and script inspection."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CodebaseSearchCriteriaDTO(BaseModel):
    """Criteria for searching mirrored SuperOffice CRMScripts and screens."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(..., min_length=1, max_length=200, description="Keyword or regex to search")
    target_type: Literal["all", "crmscript", "screen", "action", "element"] = Field(
        default="all", description="Filter search by target artifact type"
    )
    screen_name: str | None = Field(
        default=None, max_length=100, description="Optional screen name scope"
    )
    limit: int = Field(default=20, ge=1, le=50, description="Maximum number of items to return")


class CodebaseSearchItemDTO(BaseModel):
    """Single matching entry from the codebase search."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    relative_path: str
    file_type: str
    screen_name: str | None = None
    line_number: int | None = None
    line_excerpt: str | None = None
    size_bytes: int = 0


class CodebaseSearchResultDTO(BaseModel):
    """Aggregated search result with truncation metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str
    target_type: str
    returned_count: int
    is_truncated: bool
    items: tuple[CodebaseSearchItemDTO, ...]


class CodebaseFileRequestDTO(BaseModel):
    """Request to safely view a file with bounded line windowing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    relative_path: str = Field(..., min_length=1, max_length=300)
    start_line: int = Field(default=1, ge=1, description="1-indexed starting line")
    end_line: int = Field(default=100, ge=1, description="1-indexed ending line")


class CodebaseFileContentDTO(BaseModel):
    """File content slice with line bounds and sha256 checksum."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    relative_path: str
    total_lines: int
    start_line: int
    end_line: int
    is_truncated: bool
    content: str
    sha256: str | None = None


class ScreenLifecycleScriptsDTO(BaseModel):
    """Paths to screen lifecycle scripts if present."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    load_script: str | None = None
    load_post_cgi: str | None = None
    load_final: str | None = None
    creation_script: str | None = None


class ScreenActionSummaryDTO(BaseModel):
    """Summary of a button action script bound to a screen."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    title: str | None = None
    script_path: str
    script_size_bytes: int = 0


class ScreenElementSummaryDTO(BaseModel):
    """Summary of a UI element on a screen with optional creation script."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    element_id: int | None = None
    name: str
    type_name: str | None = None
    creation_script_path: str | None = None
    creation_script_size_bytes: int = 0


class ScreenDetailsDTO(BaseModel):
    """Detailed structural definition of a SuperOffice screen."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    screen_id: int | None = None
    screen_name: str
    title: str | None = None
    relative_directory: str
    lifecycle_scripts: ScreenLifecycleScriptsDTO
    action_buttons: tuple[ScreenActionSummaryDTO, ...]
    element_count: int = 0
    elements: tuple[ScreenElementSummaryDTO, ...]
