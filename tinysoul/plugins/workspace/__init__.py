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
    WorkspaceTextRead,
    WorkspaceTextRangeResult,
    WorkspaceTextSlice,
)
from .storage.mutations import WorkspaceTextEdit
from .errors import (
    WorkspaceContractError,
    WorkspaceError,
    WorkspaceImageValidationError,
    WorkspaceIOError,
    WorkspaceInvariantError,
    WorkspaceReconciliationError,
)
from .links import WorkspaceLink
from .storage.manifest import (
    WorkspaceTag,
    WorkspaceManifest,
    WorkspaceResourceKind,
    WorkspaceResourceRecord,
)
from .storage.reconcile import (
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
from .inspection.search import (
    WorkspaceSearchCoverage,
    WorkspaceSearchFragment,
    WorkspaceSearchLineHint,
    WorkspaceSearchScope,
    WorkspaceSearchScopeKind,
    WorkspaceTextSearchResult,
)
from .storage.trash import WorkspaceTrashItem
from .inspection.text import WorkspaceTextPosition, WorkspaceTextRangeRead

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
