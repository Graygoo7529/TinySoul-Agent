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
from tinysoul.llm.config.types import LLMConfig, ProviderCredentialStatus
from tinysoul.kernel.loop.config import LoopSettings
from tinysoul.kernel.loop.assembly import TurnProfile
from tinysoul.agent.user import UserTurnEntry
from tinysoul.plugins.reflection import ReflectionEngine, ReflectionSettings
from tinysoul.plugins.memory import MemorySettings
from tinysoul.plugins.session import SessionSettings
from tinysoul.plugins.workspace import WorkspaceEngine, WorkspaceSettings
from tinysoul.plugins.execution import ExecutionSettings
from tinysoul.kernel.jobs.config import JobSettings
from tinysoul.kernel.jobs.models import JobControl

from ..config import AgentSettings
from ..dispatch.inputs import InputCommandParser
from .day import DayLifecycle
from .sources import GenerationSources


@dataclass(frozen=True)
class AgentConfigPlan:
    """One validated cross-module settings snapshot for Generation assembly."""

    environment: ConfigEnvironment
    infra: InfraSettings
    agent: AgentSettings
    action: ActionSettings
    action_catalog: LoadedActionCatalog
    capabilities: CapabilitiesSettings
    context: ContextSettings
    llm: LLMConfig
    loop: LoopSettings
    reflection: ReflectionSettings
    home: AgentHomeSettings
    memory: MemorySettings
    session: SessionSettings
    workspace: WorkspaceSettings
    execution: ExecutionSettings
    jobs: JobSettings


@dataclass(frozen=True)
class AgentRuntimeGeneration:
    """Business objects that are replaced together at an idle boundary."""

    config: ConfigEnvironment
    plan: AgentConfigPlan
    llm_provider_credentials: tuple[ProviderCredentialStatus, ...]
    user_turn: UserTurnEntry
    reflection: ReflectionEngine
    day: DayLifecycle
    workspace: WorkspaceEngine
    jobs: JobControl
    input_parser: InputCommandParser
    agent_settings: AgentSettings
    reflection_settings: ReflectionSettings
    resources: AsyncResourceScope = field(default_factory=AsyncResourceScope)
    reflection_profiles: tuple[TurnProfile, ...] = ()
    sources: GenerationSources = field(default_factory=GenerationSources)

    @property
    def profiles(self) -> tuple[TurnProfile, ...]:
        return (self.user_turn.profile, *self.reflection_profiles)

    async def close(self) -> tuple[CleanupDiagnostic, ...]:
        """Release explicitly registered generation-owned resources once retired."""

        diagnostics = await self.sources.close()
        return (*diagnostics, *await self.resources.close())
