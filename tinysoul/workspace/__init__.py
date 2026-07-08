"""TinySoul workspace resource module."""

from .config import WorkspaceSettings, parse_workspace_settings
from .engine import (
    WorkspaceEngine,
    WorkspaceEngineBuilder,
    WorkspacePromptInput,
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
)
from .failures import WorkspaceFailureKind
from .links import WorkspaceLink
from .manifest import (
    WorkspaceManifest,
    WorkspaceManifestStore,
    WorkspaceResourceKind,
    WorkspaceResourceRecord,
)

__all__ = [
    "WorkspaceContractError",
    "WorkspaceEngine",
    "WorkspaceEngineBuilder",
    "WorkspaceError",
    "WorkspaceFailureKind",
    "WorkspaceIOError",
    "WorkspaceInvariantError",
    "WorkspaceLink",
    "WorkspaceManifest",
    "WorkspaceManifestStore",
    "WorkspacePromptInput",
    "WorkspaceResourceKind",
    "WorkspaceResourceRecord",
    "WorkspaceScanResult",
    "WorkspaceScanSkip",
    "WorkspaceScanSkipKind",
    "WorkspaceSettings",
    "WorkspaceTextRead",
    "WorkspaceTextSlice",
    "parse_workspace_settings",
]
