"""TinySoul Agent Home resource module."""

from .actions import HomeResourceReadExecutor
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
from .runtime_copy import AgentHomeRuntimeCopyManager, AgentHomeRuntimeCopyTrapHandler

__all__ = [
    "AgentHomeContractError",
    "AgentHomeEngine",
    "AgentHomeEngineBuilder",
    "AgentHomeError",
    "AgentHomeFailureKind",
    "AgentHomeIOError",
    "AgentHomeInvariantError",
    "AgentHomeRuntimeCopyManager",
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
]
