"""TinySoul workspace resource module."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .actions import register_workspace_actions
from .config import (
    WorkspaceAnalysisSettings,
    WorkspaceSearchSettings,
    WorkspaceSettings,
    parse_workspace_settings,
)
from .engine import WorkspaceArchiveView, WorkspaceEngine, WorkspaceEngineBuilder
from .errors import (
    WorkspaceContractError,
    WorkspaceError,
    WorkspaceImageValidationError,
    WorkspaceInvariantError,
    WorkspaceIOError,
    WorkspaceReconciliationError,
)
from .inspection.models import (
    WorkspaceAnalysisBudgetFailure,
    WorkspaceAnalysisBudgetReason,
    WorkspaceAnalysisInput,
    WorkspaceAnalysisPreparation,
    WorkspaceAnalysisReference,
    WorkspaceBundleResult,
    WorkspaceBundleWrite,
    WorkspaceByteRead,
    WorkspaceDocumentRead,
    WorkspaceImageRead,
    WorkspacePromptInput,
    WorkspaceTextRangeResult,
    WorkspaceTextRead,
    WorkspaceTextSlice,
)
from .inspection.text import WorkspaceTextPosition, WorkspaceTextRangeRead
from .links import WorkspaceLink
from .projection import (
    WorkspaceTurnPreparationHandler,
    workspace_refresh_signal,
)
from .prompts import WorkspacePromptReferenceResolver
from .storage.manifest import (
    WorkspaceManifest,
    WorkspaceResourceKind,
    WorkspaceResourceRecord,
    WorkspaceTag,
)
from .storage.mutations import WorkspaceTextEdit
from .storage.reconcile import (
    WorkspaceDiscoverySkip,
    WorkspaceDiscoverySkipKind,
    WorkspaceReconcileResult,
    WorkspaceReconcileStatus,
)
from .storage.trash import WorkspaceTrashItem

__all__ = [
    "WorkspaceTag",
    "WorkspaceTextEdit",
    "WorkspaceContractError",
    "WorkspaceAnalysisSettings",
    "WorkspaceAnalysisBudgetFailure",
    "WorkspaceAnalysisBudgetReason",
    "WorkspaceAnalysisInput",
    "WorkspaceAnalysisPreparation",
    "WorkspaceAnalysisReference",
    "WorkspaceArchiveView",
    "WorkspaceBundleResult",
    "WorkspaceBundleWrite",
    "WorkspaceByteRead",
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
    "WorkspaceLink",
    "WorkspaceManifest",
    "WorkspacePromptInput",
    "WorkspacePromptReferenceResolver",
    "WorkspaceReconcileResult",
    "WorkspaceReconcileStatus",
    "WorkspaceResourceKind",
    "WorkspaceResourceRecord",
    "WorkspaceSettings",
    "WorkspaceSearchSettings",
    "WorkspaceTextRead",
    "WorkspaceTextPosition",
    "WorkspaceTextRangeRead",
    "WorkspaceTextRangeResult",
    "WorkspaceTextSlice",
    "WorkspaceTurnPreparationHandler",
    "workspace_refresh_signal",
    "WorkspaceTrashItem",
    "parse_workspace_settings",
    "register_workspace_actions",
]


def __getattr__(name: str) -> object:
    if name == "register_workspace_actions":
        from .actions import register_workspace_actions

        return register_workspace_actions
    raise AttributeError(name)
