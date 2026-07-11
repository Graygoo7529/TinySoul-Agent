"""TinySoul workspace resource module."""

from .actions import register_workspace_actions
from .config import WorkspaceSettings, parse_workspace_settings
from .engine import (
    WorkspaceEngine,
    WorkspaceEngineBuilder,
    WorkspaceImageRead,
    WorkspacePromptInput,
    WorkspaceTextRead,
    WorkspaceTextSlice,
)
from .errors import (
    WorkspaceContractError,
    WorkspaceError,
    WorkspaceImageValidationError,
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
from .reconcile import (
    WorkspaceDiscoverySkip,
    WorkspaceDiscoverySkipKind,
    WorkspaceReconcileResult,
    WorkspaceReconcileStatus,
)
from .projection import WorkspaceTurnPreparationHandler
from .prompts import WorkspacePromptReferenceResolver

__all__ = [
    "WorkspaceContractError",
    "WorkspaceEngine",
    "WorkspaceEngineBuilder",
    "WorkspaceError",
    "WorkspaceFailureKind",
    "WorkspaceDiscoverySkip",
    "WorkspaceDiscoverySkipKind",
    "WorkspaceIOError",
    "WorkspaceImageRead",
    "WorkspaceImageValidationError",
    "WorkspaceInvariantError",
    "WorkspaceReconciliationError",
    "WorkspaceLink",
    "WorkspaceManifest",
    "WorkspacePromptInput",
    "WorkspacePromptReferenceResolver",
    "WorkspaceReconcileResult",
    "WorkspaceReconcileStatus",
    "WorkspaceResourceKind",
    "WorkspaceResourceRecord",
    "WorkspaceSettings",
    "WorkspaceTextRead",
    "WorkspaceTextSlice",
    "WorkspaceTurnPreparationHandler",
    "parse_workspace_settings",
    "register_workspace_actions",
]
