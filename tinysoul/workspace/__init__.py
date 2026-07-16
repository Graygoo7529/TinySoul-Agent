"""TinySoul workspace resource module."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .actions import register_workspace_actions
from .config import WorkspaceSettings, parse_workspace_settings
from .engine import (
    WorkspaceBundleResult,
    WorkspaceBundleWrite,
    WorkspaceDocumentRead,
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
    WorkspaceTrashRestoreRequired,
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
from .projection import (
    WorkspaceTurnPreparationHandler,
    workspace_snapshot_signal,
)
from .prompts import WorkspacePromptReferenceResolver
from .trash import WorkspaceTrashItem

__all__ = [
    "WorkspaceContractError",
    "WorkspaceBundleResult",
    "WorkspaceBundleWrite",
    "WorkspaceDocumentRead",
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
    "WorkspaceTrashRestoreRequired",
    "WorkspaceLink",
    "WorkspaceManifest",
    "WorkspacePromptInput",
    "WorkspacePromptReferenceResolver",
    "WorkspaceReconcileResult",
    "WorkspaceReconcileStatus",
    "WorkspaceResourceKind",
    "WorkspaceRetention",
    "WorkspaceResourceRecord",
    "WorkspaceSettings",
    "WorkspaceTextRead",
    "WorkspaceTextSlice",
    "WorkspaceTurnPreparationHandler",
    "workspace_snapshot_signal",
    "WorkspaceTrashItem",
    "parse_workspace_settings",
    "register_workspace_actions",
]


def __getattr__(name: str) -> object:
    if name == "register_workspace_actions":
        from .actions import register_workspace_actions

        return register_workspace_actions
    raise AttributeError(name)
