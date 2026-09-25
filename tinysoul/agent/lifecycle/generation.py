"""Application-owned Runtime Generation aggregate."""

from __future__ import annotations

from dataclasses import dataclass, field

from tinysoul.infra.concurrency import (
    AsyncResourceScope,
    CleanupDiagnostic,
)

from tinysoul.infra.config import ConfigEnvironment
from tinysoul.infra import InfraSettings
from tinysoul.kernel.action import LoadedActionCatalog
from tinysoul.kernel.action.config import ActionSettings
from tinysoul.kernel.action.models import ModelUseRegistry
from tinysoul.kernel.context import ContextSettings
from tinysoul.llm.config.types import LLMConfig, ProviderCredentialStatus
from tinysoul.kernel.loop.config import LoopSettings
from tinysoul.kernel.loop.assembly import TurnProfile
from tinysoul.kernel.registration import (
    PluginGeneration,
    ServiceExport,
    ServiceRegistration,
)
from tinysoul.agent.user import UserTurnEntry
from tinysoul.plugins.reflection import ReflectionEngine, ReflectionSettings
from tinysoul.plugins.workspace import WorkspaceEngine
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
    model_uses: ModelUseRegistry
    action_catalog: LoadedActionCatalog
    context: ContextSettings
    llm: LLMConfig
    loop: LoopSettings
    reflection: ReflectionSettings
    plugin_settings: tuple[ServiceRegistration, ...]


@dataclass(frozen=True)
class AgentGeneration:
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
    plugin_generations: tuple[PluginGeneration, ...] = ()
    sources: GenerationSources = field(default_factory=GenerationSources)

    @property
    def profiles(self) -> tuple[TurnProfile, ...]:
        return (self.user_turn.profile, *self.reflection_profiles)

    @property
    def sdk_exports(self) -> tuple[ServiceExport, ...]:
        return tuple(
            export
            for plugin in self.plugin_generations
            for export in plugin.sdk_exports
        )

    async def close(self) -> tuple[CleanupDiagnostic, ...]:
        """Release explicitly registered generation-owned resources once retired."""

        diagnostics = await self.sources.close()
        return (*diagnostics, *await self.resources.close())
