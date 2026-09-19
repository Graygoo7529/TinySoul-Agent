"""Build the complete Reflection branch from typed owner facades."""

from __future__ import annotations
from dataclasses import dataclass

from tinysoul.kernel.action import ActionEngine, LoadedActionCatalog
from tinysoul.kernel.context import ContextEngine, ContextSettings
from tinysoul.plugins.home import AgentHomeEngine
from tinysoul.plugins.home.plugin import declare_home
from tinysoul.plugins.memory.plugin import declare_memory
from tinysoul.plugins.session.plugin import declare_session
from tinysoul.kernel.loop.assembly import (
    TurnProfile,
    build_turn_context,
    build_turn_kernel,
)
from tinysoul.kernel.registration import ServiceRegistry, Service, PluginDeclaration
from tinysoul.plugins.home.services import HomeReviewService, HomeService
from tinysoul.plugins.memory.services import MemoryKnowledgeService
from tinysoul.kernel.loop.lifecycle.completion import AnswerCompletionDetector
from tinysoul.kernel.loop.turn import TurnActivityController
from tinysoul.plugins.home import HomeDomainSkillProvider
from tinysoul.kernel.loop.config import LoopSettings
from tinysoul.kernel.loop.lifecycle.preparation import TurnPreparationPipeline
from tinysoul.kernel.loop.phases import LLMRunner
from tinysoul.plugins.memory import MemoryEngine
from tinysoul.runtime import ObservationEmitter, SignalBus
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge
from tinysoul.plugins.session import SessionEngine
from tinysoul.plugins.workspace import WorkspaceEngine, WorkspaceTurnPreparationHandler

from .actions import ReflectionActionAssembly, build_reflection_action
from .config import ReflectionSettings
from .engine import ArchiveReader, ReflectionEngine
from .home import HomeReflectionTask
from tinysoul.plugins.home.actions import HomeReviewExecutor
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
        action_assembly: ReflectionActionAssembly,
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

    def build(self) -> ReflectionAssembly:
        target_context = MemoryReflectionContext()
        home_context = build_turn_context(self._context_settings, self._observations)
        memory_context = build_turn_context(self._context_settings, self._observations)
        home_review = HomeReviewService(self._home)
        memory_knowledge = MemoryKnowledgeService(self._memory)
        home_controller = HomeReviewExecutor(home_review)
        memory_controller = MemoryWriteSession(
            memory=memory_knowledge,
        )
        common_plugins = (
            declare_home(self._home, self._llm, actual=True),
            declare_memory(self._memory),
            declare_session(self._session),
        )
        home_action, home_jobs, home_services = build_reflection_action(
            kind="home",
            context=home_context,
            assembly=self._action_assembly,
            home_controller=home_controller,
            memory_controller=memory_controller,
            action_catalog=self._action_catalog,
            plugins=(
                *common_plugins,
                PluginDeclaration(
                    "home_review", services=(Service(HomeReviewService, home_review),)
                ),
            ),
        )
        memory_action, memory_jobs, memory_services = build_reflection_action(
            kind="memory",
            context=memory_context,
            assembly=self._action_assembly,
            home_controller=home_controller,
            memory_controller=memory_controller,
            action_catalog=self._action_catalog,
            plugins=(
                declare_home(self._home, self._llm, actual=True),
                declare_memory(self._memory, target=target_context),
                declare_session(
                    self._session,
                    source=target_context,
                    source_day=target_context.source_day,
                ),
                PluginDeclaration(
                    "memory_knowledge",
                    services=(Service(MemoryKnowledgeService, memory_knowledge),),
                ),
            ),
            archive_source=target_context.source_workspace,
        )
        home_turn, home_profile = self._build_turn(
            kind="home",
            context=home_context,
            action=home_action,
            jobs=home_jobs,
            preparation=TurnPreparationPipeline(
                (
                    WorkspaceTurnPreparationHandler(
                        self._workspace,
                        runtime_bridge=RuntimeWorkspaceBridge(),
                    ),
                )
            ),
            services=home_services,
        )
        memory_turn, memory_profile = self._build_turn(
            kind="memory",
            context=memory_context,
            action=memory_action,
            jobs=memory_jobs,
            preparation=TurnPreparationPipeline(
                (
                    WorkspaceTurnPreparationHandler(
                        self._workspace, runtime_bridge=RuntimeWorkspaceBridge()
                    ),
                )
            ),
            services=memory_services,
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
                controller=memory_controller,
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
        preparation: TurnPreparationPipeline,
        services: ServiceRegistry,
    ) -> tuple[ReflectionTurnEntry, TurnProfile]:
        profile = TurnProfile(
            id=f"{kind}_reflection",
            context=context,
            action=action,
            services=services,
            trap=build_reflection_turn_trap(context, home=self._home),
            settings=self._settings.home if kind == "home" else self._settings.memory,
            cycle_settings=self._loop_settings.cycle,
            turn_guidance=reflection_turn_guidance(kind),
            completion_detector=AnswerCompletionDetector(),
            preparation_pipeline=preparation,
            domain_skills=HomeDomainSkillProvider(services.get(HomeService)),
            activity_controller=jobs,
        )
        runner = build_turn_kernel(
            profile=profile,
            llm=self._llm,
            bus=self._bus,
            observations=self._observations,
        )
        return ReflectionTurnEntry(runner, kind=kind), profile
