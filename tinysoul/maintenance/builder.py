"""Build the complete Maintenance branch from typed owner facades."""

from __future__ import annotations

from tinysoul.action import ActionEngine
from tinysoul.action.config import ActionSettings
from tinysoul.context import ContextEngine, ContextSettings
from tinysoul.context.preparation import ContextTurnPreparationHandler
from tinysoul.home import AgentHomeEngine
from tinysoul.loop.assembly import build_turn_kernel
from tinysoul.loop.config import LoopSettings
from tinysoul.loop.preparation import TurnPreparationPipeline
from tinysoul.loop.phases import LLMRunner
from tinysoul.memory import LLMDailyMemoryComposer, MemoryEngine
from tinysoul.runtime import ObservationEmitter, SignalBus
from tinysoul.runtime.bridge import (
    RuntimeContextBridge,
    RuntimeSessionBridge,
    RuntimeWorkspaceBridge,
)
from tinysoul.session import SessionEngine
from tinysoul.session.projection import SessionTurnPreparationHandler
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
    MaintenanceCompletionDetector,
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
        action_settings: ActionSettings | None = None,
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
        self._action_settings = action_settings or ActionSettings()

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
        memory_controller = MemoryMaintenanceActionController(
            memory=self._memory,
            composer=LLMDailyMemoryComposer(self._llm),
        )
        home_action = build_maintenance_action(
            kind="home",
            context=home_context,
            session=self._session,
            observations=self._observations,
            home_controller=home_controller,
            memory_controller=memory_controller,
            llm_action_timeout_seconds=(
                self._action_settings.llm_action_timeout_seconds
            ),
        )
        memory_action = build_maintenance_action(
            kind="memory",
            context=memory_context,
            session=archived_context,
            observations=self._observations,
            home_controller=home_controller,
            memory_controller=memory_controller,
            llm_action_timeout_seconds=(
                self._action_settings.llm_action_timeout_seconds
            ),
        )
        home_turn = self._build_turn(
            kind="home",
            context=home_context,
            action=home_action,
            preparation=TurnPreparationPipeline(
                (
                    ContextTurnPreparationHandler(
                        home_context,
                        runtime_bridge=RuntimeContextBridge(),
                    ),
                    SessionTurnPreparationHandler(
                        self._session,
                        runtime_bridge=RuntimeSessionBridge(),
                    ),
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
            preparation=TurnPreparationPipeline(
                (
                    ContextTurnPreparationHandler(
                        memory_context,
                        runtime_bridge=RuntimeContextBridge(),
                    ),
                    archived_context,
                )
            ),
        )
        return MaintenanceEngine(
            archive=DailyLifecycleCoordinator(
                archive_root=self._settings.archive_root,
                session=self._session,
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
                memory=self._memory,
                session=self._session,
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
        preparation: TurnPreparationPipeline,
    ) -> MaintenanceTurnEntry:
        runner = build_turn_kernel(
            context=context,
            action=action,
            llm=self._llm,
            bus=self._bus,
            trap=build_maintenance_turn_trap(context),
            settings=self._settings.turn,
            phase_retry_limit=self._loop_settings.phase_retry_limit,
            turn_guidance=maintenance_turn_guidance(kind),
            completion_detector=MaintenanceCompletionDetector(),
            preparation_pipeline=preparation,
            observations=self._observations,
        )
        return MaintenanceTurnEntry(runner, kind=kind)
