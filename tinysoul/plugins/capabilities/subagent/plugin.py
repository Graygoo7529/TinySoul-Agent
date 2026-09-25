"""ACP resources, events and profile actions under one generation owner."""

from dataclasses import dataclass
from functools import partial

from tinysoul.infra.concurrency import CleanupDiagnostic
from tinysoul.infra.process import ManagedProcessCloseError
from tinysoul.kernel.jobs import JobRegistry
from tinysoul.kernel.loop.interaction.events import TurnEventSubscription
from tinysoul.kernel.registration import (
    GenerationBuildContext,
    PluginConfig,
    PluginGeneration,
    PluginProfileExtension,
    PluginTurnResource,
    ProfileBuildContext,
    ProfileKind,
)
from tinysoul.plugins.workspace.services import WorkspaceExecutionService
from tinysoul.runtime.events import EventFilter

from .config import (
    SubagentSettings,
    parse_subagent_settings,
    validate_subagent_bindings,
)
from .engine import SubagentEngine
from .actions import register_subagent_actions
from .runtime_bridge import RuntimeSubagentBridge
from .segments.connections import connections_registration, connection_refresh


class SubagentTurnResources:
    def __init__(self, engine: SubagentEngine) -> None:
        self._engine = engine

    async def close_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]:
        try:
            return await self._engine.close_turn(turn_id)
        except ManagedProcessCloseError as exc:
            raise RuntimeSubagentBridge().close_failed(exc) from exc


@dataclass(frozen=True)
class SubagentPlugin:
    id = "subagent"
    model_uses = ()
    search_capabilities = ()
    provides = ()
    requires = (JobRegistry, WorkspaceExecutionService)
    configuration = (
        PluginConfig(
            "capabilities.subagent",
            SubagentSettings,
            lambda tree, root: parse_subagent_settings(tree),
            RuntimeSubagentBridge().from_config_error,
            validate_subagent_bindings,
        ),
    )

    async def build_generation(
        self, context: GenerationBuildContext
    ) -> PluginGeneration:
        engine = SubagentEngine(
            context.settings.get(SubagentSettings),
            jobs=context.services.get(JobRegistry),
            workspace=context.services.get(WorkspaceExecutionService),
            environment=context.runtime_env,
        )

        def extend(
            kind: ProfileKind, profile: ProfileBuildContext
        ) -> PluginProfileExtension:
            return PluginProfileExtension(
                self.id,
                actions=partial(
                    register_subagent_actions, engine=engine, scenario=kind.value
                ),
                segments=(connections_registration(engine),),
                events=(
                    TurnEventSubscription(
                        EventFilter(topic="subagent.connections", source="subagent"),
                        connection_refresh,
                        coalesce=True,
                        requires_decision=False,
                    ),
                ),
                turn_resources=(PluginTurnResource(SubagentTurnResources(engine)),),
            )

        async def release() -> tuple[CleanupDiagnostic, ...]:
            try:
                return await engine.release_day()
            except ManagedProcessCloseError as exc:
                raise RuntimeSubagentBridge().close_failed(exc) from exc

        async def close() -> tuple[CleanupDiagnostic, ...]:
            try:
                return await engine.close()
            except ManagedProcessCloseError as exc:
                raise RuntimeSubagentBridge().close_failed(exc) from exc

        return PluginGeneration(
            self.id,
            profile_extension_factory=extend,
            sources=(engine,),
            release_day=release,
            close=close,
        )
