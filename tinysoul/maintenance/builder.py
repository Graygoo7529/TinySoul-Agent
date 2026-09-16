"""Build the complete Maintenance branch from typed owner facades."""

from __future__ import annotations

from tinysoul.workspace.projection import workspace_segment_registration

from tinysoul.action import ActionEngine, LoadedActionCatalog
from tinysoul.context import ContextEngine, ContextSettings
from tinysoul.home import AgentHomeEngine
from tinysoul.loop.assembly import build_turn_kernel
from tinysoul.loop.actions import CommonActionAssembly
from tinysoul.loop.completion import AnswerCompletionDetector
from tinysoul.capabilities.supervised_process import SupervisedProcessManager
from tinysoul.home import HomeDomainSkillProvider
from tinysoul.loop.config import LoopSettings
from tinysoul.loop.preparation import TurnPreparationPipeline
from tinysoul.loop.phases import LLMRunner
from tinysoul.memory import MemoryEngine
from tinysoul.runtime import ObservationEmitter, SignalBus
from tinysoul.context.runtime_bridge import RuntimeContextBridge
from tinysoul.workspace.runtime_bridge import RuntimeWorkspaceBridge
from tinysoul.session import SessionEngine
from tinysoul.session.projection import session_segment_registration
from tinysoul.workspace import WorkspaceEngine, WorkspaceTurnPreparationHandler

from .actions import build_maintenance_action
from .archive import DailyLifecycleCoordinator
from .availability import MaintenanceAvailabilityStore
from .config import MaintenanceSettings
from .context import build_maintenance_context
from .day import BusinessClock, IanaBusinessClock
from .engine import MaintenanceEngine
from .home import HomeMaintenanceActionController, HomeMaintenanceTask
from .memory import (
    ArchivedMemoryMaintenanceContext,
    MemoryMaintenanceActionController,
    MemoryMaintenanceTask,
)
from .turn import (
    MaintenanceTurnEntry,
    build_maintenance_turn_trap,
    maintenance_turn_guidance,
)


class MaintenanceBuilder:
    """Own Archive, Home and Memory Maintenance composition."""

    def __init__(
        self,
        *,
        context_settings: ContextSettings,
        loop_settings: LoopSettings,
        settings: MaintenanceSettings,
        llm: LLMRunner,
        home: AgentHomeEngine,
        memory: MemoryEngine,
        session: SessionEngine,
        workspace: WorkspaceEngine,
        bus: SignalBus,
        observations: ObservationEmitter,
        clock: BusinessClock | None = None,
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
        self._clock = clock
        self._action_catalog = action_catalog
        self._action_assembly = action_assembly

    def build(self) -> MaintenanceEngine:
        archived_context = ArchivedMemoryMaintenanceContext()
        home_context = build_maintenance_context(
            settings=self._context_settings,
            home=self._home,
            memory=self._memory,
            observations=self._observations,
        )
        memory_context = build_maintenance_context(
            settings=self._context_settings,
            home=self._home,
            memory=self._memory,
            observations=self._observations,
            memory_target_binding=archived_context,
        )
        home_controller = HomeMaintenanceActionController(self._home)
        home_context.register_segment(workspace_segment_registration())
        home_context.register_segment(session_segment_registration(self._session))
        memory_context.register_segment(session_segment_registration(archived_context))
        memory_context.register_segment(workspace_segment_registration())
        memory_controller = MemoryMaintenanceActionController(
            memory=self._memory,
        )
        home_action, home_jobs = build_maintenance_action(
            kind="home",
            context=home_context,
            assembly=self._action_assembly,
            home_controller=home_controller,
            memory_controller=memory_controller,
            action_catalog=self._action_catalog,
        )
        memory_action, memory_jobs = build_maintenance_action(
            kind="memory",
            context=memory_context,
            assembly=self._action_assembly,
            home_controller=home_controller,
            memory_controller=memory_controller,
            action_catalog=self._action_catalog,
        )
        home_turn = self._build_turn(
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
        )
        memory_turn = self._build_turn(
            kind="memory",
            context=memory_context,
            action=memory_action,
            jobs=memory_jobs,
            preparation=TurnPreparationPipeline(
                (
                    archived_context,
                )
            ),
        )
        return MaintenanceEngine(
            archive=DailyLifecycleCoordinator(
                session=self._session,
                archive_root=self._settings.archive_root,
                workspace=self._workspace,
                memory=self._memory,
                observations=self._observations,
            ),
            home=HomeMaintenanceTask(
                home=self._home,
                controller=home_controller,
                turn=home_turn,
            ),
            memory=MemoryMaintenanceTask(
                session=self._session,
                memory=self._memory,
                workspace=self._workspace,
                archived_context=archived_context,
                controller=memory_controller,
                turn=memory_turn,
            ),
            availability_store=MaintenanceAvailabilityStore(
                self._settings.runtime_root
            ),
            clock=self._clock or IanaBusinessClock(self._settings.timezone),
            observations=self._observations,
        )

    def _build_turn(
        self,
        *,
        kind: str,
        context: ContextEngine,
        action: ActionEngine,
        jobs: SupervisedProcessManager,
        preparation: TurnPreparationPipeline,
    ) -> MaintenanceTurnEntry:
        runner = build_turn_kernel(
            context=context,
            action=action,
            llm=self._llm,
            bus=self._bus,
            trap=build_maintenance_turn_trap(context),
            settings=self._settings.turn,
            cycle_settings=self._loop_settings.cycle,
            turn_guidance=maintenance_turn_guidance(kind),
            completion_detector=AnswerCompletionDetector(),
            preparation_pipeline=preparation,
            domain_skills=HomeDomainSkillProvider(self._home),
            activity_controller=jobs,
            observations=self._observations,
        )
        return MaintenanceTurnEntry(runner, kind=kind)
