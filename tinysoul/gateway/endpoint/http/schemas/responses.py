"""Stable response envelopes used by the HTTP/OpenAPI boundary.

The endpoint services still own the complete JSON projections.  These models
document the fields consumed by the remote visualization while allowing owner
specific additions to remain visible without copying business state.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tinysoul.infra.json import JsonObject, JsonValue


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
    kind: str | None = None


class RuntimeStatusResponse(ContractResponse):
    protocol_version: int
    instance_id: str
    project_identity: str
    ready: bool
    active_day: str
    turn_active: bool
    runtime: JsonObject
    latest_event_sequence: int
    event_journal: JsonObject


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
    measurement: str
    day: str | None = None
    segments: list[ContextSegmentResponse] = Field(default_factory=list)
    resolved_references: dict[str, ResourceLocatorResponse] = Field(
        default_factory=dict
    )


class PageResponse(ContractResponse):
    ref: str | None = None
    kind: str | None = None
    view: str | None = None
    items: list[JsonValue]
    next_continuation: str | None = None
    content_fragment: JsonObject | None = None
    metadata: JsonObject | None = None
    truncated: bool | None = None


class ContextMessagesResponse(ContractResponse):
    turn_id: str
    segment_id: str
    messages: list[JsonValue]
    next_continuation: str | None = None
    content_fragment: JsonObject | None = None


class ReflectionOriginResponse(ContractResponse):
    trigger: str
    target_day: str | None
    instructions_excerpt: str
    truncated: bool
    instructions: str | None = None


class TurnSummaryResponse(ContractResponse):
    turn_id: str
    kind: str
    state: str
    status: str | None = None
    generation_id: str | None = None
    active_day: str | None = None
    accepted_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    reflection: ReflectionOriginResponse | None = None


class TurnListResponse(ContractResponse):
    items: list[TurnSummaryResponse]
    completed_limit: int


class TurnResponse(TurnSummaryResponse):
    cancel_requested: bool
    wait_reason: str | None
    question: JsonObject | None
    budget_request: JsonObject | None
    result: JsonObject | None
    jobs: list[JsonValue]


class InteractionPageResponse(PageResponse):
    turn_id: str
    day: str | None
    generation_id: str | None = None
    state: str | None = None
    status: str | None = None
    pending_items: list[JsonValue] = Field(default_factory=list)
    queued_request: JsonObject | None = None
    result: JsonObject | None = None
    history_unavailable: bool | None = None


class SearchResponse(ContractResponse):
    result_ref: str | None = None
    scope: str | JsonObject
    source: str
    items: list[JsonValue]
    coverage: JsonObject
    page: JsonObject
    continuation: str | None = None


class JobListResponse(ContractResponse):
    turn_id: str
    jobs: list[JsonValue]


class JobDetailResponse(ContractResponse):
    job_id: str
    kind: str
    state: str
    summary: str
    reason: str
    pending_inputs: list[JsonValue]
    result_links: list[str]
    details: JsonObject | None = None


class JobOutputResponse(ContractResponse):
    job_id: str
    items: list[JsonValue]
    next_continuation: str
    truncated: bool
    result_locators: list[JsonValue]


class ConfigResponse(ContractResponse):
    view: Literal["saved", "active"]
    generation_id: str
    activity: JsonObject
    pending_reload: bool
    sources: list[JsonValue]
    fields: JsonObject
    runtime: JsonObject | None = None
    process_shell: JsonObject | None = None


class ConfigCatalogResponse(ContractResponse):
    surfaces: list[JsonValue] = Field(default_factory=list)
    field_groups: list[JsonValue] = Field(default_factory=list)
    collections: list[JsonValue] = Field(default_factory=list)
    fields: list[JsonValue] = Field(default_factory=list)
    document_fields: list[JsonValue] = Field(default_factory=list)
    rules: JsonObject = Field(default_factory=dict)


class ActionCatalogResponse(ContractResponse):
    scenario: str | None = None
    domains: list[JsonValue] = Field(default_factory=list)
    actions: list[JsonValue] = Field(default_factory=list)


class ConfigMutationResponse(ContractResponse):
    state: Literal["saved", "active"]
    generation_id: str | None = None
    pending_reload: bool
    changed_fields: list[str]
    changed_sources: list[str]
    matching_presets: list[str] = Field(default_factory=list)
    cleanup_diagnostics: list[JsonValue] = Field(default_factory=list)


class PresetListResponse(ContractResponse):
    presets: list[JsonValue]


class PresetResponse(ContractResponse):
    schema_version: int
    id: str
    name: str
    description: str
    included_scopes: list[str]
    snapshot: JsonObject | None = None
    active_match: bool
    saved_match: bool
    validation_issues: list[JsonValue]
    created_at: str
    updated_at: str


class PresetDeleteResponse(ContractResponse):
    deleted: bool
    preset_id: str
