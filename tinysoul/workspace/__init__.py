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
from .engine import (
    WorkspaceAnalysisBudgetFailure,
    WorkspaceAnalysisBudgetReason,
    WorkspaceAnalysisInput,
    WorkspaceAnalysisPreparation,
    WorkspaceAnalysisReference,
    WorkspaceBundleResult,
    WorkspaceBundleWrite,
    WorkspaceByteRead,
    WorkspaceDocumentRead,
    WorkspaceEngine,
    WorkspaceEngineBuilder,
    WorkspaceImageRead,
    WorkspacePromptInput,
    WorkspaceTextRead,
    WorkspaceTextRangeResult,
    WorkspaceTextSlice,
)
from .errors import (
    WorkspaceContractError,
    WorkspaceError,
    WorkspaceImageValidationError,
    WorkspaceIOError,
    WorkspaceInvariantError,
    WorkspaceMirrorConflict,
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
from .mirror import (
    WorkspaceMirror,
    WorkspaceMirrorCandidate,
    WorkspaceMirrorCommit,
    WorkspaceMirrorDiff,
    WorkspaceMirrorService,
)
from .prompts import WorkspacePromptReferenceResolver
from .search import (
    WorkspaceSearchCoverage,
    WorkspaceSearchFragment,
    WorkspaceSearchLineHint,
    WorkspaceSearchScope,
    WorkspaceSearchScopeKind,
    WorkspaceTextSearchResult,
)
from .trash import WorkspaceTrashItem
from .text import WorkspaceTextPosition, WorkspaceTextRangeRead

__all__ = [
    "WorkspaceContractError",
    "WorkspaceAnalysisSettings",
    "WorkspaceAnalysisBudgetFailure",
    "WorkspaceAnalysisBudgetReason",
    "WorkspaceAnalysisInput",
    "WorkspaceAnalysisPreparation",
    "WorkspaceAnalysisReference",
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
    "WorkspaceMirror",
    "WorkspaceMirrorCandidate",
    "WorkspaceMirrorCommit",
    "WorkspaceMirrorConflict",
    "WorkspaceMirrorDiff",
    "WorkspaceMirrorService",
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
    "WorkspaceSearchSettings",
    "WorkspaceSearchCoverage",
    "WorkspaceSearchFragment",
    "WorkspaceSearchLineHint",
    "WorkspaceSearchScope",
    "WorkspaceSearchScopeKind",
    "WorkspaceTextRead",
    "WorkspaceTextPosition",
    "WorkspaceTextRangeRead",
    "WorkspaceTextRangeResult",
    "WorkspaceTextSlice",
    "WorkspaceTextSearchResult",
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
