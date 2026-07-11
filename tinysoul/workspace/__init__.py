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
from .links import WorkspaceLink
from .manifest import (
    WorkspaceManifest,
    WorkspaceRetention,
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
from .pressure import WorkspacePressureReclaimer, WorkspacePressureReport
from .trash import WorkspaceTrashItem, WorkspaceTrashStore

__all__ = [
    "WorkspaceContractError",
    "WorkspaceEngine",
    "WorkspaceEngineBuilder",
    "WorkspaceError",
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
    "WorkspacePressureReclaimer",
    "WorkspacePressureReport",
    "WorkspaceReconcileResult",
    "WorkspaceReconcileStatus",
    "WorkspaceResourceKind",
    "WorkspaceRetention",
    "WorkspaceResourceRecord",
    "WorkspaceSettings",
    "WorkspaceTextRead",
    "WorkspaceTextSlice",
    "WorkspaceTurnPreparationHandler",
    "WorkspaceTrashItem",
    "WorkspaceTrashStore",
    "parse_workspace_settings",
    "register_workspace_actions",
]
