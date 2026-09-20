"""HTTP request schemas grouped by Endpoint protocol domain."""

from .configuration import (
    ConfigDeleteMutationRequest,
    ConfigMutationRequest,
    ConfigPatchRequest,
    ConfigSetMutationRequest,
)
from .reflection import ReflectionRequest
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
    "ConfigMutationRequest",
    "ConfigPatchRequest",
    "ConfigSetMutationRequest",
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
]
