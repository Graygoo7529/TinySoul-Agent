"""Build the complete Reflection branch from typed owner facades."""

from __future__ import annotations
from dataclasses import dataclass

from tinysoul.kernel.action import ActionEngine, LoadedActionCatalog
from tinysoul.kernel.context import ContextEngine, ContextSettings
from tinysoul.plugins.home import AgentHomeEngine
from tinysoul.plugins.home.plugin import declare_home
from tinysoul.plugins.memory.plugin import declare_memory
from tinysoul.plugins.session.plugin import declare_session
from tinysoul.kernel.loop.assembly import TurnProfile, build_turn_context, build_turn_kernel
from tinysoul.kernel.registration import ServiceRegistry, Service, PluginDeclaration
from tinysoul.plugins.home.services import HomeReviewService, HomeService
from tinysoul.plugins.memory.services import MemoryKnowledgeService
from tinysoul.plugins.capabilities.assembly import CommonActionAssembly
from tinysoul.kernel.loop.completion import AnswerCompletionDetector
from tinysoul.plugins.capabilities.supervised_process import SupervisedProcessManager
from tinysoul.plugins.home import HomeDomainSkillProvider
from tinysoul.kernel.loop.config import LoopSettings
from tinysoul.kernel.loop.preparation import TurnPreparationPipeline
from tinysoul.kernel.loop.phases import LLMRunner
from tinysoul.plugins.memory import MemoryEngine
from tinysoul.runtime import ObservationEmitter, SignalBus
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge
from tinysoul.plugins.session import SessionEngine
from tinysoul.plugins.workspace import WorkspaceEngine, WorkspaceTurnPreparationHandler

from .actions import build_maintenance_action
from .availability import ReflectionAvailabilityStore
from .config import ReflectionSettings
from .engine import ArchiveReader, ReflectionEngine
from .home import HomeReflectionActionController, HomeReflectionTask
from .memory import (
    ArchivedMemoryReflectionContext,
    MemoryReflectionActionController,
    MemoryReflectionTask,
)
from .turn import (
    ReflectionTurnEntry,
    build_maintenance_turn_trap,
    maintenance_turn_guidance,
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
        action_assembly: CommonActionAssembly,
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
        archived_context = ArchivedMemoryReflectionContext()
        home_context = build_turn_context(self._context_settings, self._observations)
        memory_context = build_turn_context(self._context_settings, self._observations)
        home_review = HomeReviewService(self._home)
        memory_knowledge = MemoryKnowledgeService(self._memory)
        home_controller = HomeReflectionActionController(home_review)
        memory_controller = MemoryReflectionActionController(
            memory=memory_knowledge,
        )
        common_plugins = (declare_home(self._home, self._llm, actual=True),
                          declare_memory(self._memory), declare_session(self._session))
        home_action, home_jobs, home_services = build_maintenance_action(
            kind="home",
            context=home_context,
            assembly=self._action_assembly,
            home_controller=home_controller,
            memory_controller=memory_controller,
            action_catalog=self._action_catalog,
            plugins=(*common_plugins, PluginDeclaration("home_review", services=(Service(HomeReviewService, home_review),))),
            policy=self._settings.home.actions,
        )
        memory_action, memory_jobs, memory_services = build_maintenance_action(
            kind="memory",
            context=memory_context,
            assembly=self._action_assembly,
            home_controller=home_controller,
            memory_controller=memory_controller,
            action_catalog=self._action_catalog,
            plugins=(declare_home(self._home, self._llm, actual=True),
                     declare_memory(self._memory, target=archived_context),
                     declare_session(self._session, source=archived_context, source_day=archived_context.source_day),
                     PluginDeclaration("memory_knowledge", services=(Service(MemoryKnowledgeService, memory_knowledge),))),
            archive_source=archived_context.source_workspace,
            policy=self._settings.memory.actions,
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
                    WorkspaceTurnPreparationHandler(self._workspace, runtime_bridge=RuntimeWorkspaceBridge()),
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
                archived_context=archived_context,
                controller=memory_controller,
                turn=memory_turn,
            ),
            availability_store=ReflectionAvailabilityStore(
                self._settings.runtime_root
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
        jobs: SupervisedProcessManager,
        preparation: TurnPreparationPipeline,
        services: ServiceRegistry,
    ) -> tuple[ReflectionTurnEntry, TurnProfile]:
        profile = TurnProfile(
            id=f"{kind}_reflection",
            context=context,
            action=action,
            services=services,
            trap=build_maintenance_turn_trap(context, home=self._home, workspace=self._workspace),
            settings=self._settings.home if kind == "home" else self._settings.memory,
            cycle_settings=self._loop_settings.cycle,
            turn_guidance=maintenance_turn_guidance(kind),
            completion_detector=AnswerCompletionDetector(),
            preparation_pipeline=preparation,
            domain_skills=HomeDomainSkillProvider(services.get(HomeService)),
            activity_controller=jobs,
        )
        runner = build_turn_kernel(profile=profile, llm=self._llm, bus=self._bus, observations=self._observations)
        return ReflectionTurnEntry(runner, kind=kind), profile
