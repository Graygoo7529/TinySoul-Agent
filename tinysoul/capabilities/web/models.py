"""Web capability domain objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tinysoul.infra import JsonObject
from tinysoul.workspace import WorkspaceManifest, WorkspaceResourceRecord

from .errors import WebContractError


class WebExtractor(StrEnum):
    DEFUDDLE = "defuddle"
    TRAFILATURA = "trafilatura"


@dataclass(frozen=True)
class WebSearchResult:
    """Bounded search interaction result with optional Workspace overflow."""

    payload: JsonObject
    manifest: WorkspaceManifest | None = None
    record: WorkspaceResourceRecord | None = None

    def __post_init__(self) -> None:
        if not self.payload:
            raise WebContractError("Web search payload must be non-empty")
        if bool(self.manifest) != bool(self.record):
            raise WebContractError(
                "Web search Workspace manifest and record must be set together"
            )


@dataclass(frozen=True)
class WebFetchResult:
    """Committed Workspace Markdown from one fetched public page."""

    markdown_link: str
    extractor: WebExtractor
    title: str
    excerpt: str
    content_chars: int
    remote_image_count: int
    manifest: WorkspaceManifest
    record: WorkspaceResourceRecord
    warning_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.markdown_link:
            raise WebContractError("Web fetch Markdown link must be non-empty")
        if not isinstance(self.extractor, WebExtractor):
            raise WebContractError("Web fetch extractor is invalid")
        if self.content_chars <= 0 or self.remote_image_count < 0:
            raise WebContractError("Web fetch result counts are invalid")
