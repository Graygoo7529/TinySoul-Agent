"""TinySoul Agent Home resource module."""

from .actions import HomeResourceReadExecutor, register_home_actions
from .config import AgentHomeSettings, parse_agent_home_settings
from .engine import AgentHomeEngine, AgentHomeEngineBuilder, HomeBackgroundEntry
from .errors import (
    AgentHomeContractError,
    AgentHomeError,
    AgentHomeIOError,
    AgentHomeInvariantError,
    AgentHomeRuntimeCopyRequired,
)
from .failures import AgentHomeFailureKind
from .guidance import HomeDomainGuidanceProvider
from .links import HomeLink, HomeResourceLink, HomeTopLink, parse_home_link
from .runtime_copy import (
    AgentHomeRuntimeCopyManager,
    AgentHomeRuntimeCopyRecovery,
    AgentHomeRuntimeCopyTrapHandler,
)

__all__ = [
    "AgentHomeContractError",
    "AgentHomeEngine",
    "AgentHomeEngineBuilder",
    "AgentHomeError",
    "AgentHomeFailureKind",
    "AgentHomeIOError",
    "AgentHomeInvariantError",
    "AgentHomeRuntimeCopyManager",
    "AgentHomeRuntimeCopyRecovery",
    "AgentHomeRuntimeCopyTrapHandler",
    "AgentHomeSettings",
    "AgentHomeRuntimeCopyRequired",
    "HomeBackgroundEntry",
    "HomeDomainGuidanceProvider",
    "HomeLink",
    "HomeResourceLink",
    "HomeResourceReadExecutor",
    "HomeTopLink",
    "parse_agent_home_settings",
    "parse_home_link",
    "register_home_actions",
]
