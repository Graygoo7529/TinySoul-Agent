"""HTTP request schemas grouped by Endpoint protocol domain."""

from .configuration import (
    ConfigDeleteMutationRequest,
    ConfigMutationRequest,
    ConfigPatchRequest,
    ConfigSetMutationRequest,
)
from .reflection import ReflectionRequest
from .runtime import ControlRequest, InputRequest
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
    "ReflectionRequest",
    "WorkspaceRestoreRequest",
    "WorkspaceTrashRequest",
    "WorkspaceWriteRequest",
]
