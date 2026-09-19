"""Typed bounded resources and task-local inputs; no filesystem versions."""

from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from ..errors import WorkspaceContractError
from ..links import WorkspaceLink
from ..storage.manifest import (
    WorkspaceManifest,
    WorkspaceResourceRecord,
    WorkspaceResourceKind,
)
from .text import WorkspaceTextRangeRead


@dataclass(frozen=True)
class WorkspaceTextRead:
    link: str
    text: str
    truncated: bool
    size: int


@dataclass(frozen=True)
class WorkspaceByteRead:
    """A complete bounded byte resource for external protocol adapters."""

    link: str
    data: bytes
    kind: WorkspaceResourceKind
    media_type: str
    size: int


@dataclass(frozen=True)
class WorkspaceImageRead:
    """A complete image resource prepared for an LLM image part."""

    link: str
    data: bytes
    media_type: str
    size: int


@dataclass(frozen=True)
class WorkspaceDocumentRead:
    """A complete bounded document resource for local conversion."""

    link: str
    data: bytes
    media_type: str
    suffix: str
    size: int


@dataclass(frozen=True)
class WorkspaceBundleWrite:
    """One validated file write in a serialized Workspace bundle."""

    link: str
    data: bytes
    overwrite: bool = False

    def __post_init__(self) -> None:
        WorkspaceLink.parse(self.link)
        if not isinstance(self.data, bytes):
            raise WorkspaceContractError("Workspace bundle data must be bytes")
        if not isinstance(self.overwrite, bool):
            raise WorkspaceContractError("Workspace bundle overwrite must be boolean")


@dataclass(frozen=True)
class WorkspaceBundleResult:
    """Committed records and manifest for one Workspace bundle mutation."""

    manifest: WorkspaceManifest
    records: tuple[WorkspaceResourceRecord, ...]


@dataclass(frozen=True)
class WorkspaceTextSlice:
    """A bounded text slice for temporary workspace prompt input."""

    link: str
    range_label: str
    text: str
    truncated: bool
    size: int

    def __post_init__(self) -> None:
        if not self.link:
            raise WorkspaceContractError("WorkspaceTextSlice.link must be non-empty")
        if not self.range_label:
            raise WorkspaceContractError(
                "WorkspaceTextSlice.range_label must be non-empty"
            )
        if self.size < 0:
            raise WorkspaceContractError("WorkspaceTextSlice.size must be non-negative")


@dataclass(frozen=True)
class WorkspaceTextRangeResult:
    """A bounded page from the current contents of an explicit line range."""

    link: str
    size: int
    start_line: int
    end_line: int
    max_chars: int
    page: WorkspaceTextRangeRead


@dataclass(frozen=True)
class WorkspaceAnalysisReference:
    """One complete text reference for a Workspace analysis task."""

    source_id: str
    link: str
    text: str
    size: int
    end_line: int


@dataclass(frozen=True)
class WorkspaceAnalysisInput:
    """A complete bounded reference bundle for one analysis task."""

    references: tuple[WorkspaceAnalysisReference, ...]
    total_chars: int


class WorkspaceAnalysisBudgetReason(StrEnum):
    REFERENCE_COUNT = "reference_count_exceeded"
    REFERENCE_CHARS = "reference_chars_exceeded"
    SOURCE_CHARS = "source_chars_exceeded"


@dataclass(frozen=True)
class WorkspaceAnalysisBudgetFailure:
    reason: WorkspaceAnalysisBudgetReason
    limit: int
    observed: int
    offending_link: str = ""
    inspected: tuple[WorkspaceResourceRecord, ...] = ()


@dataclass(frozen=True)
class WorkspaceAnalysisPreparation:
    input: WorkspaceAnalysisInput | None = None
    failure: WorkspaceAnalysisBudgetFailure | None = None

    def __post_init__(self) -> None:
        if (self.input is None) == (self.failure is None):
            raise WorkspaceContractError(
                "Workspace analysis preparation requires exactly one outcome"
            )


@dataclass(frozen=True)
class WorkspacePromptInput:
    """Workspace text slices for a temporary task prompt."""

    slices: tuple[WorkspaceTextSlice, ...]

    def __post_init__(self) -> None:
        if not self.slices:
            raise WorkspaceContractError(
                "WorkspacePromptInput requires at least one text slice"
            )

    @property
    def truncated(self) -> bool:
        return any(text_slice.truncated for text_slice in self.slices)

    def render(self) -> str:
        return "\n\n".join(
            f"{text_slice.link} ({text_slice.range_label})\n{text_slice.text}"
            for text_slice in self.slices
        )
