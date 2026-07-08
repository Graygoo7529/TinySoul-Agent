"""TinySoul workspace resource module."""

from .actions import register_workspace_actions
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
from .prompts import (
    WORKSPACE_TARGET_REFERENCE,
    WORKSPACE_TEXT_REFERENCE,
    WorkspacePromptReferenceResolver,
    prompt_blocks_from_workspace_input,
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
    "WorkspacePromptReferenceResolver",
    "WorkspaceResourceKind",
    "WorkspaceResourceRecord",
    "WorkspaceScanResult",
    "WorkspaceScanSkip",
    "WorkspaceScanSkipKind",
    "WorkspaceSettings",
    "WorkspaceTextRead",
    "WorkspaceTextSlice",
    "WORKSPACE_TARGET_REFERENCE",
    "WORKSPACE_TEXT_REFERENCE",
    "parse_workspace_settings",
    "prompt_blocks_from_workspace_input",
    "register_workspace_actions",
]
