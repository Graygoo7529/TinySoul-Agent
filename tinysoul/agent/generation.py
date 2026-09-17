"""Application-owned Runtime Generation aggregate."""

from __future__ import annotations

from dataclasses import dataclass, field

from tinysoul.infra.concurrency import AsyncResourceScope, CleanupDiagnostic

from tinysoul.infra.config import ConfigEnvironment
from tinysoul.infra import InfraSettings
from tinysoul.kernel.action import LoadedActionCatalog
from tinysoul.kernel.action.config import ActionSettings
from tinysoul.plugins.capabilities import CapabilitiesSettings
from tinysoul.kernel.context import ContextSettings
from tinysoul.plugins.home import AgentHomeSettings
from tinysoul.llm.config_types import LLMConfig, ProviderCredentialStatus
from tinysoul.kernel.loop.config import LoopSettings
from tinysoul.agent.user import UserTurnEntry
from tinysoul.plugins.reflection import (ReflectionEngine, ReflectionSettings)
from tinysoul.plugins.memory import MemorySettings
from tinysoul.plugins.session import SessionSettings
from tinysoul.plugins.workspace import WorkspaceEngine, WorkspaceSettings

from .config import AgentSettings
from .inputs import InputCommandParser
from .day import DayLifecycle


@dataclass(frozen=True)
class AgentConfigPlan:
    """One validated cross-module settings snapshot for Generation assembly."""

    environment: ConfigEnvironment
    infra: InfraSettings
    app: AgentSettings
    action: ActionSettings
    action_catalog: LoadedActionCatalog
    capabilities: CapabilitiesSettings
    context: ContextSettings
    llm: LLMConfig
    loop: LoopSettings
    maintenance: ReflectionSettings
    home: AgentHomeSettings
    memory: MemorySettings
    session: SessionSettings
    workspace: WorkspaceSettings


@dataclass(frozen=True)
class AgentRuntimeGeneration:
    """Business objects that are replaced together at an idle boundary."""

    config: ConfigEnvironment
    plan: AgentConfigPlan
    llm_provider_credentials: tuple[ProviderCredentialStatus, ...]
    user_turn: UserTurnEntry
    maintenance: ReflectionEngine
    day: DayLifecycle
    workspace: WorkspaceEngine
    input_parser: InputCommandParser
    app_settings: AgentSettings
    maintenance_settings: ReflectionSettings
    resources: AsyncResourceScope = field(default_factory=AsyncResourceScope)

    async def close(self) -> tuple[CleanupDiagnostic, ...]:
        """Release explicitly registered generation-owned resources once retired."""

        return await self.resources.close()
