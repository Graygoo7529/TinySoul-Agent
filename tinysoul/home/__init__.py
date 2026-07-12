"""TinySoul Agent Home resource module."""

from .actions import HomeResourceReadExecutor, register_home_actions
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
    AgentHomeRuntimeCopyRequired,
)
from .failures import AgentHomeFailureKind
from .guidance import HomeActionHowProvider, HomeDomainHowProvider
from .links import (
    HomeLink,
    HomePromptMountLink,
    HomeResourceLink,
    HomeTopLink,
    parse_home_link,
)
from .runtime_copy import (
    AgentHomeRuntimeCopyTrapHandler,
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
    "AgentHomeRuntimeCopyTrapHandler",
    "AgentHomeSettings",
    "AgentHomeRuntimeCopyRequired",
    "HomeActionHowProvider",
    "HomeBackgroundContentLoader",
    "HomeBackgroundEntryProvider",
    "HomeBackgroundEntry",
    "HomeDomainHowProvider",
    "HomeLink",
    "HomePromptMountLink",
    "HomeResourceLink",
    "HomeResourceReadExecutor",
    "HomeResourceMutation",
    "HomeOverlayRecord",
    "HomeOverlayState",
    "HomeTopLink",
    "parse_agent_home_settings",
    "parse_home_link",
    "register_home_actions",
]
