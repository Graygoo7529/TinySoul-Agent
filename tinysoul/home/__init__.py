"""TinySoul Agent Home resource module."""

from .actions import (
    HomePromptMountPatchExecutor,
    HomePromptMountWriteExecutor,
    HomeResourceReadExecutor,
    HomeTopDeleteExecutor,
    HomeTopPatchExecutor,
    HomeTopWriteExecutor,
    register_home_actions,
)
from .background import HomeBackgroundContentLoader, HomeBackgroundEntryProvider
from .config import AgentHomeSettings, parse_agent_home_settings
from .engine import (
    AgentHomeEngine,
    AgentHomeEngineBuilder,
    HomeBackgroundEntry,
    HomeResourceMutation,
)
from .errors import (
    AgentHomeContractError,
    AgentHomeError,
    AgentHomeIOError,
    AgentHomeInvariantError,
    AgentHomeReviewError,
    AgentHomeRuntimeCopyRequired,
)
from .failures import AgentHomeFailureKind
from .guidance import HomeActionHowProvider, HomeDomainHowProvider
from .links import (
    HomeLink,
    HomePromptMountLink,
    HomeResourceLink,
    HomeTopLink,
    HomeWhatKind,
    parse_home_link,
)
from .runtime_copy import (
    AgentHomeRuntimeCopyTrapHandler,
)
from .maintenance import (
    HomeMaintenanceChange,
    HomeMaintenanceDecision,
    HomeMaintenanceDecisionProvider,
    HomeMaintenanceFailure,
    HomeMaintenanceItemOutcome,
    HomeMaintenanceMode,
    HomeMaintenanceOutcome,
    HomeMaintenanceReviewer,
    HomeMaintenanceStatus,
    HomeSkillMemoryContext,
    LLMHomeMaintenanceReviewer,
)
from .overlay import HomeOverlayRecord, HomeOverlayState

__all__ = [
    "AgentHomeContractError",
    "AgentHomeEngine",
    "AgentHomeEngineBuilder",
    "AgentHomeError",
    "AgentHomeFailureKind",
    "AgentHomeIOError",
    "AgentHomeInvariantError",
    "AgentHomeReviewError",
    "AgentHomeRuntimeCopyTrapHandler",
    "AgentHomeSettings",
    "AgentHomeRuntimeCopyRequired",
    "HomeActionHowProvider",
    "HomeBackgroundContentLoader",
    "HomeBackgroundEntryProvider",
    "HomeBackgroundEntry",
    "HomeDomainHowProvider",
    "HomeLink",
    "HomeMaintenanceChange",
    "HomeMaintenanceDecision",
    "HomeMaintenanceDecisionProvider",
    "HomeMaintenanceFailure",
    "HomeMaintenanceItemOutcome",
    "HomeMaintenanceMode",
    "HomeMaintenanceOutcome",
    "HomeMaintenanceReviewer",
    "HomeMaintenanceStatus",
    "HomePromptMountLink",
    "HomePromptMountPatchExecutor",
    "HomePromptMountWriteExecutor",
    "HomeResourceLink",
    "HomeResourceReadExecutor",
    "HomeResourceMutation",
    "HomeOverlayRecord",
    "HomeOverlayState",
    "HomeTopLink",
    "HomeTopDeleteExecutor",
    "HomeTopPatchExecutor",
    "HomeTopWriteExecutor",
    "HomeWhatKind",
    "HomeSkillMemoryContext",
    "LLMHomeMaintenanceReviewer",
    "parse_agent_home_settings",
    "parse_home_link",
    "register_home_actions",
]
