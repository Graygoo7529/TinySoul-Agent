"""TinySoul workspace resource module."""

from .actions import register_workspace_actions
from .config import WorkspaceSettings, parse_workspace_settings
from .engine import (
    WorkspaceEngine,
    WorkspaceEngineBuilder,
    WorkspaceImageRead,
    WorkspacePromptInput,
    WorkspaceReconcileStatus,
    WorkspaceScanResult,
    WorkspaceScanSkip,
    WorkspaceScanSkipKind,
    WorkspaceTextRead,
    WorkspaceTextSlice,
)
from .errors import (
    WorkspaceContractError,
    WorkspaceError,
    WorkspaceIOError,
    WorkspaceInvariantError,
    WorkspaceReconciliationError,
)
from .failures import WorkspaceFailureKind
from .links import WorkspaceLink
from .manifest import (
    WorkspaceManifest,
    WorkspaceResourceKind,
    WorkspaceResourceRecord,
)
from .projection import WorkspaceTurnPreparationHandler
from .prompts import WorkspacePromptReferenceResolver

__all__ = [
    "WorkspaceContractError",
    "WorkspaceEngine",
    "WorkspaceEngineBuilder",
    "WorkspaceError",
    "WorkspaceFailureKind",
    "WorkspaceIOError",
    "WorkspaceImageRead",
    "WorkspaceInvariantError",
    "WorkspaceReconciliationError",
    "WorkspaceLink",
    "WorkspaceManifest",
    "WorkspacePromptInput",
    "WorkspacePromptReferenceResolver",
    "WorkspaceReconcileStatus",
    "WorkspaceResourceKind",
    "WorkspaceResourceRecord",
    "WorkspaceScanResult",
    "WorkspaceScanSkip",
    "WorkspaceScanSkipKind",
    "WorkspaceSettings",
    "WorkspaceTextRead",
    "WorkspaceTextSlice",
    "WorkspaceTurnPreparationHandler",
    "parse_workspace_settings",
    "register_workspace_actions",
]
