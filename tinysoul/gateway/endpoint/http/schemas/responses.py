"""Stable response envelopes used by the HTTP/OpenAPI boundary.

The endpoint services still own the complete JSON projections.  These models
document the fields consumed by the remote visualization while allowing owner
specific additions to remain visible during the normal response transition.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContractResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class HealthResponse(ContractResponse):
    ok: bool


class CommandReceiptResponse(ContractResponse):
    accepted: bool | None = None
    command_id: str | None = None
    turn_id: str | None = None
    request_id: str | None = None
    state: str | None = None


class RuntimeStatusResponse(ContractResponse):
    protocol_version: int
    instance_id: str
    project_identity: str
    ready: bool
    active_day: str
    turn_active: bool
    runtime: dict[str, Any]
    latest_event_sequence: int
    event_journal: dict[str, Any]


class ResourceLocatorResponse(ContractResponse):
    link: str | None = None
    ref: str | None = None
    day: str | None = None
    turn_id: str | None = None
    view: str | None = None


class ResourceResolveResponse(ContractResponse):
    kind: str
    locator: ResourceLocatorResponse
    capabilities: list[str] = Field(default_factory=list)
    resolved_from: str | None = None


class ContextSegmentResponse(ContractResponse):
    id: str
    owner: str
    slot: str
    shape: str
    order: int
    capabilities: list[str] = Field(default_factory=list)
    root_refs: list[str] = Field(default_factory=list)
    chars: int = 0
    image_bytes: int = 0
    available_refs: list[str] = Field(default_factory=list)
    loaded_refs: list[str] = Field(default_factory=list)
    protected_refs: list[str] = Field(default_factory=list)


class ContextOverviewResponse(ContractResponse):
    generation_id: str
    captured_at: str
    turn_id: str
    day: str | None = None
    segments: list[ContextSegmentResponse] = Field(default_factory=list)
    resolved_references: dict[str, ResourceLocatorResponse] = Field(
        default_factory=dict
    )


class PageResponse(ContractResponse):
    ref: str | None = None
    kind: str | None = None
    items: list[Any] = Field(default_factory=list)
    children: list[Any] = Field(default_factory=list)
    content: list[Any] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    continuation: str | None = None
    truncated: bool | None = None
    complete: bool | None = None


class TurnResponse(ContractResponse):
    turn_id: str
    kind: str | None = None
    state: str | None = None
    active_day: str | None = None
    accepted: bool | None = None
    jobs: list[Any] = Field(default_factory=list)


class SearchResponse(PageResponse):
    operation: str | None = None
    candidates: list[Any] = Field(default_factory=list)
    query: str | None = None


class ConfigResponse(ContractResponse):
    view: str | None = None
    generation_id: str | None = None
    pending_reload: bool | None = None
    sources: list[Any] = Field(default_factory=list)
    presets: list[Any] = Field(default_factory=list)
