"""TinySoul Agent Home resource module."""

from .actions import (
    HomePromptMountPatchExecutor,
    HomePromptMountWriteExecutor,
    HomeInspectExecutor,
    HomeSearchExecutor,
    HomeTopDeleteExecutor,
    HomeTopPatchExecutor,
    HomeTopWriteExecutor,
    register_home_actions,
)
from .background import (
    HomeBackgroundContentLoader,
    HomeBackgroundEntryProvider,
)
from .config import (
    AgentHomeSettings,
    HomeSearchSettings,
    parse_agent_home_settings,
)
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
    AgentHomeRuntimeCopyRequired,
)
from .failures import AgentHomeFailureKind
from .skills.guidance import HomeActionSkillProvider, HomeDomainSkillProvider
from .links import (
    HomeLink,
    HomePromptMountLink,
    HomeResourceLink,
    HomeTopLink,
    parse_home_link,
)
from .content.runtime_copy import AgentHomeRuntimeCopyTrapHandler
from .review import (
    HomeReviewChange,
    HomeReviewPending,
    HomeReview,
    HomeReviewResolveOutcome,
    HomeReviewResolution,
    HomeReviewSnapshot,
    HomeSkillReview,
    HomeSkillMemoryContext,
)
from .overlay import HomeOverlayRecord, HomeOverlayState
from .skills.metadata import HomeSkillMetadata, parse_home_skill_metadata

__all__ = [
    "AgentHomeContractError",
    "AgentHomeEngine",
    "AgentHomeEngineBuilder",
    "AgentHomeError",
    "AgentHomeFailureKind",
    "AgentHomeIOError",
    "AgentHomeInvariantError",
    "AgentHomeRuntimeCopyTrapHandler",
    "AgentHomeSettings",
    "AgentHomeRuntimeCopyRequired",
    "HomeActionSkillProvider",
    "HomeBackgroundContentLoader",
    "HomeBackgroundEntryProvider",
    "HomeBackgroundEntry",
    "HomeDomainSkillProvider",
    "HomeLink",
    "HomeReviewChange",
    "HomeReviewPending",
    "HomeReview",
    "HomeReviewResolveOutcome",
    "HomeReviewResolution",
    "HomeReviewSnapshot",
    "HomePromptMountLink",
    "HomePromptMountPatchExecutor",
    "HomePromptMountWriteExecutor",
    "HomeResourceLink",
    "HomeInspectExecutor",
    "HomeResourceMutation",
    "HomeOverlayRecord",
    "HomeOverlayState",
    "HomeTopLink",
    "HomeSearchExecutor",
    "HomeTopDeleteExecutor",
    "HomeTopPatchExecutor",
    "HomeTopWriteExecutor",
    "HomeSearchSettings",
    "HomeSkillMemoryContext",
    "HomeSkillReview",
    "HomeSkillMetadata",
    "parse_agent_home_settings",
    "parse_home_link",
    "parse_home_skill_metadata",
    "register_home_actions",
]
