"""Build the complete Reflection branch from typed owner facades."""

from __future__ import annotations
from dataclasses import dataclass

from tinysoul.kernel.action import ActionEngine, LoadedActionCatalog
from tinysoul.kernel.context import ContextEngine, ContextSettings
from tinysoul.plugins.home import AgentHomeEngine
from tinysoul.plugins.memory.plugin import MemoryProfileSource
from tinysoul.plugins.session.plugin import SessionProfileSource
from tinysoul.plugins.workspace.plugin import WorkspaceProfileSource
from tinysoul.kernel.loop.assembly import (
    TurnProfile,
    build_turn_context,
    build_turn_kernel,
)
from tinysoul.kernel.registration import ProfileKind, ResolvedProfileExtensions, Service, ServiceRegistry
from tinysoul.plugins.home.services import HomeService
from tinysoul.kernel.loop.lifecycle.completion import AnswerCompletionDetector
from tinysoul.kernel.loop.turn import TurnActivityController
from tinysoul.plugins.home import HomeDomainSkillProvider
from tinysoul.kernel.loop.config import LoopSettings
from tinysoul.kernel.loop.phases import LLMRunner
from tinysoul.plugins.memory import MemoryEngine
from tinysoul.runtime import ObservationEmitter, SignalBus
from tinysoul.plugins.session import SessionEngine
from tinysoul.plugins.workspace import WorkspaceEngine

from .actions import ProfileAssemblyPort, build_reflection_action
from .config import ReflectionSettings
from .engine import ArchiveReader, ReflectionEngine
from .home import HomeReflectionTask
from tinysoul.plugins.memory.actions import MemoryWriteSession
from .memory import (
    MemoryReflectionContext,
    MemoryReflectionTask,
)
from .turn import (
    ReflectionTurnEntry,
    build_reflection_turn_trap,
    reflection_turn_guidance,
)


@dataclass(frozen=True)
class ReflectionAssembly:
    engine: ReflectionEngine
    profiles: tuple[TurnProfile, TurnProfile]


class ReflectionBuilder:
    """Own Archive, Home and Memory Reflection composition."""

    def __init__(
        self,
        *,
        context_settings: ContextSettings,
        loop_settings: LoopSettings,
        settings: ReflectionSettings,
        llm: LLMRunner,
        home: AgentHomeEngine,
        memory: MemoryEngine,
        session: SessionEngine,
        workspace: WorkspaceEngine,
        bus: SignalBus,
        observations: ObservationEmitter,
        archive: ArchiveReader,
        action_catalog: LoadedActionCatalog,
        action_assembly: ProfileAssemblyPort,
        memory_controller: MemoryWriteSession,
    ) -> None:
        self._context_settings = context_settings
        self._loop_settings = loop_settings
        self._settings = settings
        self._llm = llm
        self._home = home
        self._memory = memory
        self._session = session
        self._workspace = workspace
        self._bus = bus
        self._observations = observations
        self._archive = archive
        self._action_catalog = action_catalog
        self._action_assembly = action_assembly
        self._memory_controller = memory_controller

    def build(self) -> ReflectionAssembly:
        target_context = MemoryReflectionContext()
        home_context = build_turn_context(self._context_settings, self._observations)
        memory_context = build_turn_context(self._context_settings, self._observations)
        home_action, home_jobs, home_services = build_reflection_action(
            kind=ProfileKind.HOME_REFLECTION, context=home_context,
            assembly=self._action_assembly, action_catalog=self._action_catalog,
        )
        memory_action, memory_jobs, memory_services = build_reflection_action(
            kind=ProfileKind.MEMORY_REFLECTION, context=memory_context,
            assembly=self._action_assembly, action_catalog=self._action_catalog,
            bindings=ServiceRegistry((
                Service(MemoryProfileSource, MemoryProfileSource(target_context)),
                Service(SessionProfileSource, SessionProfileSource(target_context, target_context.source_day)),
                Service(WorkspaceProfileSource, WorkspaceProfileSource(target_context.source_workspace)),
            )),
        )
        home_turn, home_profile = self._build_turn(
            kind="home",
            context=home_context,
            action=home_action,
            jobs=home_jobs,
            plugins=home_services,
        )
        memory_turn, memory_profile = self._build_turn(
            kind="memory",
            context=memory_context,
            action=memory_action,
            jobs=memory_jobs,
            plugins=memory_services,
        )
        engine = ReflectionEngine(
            archive=self._archive,
            home=HomeReflectionTask(
                home=self._home,
                turn=home_turn,
            ),
            memory=MemoryReflectionTask(
                session=self._session,
                memory=self._memory,
                workspace=self._workspace,
                target_context=target_context,
                controller=self._memory_controller,
                turn=memory_turn,
            ),
            observations=self._observations,
        )
        return ReflectionAssembly(engine, (home_profile, memory_profile))

    def _build_turn(
        self,
        *,
        kind: str,
        context: ContextEngine,
        action: ActionEngine,
        jobs: TurnActivityController,
        plugins: ResolvedProfileExtensions,
    ) -> tuple[ReflectionTurnEntry, TurnProfile]:
        profile = TurnProfile(
            kind=(ProfileKind.HOME_REFLECTION if kind == "home" else ProfileKind.MEMORY_REFLECTION),
            context=context,
            action=action,
            services=plugins.services,
            trap=build_reflection_turn_trap(context, plugins=plugins),
            settings=self._settings.home if kind == "home" else self._settings.memory,
            cycle_settings=self._loop_settings.cycle,
            turn_guidance=reflection_turn_guidance(kind),
            completion_detector=AnswerCompletionDetector(),
            preparation_pipeline=plugins.preparation,
            completion_pipeline=plugins.completion,
            events=plugins.events,
            domain_skills=HomeDomainSkillProvider(plugins.services.get(HomeService)),
            activity_controller=jobs,
        )
        runner = build_turn_kernel(
            profile=profile,
            llm=self._llm,
            bus=self._bus,
            observations=self._observations,
        )
        return ReflectionTurnEntry(runner, kind=kind), profile
