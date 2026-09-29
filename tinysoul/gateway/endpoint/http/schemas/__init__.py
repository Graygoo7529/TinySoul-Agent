"""HTTP request schemas grouped by Endpoint protocol domain."""

from .configuration import (
    ConfigApplyRequest,
    ConfigDeleteMutationRequest,
    ConfigMutationRequest,
    ConfigPatchRequest,
    ConfigSetMutationRequest,
    PresetCreateRequest,
    PresetUpdateRequest,
)
from .reflection import ReflectionRequest
from .responses import (
    CommandReceiptResponse,
    ConfigResponse,
    ContextOverviewResponse,
    HealthResponse,
    PageResponse,
    ResourceResolveResponse,
    RuntimeStatusResponse,
    SearchResponse,
    TurnResponse,
)
from .runtime import ControlRequest, InputRequest
from .turns import (
    TurnCreateRequest,
    TurnGrantRequest,
    TurnInputRequest,
    TurnReplyRequest,
)
from .workspace import (
    WorkspaceRestoreRequest,
    WorkspaceTrashRequest,
    WorkspaceWriteRequest,
)

__all__ = [
    "ConfigDeleteMutationRequest",
    "ConfigApplyRequest",
    "ConfigMutationRequest",
    "ConfigPatchRequest",
    "ConfigSetMutationRequest",
    "PresetCreateRequest",
    "PresetUpdateRequest",
    "ControlRequest",
    "InputRequest",
    "TurnCreateRequest",
    "TurnGrantRequest",
    "TurnInputRequest",
    "TurnReplyRequest",
    "ReflectionRequest",
    "WorkspaceRestoreRequest",
    "WorkspaceTrashRequest",
    "WorkspaceWriteRequest",
    "CommandReceiptResponse",
    "ConfigResponse",
    "ContextOverviewResponse",
    "HealthResponse",
    "PageResponse",
    "ResourceResolveResponse",
    "RuntimeStatusResponse",
    "SearchResponse",
    "TurnResponse",
]
