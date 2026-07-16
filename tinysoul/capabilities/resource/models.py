"""Resource conversion domain objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tinysoul.workspace import WorkspaceManifest, WorkspaceResourceRecord

from .errors import ResourceContractError


class ResourceConverter(StrEnum):
    MARKITDOWN = "markitdown"
    PYPDF = "pypdf"


class ResourceContentStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    VISUAL_ONLY = "visual_only"


@dataclass(frozen=True)
class ResourceConversionResult:
    """Committed Workspace result for one document conversion."""

    source_link: str
    markdown_link: str
    converter: ResourceConverter
    content_status: ResourceContentStatus
    manifest: WorkspaceManifest
    records: tuple[WorkspaceResourceRecord, ...]
    visual_reference_links: tuple[str, ...] = ()
    warning_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_link or not self.markdown_link:
            raise ResourceContractError("Resource conversion links must be non-empty")
        if not isinstance(self.converter, ResourceConverter):
            raise ResourceContractError("Resource converter is invalid")
        if not isinstance(self.content_status, ResourceContentStatus):
            raise ResourceContractError("Resource content status is invalid")
        if not self.records:
            raise ResourceContractError("Resource conversion must commit records")

