"""TinySoul application assembly entry point."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tinysoul.action import (
    ActionEngine,
    ActionEngineBuilder,
    ActionError,
    builtin_action_catalog_root,
)
from tinysoul.action.backends.llm_action import LLMActionTaskRunner
from tinysoul.action.builtins.core import register_core_actions
from tinysoul.capabilities import CapabilitiesSettings, parse_capabilities_settings
from tinysoul.capabilities.resource import register_resource_actions
from tinysoul.capabilities.shell import register_shell_actions
from tinysoul.capabilities.script import (
    ScriptSourceResolver,
    register_script_actions,
)
from tinysoul.capabilities.supervised_process import (
    SupervisedProcessAnswerGuard,
    SupervisedProcessManager,
    register_supervised_process_actions,
)
from tinysoul.capabilities.web import register_web_actions
from tinysoul.context import (
    ContextEngine,
    ContextEngineBuilder,
    ContextSettings,
    parse_context_settings,
)
from tinysoul.context.preparation import ContextTurnPreparationHandler
from tinysoul.context.actions import register_context_actions
from tinysoul.context.errors import ContextError
from tinysoul.endpoint import (
    EndpointEngine,
    EndpointEventBuffer,
    EndpointHost,
    EndpointReady,
    EndpointSettings,
)
from tinysoul.home import (
    ActualHomeBackgroundEntryProvider,
    AgentHomeEngine,
    AgentHomeEngineBuilder,
    AgentHomeRuntimeCopyTrapHandler,
    HomeActionHowProvider,
    HomeBackgroundEntryProvider,
    HomeDomainHowProvider,
    LLMHomeSearchReranker,
    parse_agent_home_settings,
    register_home_actions,
)
from tinysoul.home.errors import AgentHomeError
from tinysoul.memory import (
    LLMMemoryConsolidator,
    LLMMemorySearchReranker,
    MemoryBackgroundEntryProvider,
    MemoryEngine,
    parse_memory_settings,
    register_memory_actions,
)
from tinysoul.memory.errors import MemoryError
from tinysoul.infra import StagingDirectoryManager, StagingError
from tinysoul.infra.config import ConfigEnvironment, ConfigError
from tinysoul.llm.config import LLMConfigParser
from tinysoul.llm.provider import ProviderError
from tinysoul.llm.provider.factory import build_provider_registry
from tinysoul.llm.task import LLMTaskRunner
from tinysoul.loop.config import LoopSettings, parse_loop_settings
from tinysoul.maintenance import (
    BusinessClock,
    DailyLifecycleCoordinator,
    IanaBusinessClock,
    MaintenanceEngine,
    MaintenanceAvailabilityStore,
    MaintenanceSettings,
    parse_maintenance_settings,
)
from tinysoul.maintenance.actions import (
    COMMON_MAINTENANCE_READ_ACTIONS,
    MAINTENANCE_ACTIONS,
    maintenance_action_view,
    user_action_view,
)
from tinysoul.maintenance.home import (
    HOME_MAINTENANCE_ACTIONS,
    HomeMaintenanceActionController,
    HomeMaintenanceTask,
    register_home_maintenance_actions,
)
from tinysoul.maintenance.memory import (
    MEMORY_MAINTENANCE_ACTIONS,
    MemoryMaintenanceActionController,
    MemoryMaintenanceTask,
    register_memory_maintenance_actions,
)
from tinysoul.loop.completion import (
    TurnCompletionHandler,
    TurnCompletionPipeline,
)
from tinysoul.loop.context_signals import ContextSignalConsumer
from tinysoul.loop.cycle import CycleRunner
from tinysoul.loop.phases import LLMRunner, Phase1Unit, Phase2Unit, Phase3Unit
from tinysoul.loop.preparation import TurnPreparationPipeline
from tinysoul.loop.pressure import ContextPressureRecovery
from tinysoul.loop.maintenance import (
    ArchivedMaintenanceContext,
    MaintenanceCompletionDetector,
    maintenance_turn_guidance,
)
from tinysoul.loop.user import (
    USER_TURN_GUIDANCE,
    UserAnswerCompletionDetector,
    user_output_from_completion,
)
from .program import ProgramRunner
from tinysoul.loop.prompts import DomainHowProvider, EmptyDomainHowProvider
from tinysoul.loop.trap_handlers import (
    ContextPressureTrapHandler,
    EndFrameTrapHandler,
    EndTurnOrProgramTrapHandler,
    WorkspaceTrashRestoreTrapHandler,
)
from tinysoul.loop.turn import TurnRunner
from tinysoul.runtime import (
    CONTEXT_COMPRESSION_REQUIRED,
    HOME_RUNTIME_COPY_REQUIRED,
    RUNTIME_CYCLE_END,
    RUNTIME_PROGRAM_END,
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    WORKSPACE_TRASH_RESTORE_REQUIRED,
    ObservationEmitter,
    ObservationLevel,
    RunLevel,
    RuntimeException,
    RuntimeModuleRunner,
    RuntimeTrap,
    SignalBus,
    TrapHandlerRegistry,
)
from tinysoul.runtime.bridge import (
    RuntimeActionBridge,
    RuntimeAgentHomeBridge,
    RuntimeAppBridge,
    RuntimeContextBridge,
    RuntimeInfraBridge,
    RuntimeLLMBridge,
    RuntimeLoopBridge,
    RuntimeMaintenanceBridge,
    RuntimeMemoryBridge,
    RuntimeSessionBridge,
    RuntimeScriptBridge,
    RuntimeShellBridge,
    RuntimeSupervisedProcessBridge,
    RuntimeWorkspaceBridge,
)
from tinysoul.session import SessionEngine, parse_session_settings
from tinysoul.session.actions import SessionInspector, register_session_actions
from tinysoul.session.errors import SessionError
from tinysoul.session.projection import (
    SessionTurnCompletionHandler,
    SessionTurnPreparationHandler,
)
from tinysoul.workspace import (
    WorkspaceEngine,
    WorkspaceEngineBuilder,
    WorkspaceMirrorService,
    WorkspacePromptReferenceResolver,
    WorkspaceTurnPreparationHandler,
    parse_workspace_settings,
    register_workspace_actions,
)
from tinysoul.workspace.errors import WorkspaceError

from .config import AppSettings, parse_app_settings
from .errors import AppError, AppInvariantError
from .gateway import AppCommandGateway
from .inputs import InputCommandParser, InputDispatcher, InputSource
from .outputs import ConsoleOutputSink, ObservationRoute, ObservationRouter, OutputSink
from .runtime import TinySoulApp
from .sources import MaintenanceScheduler, TerminalInputSource


class TinySoulAppBuilder:
    """Assemble TinySoul runtime modules into a runnable application."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path.cwd()
        self._loop_settings: LoopSettings | None = None
        self._maintenance_settings: MaintenanceSettings | None = None
        self._app_settings: AppSettings | None = None
        self._config_env: ConfigEnvironment | None = None
        self._llm: LLMRunner | None = None
        self._action: ActionEngine | None = None
        self._context: ContextEngine | None = None
        self._session: SessionEngine | None = None
        self._memory: MemoryEngine | None = None
        self._business_clock: BusinessClock | None = None
        self._bus: SignalBus | None = None
        self._domain_how: DomainHowProvider | None = None
        self._input_parser: InputCommandParser | None = None
        self._input_sources: list[InputSource] = []
        self._turn_completion_handlers: list[TurnCompletionHandler] = []
        self._output_sinks: list[OutputSink] = []
        self._endpoint_settings: EndpointSettings | None = None
        self._endpoint_ready: Callable[[EndpointReady], None] | None = None

    def with_loop_settings(self, settings: LoopSettings) -> "TinySoulAppBuilder":
        self._loop_settings = settings
        return self

    def with_maintenance_settings(
        self,
        settings: MaintenanceSettings,
    ) -> "TinySoulAppBuilder":
        self._maintenance_settings = settings
        return self

    def with_app_settings(self, settings: AppSettings) -> "TinySoulAppBuilder":
        self._app_settings = settings
        return self

    def with_config_environment(
        self,
        config: ConfigEnvironment,
    ) -> "TinySoulAppBuilder":
        self._config_env = config
        return self

    def with_llm_runner(self, llm: LLMRunner) -> "TinySoulAppBuilder":
        self._llm = llm
        return self

    def with_action_engine(self, action: ActionEngine) -> "TinySoulAppBuilder":
        self._action = action
        return self

    def with_context_engine(self, context: ContextEngine) -> "TinySoulAppBuilder":
        self._context = context
        return self

    def with_session_engine(self, session: SessionEngine) -> "TinySoulAppBuilder":
        self._session = session
        return self

    def with_memory_engine(self, memory: MemoryEngine) -> "TinySoulAppBuilder":
        self._memory = memory
        return self

    def with_business_clock(
        self,
        clock: BusinessClock,
    ) -> "TinySoulAppBuilder":
        self._business_clock = clock
        return self

    def with_signal_bus(self, bus: SignalBus) -> "TinySoulAppBuilder":
        self._bus = bus
        return self

    def with_domain_how(
        self,
        domain_how: DomainHowProvider,
    ) -> "TinySoulAppBuilder":
        self._domain_how = domain_how
        return self

    def with_input_parser(self, parser: InputCommandParser) -> "TinySoulAppBuilder":
        self._input_parser = parser
        return self

    def with_input_source(self, source: InputSource) -> "TinySoulAppBuilder":
        self._input_sources.append(source)
        return self

    def with_turn_completion_handler(
        self,
        handler: TurnCompletionHandler,
    ) -> "TinySoulAppBuilder":
        self._turn_completion_handlers.append(handler)
        return self

    def with_output_sink(self, sink: OutputSink) -> "TinySoulAppBuilder":
        self._output_sinks.append(sink)
        return self

    def with_endpoint(
        self,
        settings: EndpointSettings,
        *,
        ready: Callable[[EndpointReady], None] | None = None,
    ) -> "TinySoulAppBuilder":
        self._endpoint_settings = settings
        self._endpoint_ready = ready
        return self

    def build(self) -> TinySoulApp:
        app_bridge = RuntimeAppBridge()
        infra_bridge = RuntimeInfraBridge()
        llm_bridge = RuntimeLLMBridge()
        loop_bridge = RuntimeLoopBridge()
        maintenance_bridge = RuntimeMaintenanceBridge()
        action_bridge = RuntimeActionBridge()
        context_bridge = RuntimeContextBridge()
        session_bridge = RuntimeSessionBridge()
        workspace_bridge = RuntimeWorkspaceBridge()
        home_bridge = RuntimeAgentHomeBridge()
        memory_bridge = RuntimeMemoryBridge()
        script_bridge = RuntimeScriptBridge()
        shell_bridge = RuntimeShellBridge()
        supervised_process_bridge = RuntimeSupervisedProcessBridge()
        try:
            config = (
                self._config_env
                if self._config_env is not None
                else ConfigEnvironment.from_project_root(self._root)
            )
            config.validate_sections(
                {
                    "config",
                    "app",
                    "loop",
                    "llm",
                    "context",
                    "home",
                    "memory",
                    "maintenance",
                    "session",
                    "workspace",
                    "capabilities",
                }
            )
            loop_settings = (
                self._loop_settings
                if self._loop_settings is not None
                else self._build_loop_settings(config, loop_bridge)
            )
            maintenance_settings = (
                self._maintenance_settings
                if self._maintenance_settings is not None
                else self._build_maintenance_settings(config, maintenance_bridge)
            )
            app_settings = (
                self._app_settings
                if self._app_settings is not None
                else self._build_app_settings(config, app_bridge)
            )
            context_settings = self._build_context_settings(config, context_bridge)
            capabilities_settings = self._build_capabilities_settings(
                config,
                script_bridge,
                shell_bridge,
                supervised_process_bridge,
            )
            output_sinks = tuple(self._output_sinks)
            endpoint_events: EndpointEventBuffer | None = None
            if (
                not output_sinks
                and app_settings.interactive
                and self._endpoint_settings is None
            ):
                output_sinks = (
                    ConsoleOutputSink(max_chars=app_settings.output.model_max_chars),
                )
            output_routes = tuple(
                ObservationRoute(sink=sink, mode=app_settings.output.mode)
                for sink in output_sinks
            )
            if self._endpoint_settings is not None:
                endpoint_events = EndpointEventBuffer(
                    capacity=self._endpoint_settings.event_capacity,
                    max_bytes=self._endpoint_settings.event_bytes,
                )
                output_routes = (
                    *output_routes,
                    ObservationRoute(
                        sink=endpoint_events,
                        mode=ObservationLevel.MODEL,
                    ),
                )
            observations = ObservationRouter(
                mode=(
                    _higher_observation_level(
                        app_settings.output.mode,
                        ObservationLevel.MODEL,
                    )
                    if self._endpoint_settings is not None
                    else app_settings.output.mode
                ),
                routes=output_routes,
            )
            bus = self._bus if self._bus is not None else SignalBus()
            llm = (
                self._llm
                if self._llm is not None
                else self._build_llm(
                    config,
                    llm_bridge,
                    observations,
                    context_trigger_ratio=context_settings.compression_trigger_ratio,
                )
            )
            home = self._build_home(config, home_bridge)
            memory = (
                self._memory
                if self._memory is not None
                else self._build_memory(
                    config,
                    memory_bridge,
                    home,
                    observations,
                )
            )
            workspace = self._build_workspace(
                config,
                workspace_bridge,
                observations,
            )
            session = (
                self._session
                if self._session is not None
                else self._build_session(config, session_bridge)
            )
            context = (
                self._context
                if self._context is not None
                else self._build_context(
                    context_settings,
                    home,
                    memory,
                    observations,
                    context_bridge,
                    home_bridge,
                    memory_bridge,
                )
            )
            maintenance_context = self._build_maintenance_context(
                context_settings,
                home,
                memory,
                observations,
                context_bridge,
                home_bridge,
                memory_bridge,
            )
            domain_how = self._domain_how or HomeDomainHowProvider(
                home,
                runtime_bridge=home_bridge,
            )
            action_how = HomeActionHowProvider(
                home,
                runtime_bridge=home_bridge,
            )
            llm_action = LLMActionTaskRunner(
                llm_runner=llm,
                context=context,
                action_how=action_how,
            )
            memory_consolidator = LLMMemoryConsolidator(llm)
            process_jobs: SupervisedProcessManager | None = None
            if self._action is not None:
                action = self._action
            else:
                staging = StagingDirectoryManager(self._root)
                try:
                    staging.prepare()
                except StagingError as exc:
                    raise infra_bridge.startup_failure(
                        message=str(exc),
                        payload={"error_type": type(exc).__name__},
                    ) from exc
                process_jobs = SupervisedProcessManager(
                    settings=capabilities_settings.supervised_process,
                    mirror_service=WorkspaceMirrorService(
                        workspace,
                        max_files=(
                            capabilities_settings.supervised_process.max_mirror_files
                        ),
                        max_total_bytes=(
                            capabilities_settings.supervised_process.max_mirror_bytes
                        ),
                        max_file_bytes=(
                            capabilities_settings.supervised_process.max_mirror_file_bytes
                        ),
                    ),
                    staging=staging,
                    runtime_bridge=supervised_process_bridge,
                )
                script_resolver = ScriptSourceResolver(
                    workspace=workspace,
                    home=home,
                    max_source_chars=capabilities_settings.script.max_source_chars,
                )
                action = self._build_action(
                    bus=bus,
                    workspace=workspace,
                    context=context,
                    session=session,
                    home=home,
                    memory=memory,
                    home_bridge=home_bridge,
                    memory_bridge=memory_bridge,
                    context_bridge=context_bridge,
                    session_bridge=session_bridge,
                    workspace_bridge=workspace_bridge,
                    action_bridge=action_bridge,
                    script_bridge=script_bridge,
                    shell_bridge=shell_bridge,
                    llm_action=llm_action,
                    llm=llm,
                    observations=observations,
                    capabilities_settings=capabilities_settings,
                    runtime_env=config.runtime_env,
                    staging=staging,
                    process_jobs=process_jobs,
                    script_resolver=script_resolver,
                )
            user_action = user_action_view(action)
            try:
                home.reconcile_prompt_mounts(
                    domains=user_action.domain_names(),
                    actions=user_action.action_identifiers(),
                )
            except AgentHomeError as exc:
                raise home_bridge.startup_failure(
                    message=str(exc),
                    payload={"error_type": type(exc).__name__},
                ) from exc
            trap = self._build_trap(context, home, workspace)
            module_runner = RuntimeModuleRunner(
                trap=trap,
                bus=bus,
                observations=observations,
            )
            signal_consumer = ContextSignalConsumer(
                context=context,
                bus=bus,
                module_runner=module_runner,
            )
            phase1 = Phase1Unit(
                context=context,
                action=user_action,
                llm=llm,
                bus=bus,
                retry_limit=loop_settings.phase_retry_limit,
                signal_consumer=signal_consumer,
                turn_guidance=USER_TURN_GUIDANCE,
            )
            phase2 = Phase2Unit(
                context=context,
                action=user_action,
                llm=llm,
                bus=bus,
                retry_limit=loop_settings.phase_retry_limit,
                domain_how=domain_how,
                signal_consumer=signal_consumer,
                observations=observations,
                turn_guidance=USER_TURN_GUIDANCE,
            )
            phase3 = Phase3Unit(
                context=context,
                action=user_action,
                bus=bus,
                module_runner=module_runner,
                signal_consumer=signal_consumer,
                observations=observations,
                completion_detector=UserAnswerCompletionDetector(),
            )
            cycle_runner = CycleRunner(
                context=context,
                bus=bus,
                trap=trap,
                phase1=phase1,
                phase2=phase2,
                phase3=phase3,
                signal_consumer=signal_consumer,
                observations=observations,
            )
            user_turn = TurnRunner(
                context=context,
                bus=bus,
                trap=trap,
                cycle_runner=cycle_runner,
                settings=loop_settings.user,
                completion_to_output=user_output_from_completion,
                signal_consumer=signal_consumer,
                completion_pipeline=TurnCompletionPipeline(
                    (
                        SessionTurnCompletionHandler(
                            session,
                            runtime_bridge=session_bridge,
                        ),
                        *self._turn_completion_handlers,
                    )
                ),
                preparation_pipeline=TurnPreparationPipeline(
                    (
                        ContextTurnPreparationHandler(
                            context,
                            runtime_bridge=context_bridge,
                        ),
                        SessionTurnPreparationHandler(
                            session,
                            runtime_bridge=session_bridge,
                        ),
                        WorkspaceTurnPreparationHandler(
                            workspace,
                            runtime_bridge=workspace_bridge,
                        ),
                    )
                ),
                activity_controller=process_jobs,
                observations=observations,
            )
            daily_lifecycle = DailyLifecycleCoordinator(
                archive_root=maintenance_settings.archive_root,
                session=session,
                workspace=workspace,
                observations=observations,
            )
            archived_context = ArchivedMaintenanceContext(
                session_bridge=session_bridge,
            )
            home_controller = HomeMaintenanceActionController(home)
            memory_controller = MemoryMaintenanceActionController(
                memory=memory,
                consolidator=memory_consolidator,
                timezone=maintenance_settings.timezone,
            )
            home_maintenance_action = self._build_maintenance_action(
                kind="home",
                context=maintenance_context,
                session=session,
                context_bridge=context_bridge,
                session_bridge=session_bridge,
                action_bridge=action_bridge,
                observations=observations,
                home_controller=home_controller,
                memory_controller=memory_controller,
            )
            memory_maintenance_action = self._build_maintenance_action(
                kind="memory",
                context=maintenance_context,
                session=archived_context,
                context_bridge=context_bridge,
                session_bridge=session_bridge,
                action_bridge=action_bridge,
                observations=observations,
                home_controller=home_controller,
                memory_controller=memory_controller,
            )
            maintenance_trap = self._build_trap(
                maintenance_context,
                home,
                workspace,
            )
            maintenance_module_runner = RuntimeModuleRunner(
                trap=maintenance_trap,
                bus=bus,
                observations=observations,
            )
            maintenance_signal_consumer = ContextSignalConsumer(
                context=maintenance_context,
                bus=bus,
                module_runner=maintenance_module_runner,
            )
            home_maintenance_turn = self._build_maintenance_turn(
                kind="home",
                context=maintenance_context,
                action=home_maintenance_action,
                llm=llm,
                bus=bus,
                trap=maintenance_trap,
                module_runner=maintenance_module_runner,
                signal_consumer=maintenance_signal_consumer,
                settings=loop_settings,
                preparation=TurnPreparationPipeline(
                    (
                        ContextTurnPreparationHandler(
                            maintenance_context,
                            runtime_bridge=context_bridge,
                        ),
                        SessionTurnPreparationHandler(
                            session,
                            runtime_bridge=session_bridge,
                        ),
                        WorkspaceTurnPreparationHandler(
                            workspace,
                            runtime_bridge=workspace_bridge,
                        ),
                    )
                ),
                observations=observations,
            )
            memory_maintenance_turn = self._build_maintenance_turn(
                kind="memory",
                context=maintenance_context,
                action=memory_maintenance_action,
                llm=llm,
                bus=bus,
                trap=maintenance_trap,
                module_runner=maintenance_module_runner,
                signal_consumer=maintenance_signal_consumer,
                settings=loop_settings,
                preparation=TurnPreparationPipeline(
                    (
                        ContextTurnPreparationHandler(
                            maintenance_context,
                            runtime_bridge=context_bridge,
                        ),
                        archived_context,
                    )
                ),
                observations=observations,
            )
            maintenance_engine = MaintenanceEngine(
                archive=daily_lifecycle,
                home=HomeMaintenanceTask(
                    home=home,
                    controller=home_controller,
                    turn=home_maintenance_turn,
                ),
                memory=MemoryMaintenanceTask(
                    memory=memory,
                    session=session,
                    workspace=workspace,
                    archived_context=archived_context,
                    controller=memory_controller,
                    turn=memory_maintenance_turn,
                ),
                availability_store=MaintenanceAvailabilityStore(
                    maintenance_settings.runtime_root
                ),
                clock=(
                    self._business_clock
                    or IanaBusinessClock(maintenance_settings.timezone)
                ),
                observations=observations,
            )
            program_runner = ProgramRunner(
                user_turn=user_turn,
                maintenance=maintenance_engine,
                bus=bus,
                trap=trap,
                retained_outcomes=app_settings.retained_outcomes,
                maintenance_bridge=maintenance_bridge,
                observations=observations,
            )
            parser = self._input_parser or InputCommandParser(app_settings.input_commands)
            dispatcher = InputDispatcher(
                parser=parser,
                bus=bus,
                program_inputs=program_runner.input_queue,
                active_turn_scope=lambda: user_turn.active_scope,
                observations=observations,
                program_scope=program_runner.scope,
            )
            gateway = AppCommandGateway(
                dispatcher=dispatcher,
                bus=bus,
                active_turn_scope=lambda: user_turn.active_scope,
                program_scope=program_runner.scope,
            )
            endpoint: EndpointEngine | None = None
            services = ()
            input_sources = tuple(self._input_sources)
            if self._endpoint_settings is not None:
                if endpoint_events is None:
                    raise AppInvariantError("Endpoint event buffer was not assembled")
                endpoint = EndpointEngine(
                    settings=self._endpoint_settings,
                    events=endpoint_events,
                    gateway=gateway,
                    workspace=workspace,
                    maintenance=maintenance_engine,
                )
                services = (
                    EndpointHost(
                        engine=endpoint,
                        settings=self._endpoint_settings,
                        ready=self._endpoint_ready,
                    ),
                )
            if (
                not input_sources
                and app_settings.interactive
                and self._endpoint_settings is None
            ):
                input_sources = (
                    TerminalInputSource(
                        eof_command=app_settings.input_commands.exit_commands[0],
                    ),
                )
            program_request_sources = (
                (
                    MaintenanceScheduler(
                        maintenance_settings.schedule,
                        timezone=maintenance_settings.timezone,
                    ),
                )
                if maintenance_settings.schedule.enabled
                else ()
            )
            return TinySoulApp(
                program_runner=program_runner,
                input_dispatcher=dispatcher,
                gateway=gateway,
                input_sources=input_sources,
                program_request_sources=program_request_sources,
                services=services,
                observations=observations,
                endpoint=endpoint,
            )
        except ConfigError as exc:
            raise infra_bridge.from_config_error(exc) from exc
        except ProviderError as exc:
            raise llm_bridge.startup_failure(
                message=str(exc),
                payload={"error_type": type(exc).__name__},
            ) from exc
        except AppError as exc:
            raise app_bridge.from_app_error(exc) from exc
        except RuntimeException:
            raise

    def _build_llm(
        self,
        config: ConfigEnvironment,
        bridge: RuntimeLLMBridge,
        observations: ObservationEmitter,
        *,
        context_trigger_ratio: float,
    ) -> LLMTaskRunner:
        try:
            llm_config = config.parse_section("llm", LLMConfigParser().parse)
            providers = build_provider_registry(
                llm_config.providers,
                env=config.runtime_env,
            )
            return LLMTaskRunner(
                models=llm_config.models,
                providers=providers,
                tasks=llm_config.tasks,
                runtime_bridge=bridge,
                observations=observations,
                context_trigger_ratio=context_trigger_ratio,
            )
        except ConfigError as exc:
            enriched = config.enrich_error(exc)
            raise bridge.from_config_error(enriched) from exc

    def _build_loop_settings(
        self,
        config: ConfigEnvironment,
        bridge: RuntimeLoopBridge,
    ) -> LoopSettings:
        try:
            return config.parse_section(
                "loop",
                parse_loop_settings,
            )
        except ConfigError as exc:
            raise bridge.from_config_error(exc) from exc

    def _build_maintenance_settings(
        self,
        config: ConfigEnvironment,
        bridge: RuntimeMaintenanceBridge,
    ) -> MaintenanceSettings:
        try:
            return config.parse_section(
                "maintenance",
                lambda tree: parse_maintenance_settings(
                    tree,
                    project_root=self._root,
                ),
            )
        except ConfigError as exc:
            raise bridge.from_config_error(exc) from exc

    def _build_app_settings(
        self,
        config: ConfigEnvironment,
        bridge: RuntimeAppBridge,
    ) -> AppSettings:
        try:
            return config.parse_section("app", parse_app_settings)
        except ConfigError as exc:
            raise bridge.from_config_error(exc) from exc

    def _build_home(
        self,
        config: ConfigEnvironment,
        bridge: RuntimeAgentHomeBridge,
    ) -> AgentHomeEngine:
        try:
            settings = config.parse_section(
                "home",
                lambda tree: parse_agent_home_settings(
                    tree,
                    project_root=self._root,
                ),
            )
            home = AgentHomeEngineBuilder(settings).build()
            return home
        except ConfigError as exc:
            raise bridge.from_config_error(exc) from exc
        except AgentHomeError as exc:
            raise bridge.startup_failure(
                message=str(exc),
                payload={"error_type": type(exc).__name__},
            ) from exc

    def _build_workspace(
        self,
        config: ConfigEnvironment,
        bridge: RuntimeWorkspaceBridge,
        observations: ObservationEmitter,
    ) -> WorkspaceEngine:
        try:
            settings = config.parse_section(
                "workspace",
                lambda tree: parse_workspace_settings(
                    tree,
                    project_root=self._root,
                ),
            )
            return WorkspaceEngineBuilder(
                settings,
                observations=observations,
            ).build()
        except ConfigError as exc:
            raise bridge.from_config_error(exc) from exc
        except WorkspaceError as exc:
            raise bridge.startup_failure(
                message=str(exc),
                payload={"error_type": type(exc).__name__},
            ) from exc

    def _build_memory(
        self,
        config: ConfigEnvironment,
        bridge: RuntimeMemoryBridge,
        home: AgentHomeEngine,
        observations: ObservationEmitter,
    ) -> MemoryEngine:
        try:
            settings = config.parse_section(
                "memory",
                lambda tree: parse_memory_settings(tree, project_root=self._root),
            )
            return MemoryEngine(
                settings=settings,
                home_catalog=home,
                observations=observations,
            )
        except ConfigError as exc:
            raise bridge.from_config_error(exc) from exc
        except MemoryError as exc:
            raise bridge.startup_failure(
                message=str(exc),
                payload={"error_type": type(exc).__name__},
            ) from exc

    def _build_capabilities_settings(
        self,
        config: ConfigEnvironment,
        script_bridge: RuntimeScriptBridge,
        shell_bridge: RuntimeShellBridge,
        supervised_process_bridge: RuntimeSupervisedProcessBridge,
    ) -> CapabilitiesSettings:
        try:
            return config.parse_section(
                "capabilities",
                parse_capabilities_settings,
            )
        except ConfigError as exc:
            if exc.key == "capabilities.script" or exc.key.startswith(
                "capabilities.script."
            ):
                raise script_bridge.from_config_error(exc) from exc
            if exc.key == "capabilities.supervised_process" or exc.key.startswith(
                "capabilities.supervised_process."
            ):
                raise supervised_process_bridge.from_config_error(exc) from exc
            if exc.key == "capabilities.shell" or exc.key.startswith(
                "capabilities.shell."
            ):
                raise shell_bridge.from_config_error(exc) from exc
            raise

    def _build_context_settings(
        self,
        config: ConfigEnvironment,
        bridge: RuntimeContextBridge,
    ) -> ContextSettings:
        try:
            return config.parse_section("context", parse_context_settings)
        except ConfigError as exc:
            enriched = config.enrich_error(exc)
            raise bridge.from_config_error(enriched) from exc

    def _build_context(
        self,
        settings: ContextSettings,
        home: AgentHomeEngine,
        memory: MemoryEngine,
        observations: ObservationEmitter,
        bridge: RuntimeContextBridge,
        home_bridge: RuntimeAgentHomeBridge,
        memory_bridge: RuntimeMemoryBridge,
    ) -> ContextEngine:
        try:
            builder = (
                ContextEngineBuilder(system_text=settings.system_text)
                .with_journal(settings.journal)
                .with_observations(observations)
                .with_budget_max_image_bytes(settings.budget_max_image_bytes)
                .with_trace_heap(
                    chunk_max_chars=settings.trace_chunk_max_chars,
                    branch_factor=settings.trace_branch_factor,
                    min_hot_entries=settings.trace_min_hot_entries,
                )
                .with_trace_inspect_max_chars(settings.trace_inspect_max_chars)
                .with_compression_trigger_ratio(settings.compression_trigger_ratio)
                .with_compression_target_ratio(settings.compression_target_ratio)
                .add_background_provider(
                    HomeBackgroundEntryProvider(
                        home=home,
                        runtime_bridge=home_bridge,
                    )
                )
                .add_background_provider(
                    MemoryBackgroundEntryProvider(
                        memory=memory,
                        runtime_bridge=memory_bridge,
                    )
                )
            )
            return builder.build()
        except ConfigError as exc:
            raise bridge.from_config_error(exc) from exc
        except ContextError as exc:
            raise bridge.startup_failure(
                message=str(exc),
                payload={"error_type": type(exc).__name__},
            ) from exc
        except AgentHomeError as exc:
            raise home_bridge.startup_failure(
                message=str(exc),
                payload={"error_type": type(exc).__name__},
            ) from exc

    def _build_maintenance_context(
        self,
        settings: ContextSettings,
        home: AgentHomeEngine,
        memory: MemoryEngine,
        observations: ObservationEmitter,
        bridge: RuntimeContextBridge,
        home_bridge: RuntimeAgentHomeBridge,
        memory_bridge: RuntimeMemoryBridge,
    ) -> ContextEngine:
        """Build an independent Context using actual Home as its baseline."""

        try:
            return (
                ContextEngineBuilder(system_text=settings.system_text)
                .with_journal(settings.journal)
                .with_observations(observations)
                .with_budget_max_image_bytes(settings.budget_max_image_bytes)
                .with_trace_heap(
                    chunk_max_chars=settings.trace_chunk_max_chars,
                    branch_factor=settings.trace_branch_factor,
                    min_hot_entries=settings.trace_min_hot_entries,
                )
                .with_trace_inspect_max_chars(settings.trace_inspect_max_chars)
                .with_compression_trigger_ratio(settings.compression_trigger_ratio)
                .with_compression_target_ratio(settings.compression_target_ratio)
                .add_background_provider(
                    ActualHomeBackgroundEntryProvider(
                        home=home,
                        runtime_bridge=home_bridge,
                    )
                )
                .add_background_provider(
                    MemoryBackgroundEntryProvider(
                        memory=memory,
                        runtime_bridge=memory_bridge,
                    )
                )
                .build()
            )
        except ConfigError as exc:
            raise bridge.from_config_error(exc) from exc
        except ContextError as exc:
            raise bridge.startup_failure(
                message=str(exc),
                payload={"error_type": type(exc).__name__},
            ) from exc
        except AgentHomeError as exc:
            raise home_bridge.startup_failure(
                message=str(exc),
                payload={"error_type": type(exc).__name__},
            ) from exc

    def _build_session(
        self,
        config: ConfigEnvironment,
        bridge: RuntimeSessionBridge,
    ) -> SessionEngine:
        try:
            settings = config.parse_section(
                "session",
                lambda tree: parse_session_settings(
                    tree,
                    project_root=self._root,
                ),
            )
            return SessionEngine(settings)
        except ConfigError as exc:
            raise bridge.from_config_error(exc) from exc
        except SessionError as exc:
            raise bridge.startup_failure(
                message=str(exc),
                payload={"error_type": type(exc).__name__},
            ) from exc

    def _build_action(
        self,
        *,
        bus: SignalBus,
        workspace: WorkspaceEngine,
        context: ContextEngine,
        session: SessionEngine,
        home: AgentHomeEngine,
        memory: MemoryEngine,
        home_bridge: RuntimeAgentHomeBridge,
        memory_bridge: RuntimeMemoryBridge,
        context_bridge: RuntimeContextBridge,
        session_bridge: RuntimeSessionBridge,
        workspace_bridge: RuntimeWorkspaceBridge,
        action_bridge: RuntimeActionBridge,
        script_bridge: RuntimeScriptBridge,
        shell_bridge: RuntimeShellBridge,
        llm_action: LLMActionTaskRunner,
        llm: LLMRunner,
        observations: ObservationEmitter,
        capabilities_settings: CapabilitiesSettings,
        runtime_env: dict[str, str],
        staging: StagingDirectoryManager,
        process_jobs: SupervisedProcessManager,
        script_resolver: ScriptSourceResolver,
    ) -> ActionEngine:
        try:
            with builtin_action_catalog_root() as catalog_root:
                builder = ActionEngineBuilder(catalog_root)
                builder.with_observations(observations)
                builder.disable_actions(*MAINTENANCE_ACTIONS)
                register_context_actions(
                    builder,
                    context=context,
                    runtime_bridge=context_bridge,
                )
                register_session_actions(
                    builder,
                    session=session,
                    runtime_bridge=session_bridge,
                )
                register_workspace_actions(
                    builder,
                    workspace=workspace,
                    bus=bus,
                    llm_action=llm_action,
                    runtime_bridge=workspace_bridge,
                )
                register_resource_actions(
                    builder,
                    settings=capabilities_settings.resource,
                    workspace=workspace,
                    bus=bus,
                    runtime_bridge=workspace_bridge,
                    staging=staging,
                )
                register_web_actions(
                    builder,
                    settings=capabilities_settings.web,
                    runtime_env=runtime_env,
                    workspace=workspace,
                    bus=bus,
                    runtime_bridge=workspace_bridge,
                    staging=staging,
                )
                try:
                    register_script_actions(
                        builder,
                        settings=capabilities_settings.script,
                        resolver=script_resolver,
                        jobs=process_jobs,
                        workspace=workspace,
                        bus=bus,
                        llm_action=llm_action,
                        home_bridge=home_bridge,
                        workspace_bridge=workspace_bridge,
                    )
                except ConfigError as exc:
                    raise script_bridge.from_config_error(exc) from exc
                try:
                    register_shell_actions(
                        builder,
                        settings=capabilities_settings.shell,
                        jobs=process_jobs,
                        bus=bus,
                        workspace_bridge=workspace_bridge,
                    )
                except ConfigError as exc:
                    raise shell_bridge.from_config_error(exc) from exc
                script_process_enabled = (
                    capabilities_settings.script.enabled
                    and (
                        capabilities_settings.script.python.enabled
                        or capabilities_settings.script.bash.enabled
                    )
                )
                shell_process_enabled = (
                    capabilities_settings.shell.enabled
                    and (
                        capabilities_settings.shell.powershell.enabled
                        or capabilities_settings.shell.cmd.enabled
                        or capabilities_settings.shell.bash.enabled
                    )
                )
                register_supervised_process_actions(
                    builder,
                    enabled=script_process_enabled or shell_process_enabled,
                    jobs=process_jobs,
                    bus=bus,
                    workspace_bridge=workspace_bridge,
                )
                builder.register_execution_hook(
                    "supervised_process.answer_guard",
                    SupervisedProcessAnswerGuard(process_jobs),
                )
                builder.use_action_execution_hooks(
                    "core.answer",
                    "supervised_process.answer_guard",
                )
                register_home_actions(
                    builder,
                    home=home,
                    runtime_bridge=home_bridge,
                    search_reranker=LLMHomeSearchReranker(llm),
                )
                register_memory_actions(
                    builder,
                    memory=memory,
                    runtime_bridge=memory_bridge,
                    search_reranker=LLMMemorySearchReranker(llm),
                )
                register_core_actions(
                    builder,
                    reference_resolvers=(
                        WorkspacePromptReferenceResolver(
                            workspace,
                            runtime_bridge=workspace_bridge,
                        ),
                    ),
                    llm_action=llm_action,
                )
                return builder.build()
        except ConfigError as exc:
            raise action_bridge.from_config_error(exc) from exc
        except ActionError as exc:
            raise action_bridge.startup_failure(
                message=str(exc),
                payload={"error_type": type(exc).__name__},
            ) from exc

    def _build_maintenance_action(
        self,
        *,
        kind: str,
        context: ContextEngine,
        session: SessionInspector,
        context_bridge: RuntimeContextBridge,
        session_bridge: RuntimeSessionBridge,
        action_bridge: RuntimeActionBridge,
        observations: ObservationEmitter,
        home_controller: HomeMaintenanceActionController,
        memory_controller: MemoryMaintenanceActionController,
    ) -> ActionEngine:
        task_actions = {
            "home": HOME_MAINTENANCE_ACTIONS,
            "memory": MEMORY_MAINTENANCE_ACTIONS,
        }[kind]
        try:
            with builtin_action_catalog_root() as catalog_root:
                builder = ActionEngineBuilder(catalog_root)
                builder.with_observations(observations)
                builder.include_actions(
                    *COMMON_MAINTENANCE_READ_ACTIONS,
                    *task_actions,
                )
                register_context_actions(
                    builder,
                    context=context,
                    runtime_bridge=context_bridge,
                )
                register_session_actions(
                    builder,
                    session=session,
                    runtime_bridge=session_bridge,
                )
                if kind == "home":
                    register_home_maintenance_actions(
                        builder,
                        controller=home_controller,
                    )
                else:
                    register_memory_maintenance_actions(
                        builder,
                        controller=memory_controller,
                    )
                return maintenance_action_view(builder.build(), kind=kind)
        except (ConfigError, ActionError) as exc:
            if isinstance(exc, ConfigError):
                raise action_bridge.from_config_error(exc) from exc
            raise action_bridge.startup_failure(
                message=str(exc),
                payload={"error_type": type(exc).__name__},
            ) from exc

    def _build_maintenance_turn(
        self,
        *,
        kind: str,
        context: ContextEngine,
        action: ActionEngine,
        llm: LLMRunner,
        bus: SignalBus,
        trap: RuntimeTrap,
        module_runner: RuntimeModuleRunner,
        signal_consumer: ContextSignalConsumer,
        settings: LoopSettings,
        preparation: TurnPreparationPipeline,
        observations: ObservationEmitter,
    ) -> TurnRunner:
        guidance = maintenance_turn_guidance(kind)
        phase1 = Phase1Unit(
            context=context,
            action=action,
            llm=llm,
            bus=bus,
            retry_limit=settings.phase_retry_limit,
            signal_consumer=signal_consumer,
            turn_guidance=guidance,
        )
        phase2 = Phase2Unit(
            context=context,
            action=action,
            llm=llm,
            bus=bus,
            retry_limit=settings.phase_retry_limit,
            domain_how=EmptyDomainHowProvider(),
            signal_consumer=signal_consumer,
            observations=observations,
            turn_guidance=guidance,
        )
        phase3 = Phase3Unit(
            context=context,
            action=action,
            bus=bus,
            module_runner=module_runner,
            signal_consumer=signal_consumer,
            observations=observations,
            completion_detector=MaintenanceCompletionDetector(),
        )
        cycle = CycleRunner(
            context=context,
            bus=bus,
            trap=trap,
            phase1=phase1,
            phase2=phase2,
            phase3=phase3,
            signal_consumer=signal_consumer,
            observations=observations,
        )
        return TurnRunner(
            context=context,
            bus=bus,
            trap=trap,
            cycle_runner=cycle,
            settings=settings.maintenance,
            completion_to_output=lambda _completion: None,
            signal_consumer=signal_consumer,
            preparation_pipeline=preparation,
            observations=observations,
        )

    def _build_trap(
        self,
        context: ContextEngine,
        home: AgentHomeEngine,
        workspace: WorkspaceEngine,
    ) -> RuntimeTrap:
        registry = TrapHandlerRegistry()
        registry.register(RUNTIME_TURN_END, EndFrameTrapHandler(RunLevel.TURN))
        registry.register(RUNTIME_CYCLE_END, EndFrameTrapHandler(RunLevel.CYCLE))
        registry.register(RUNTIME_PROGRAM_END, EndFrameTrapHandler(RunLevel.PROGRAM))
        registry.register(RUNTIME_STARTUP_FAILED, EndFrameTrapHandler(RunLevel.PROGRAM))
        registry.register(
            CONTEXT_COMPRESSION_REQUIRED,
            ContextPressureTrapHandler(
                ContextPressureRecovery(
                    context=context,
                    workspace=workspace,
                    target_ratio=context.compression_target_ratio,
                )
            ),
        )
        registry.register(HOME_RUNTIME_COPY_REQUIRED, AgentHomeRuntimeCopyTrapHandler(home))
        registry.register(
            WORKSPACE_TRASH_RESTORE_REQUIRED,
            WorkspaceTrashRestoreTrapHandler(workspace=workspace, context=context),
        )
        registry.register_fallback(EndTurnOrProgramTrapHandler())
        return RuntimeTrap(registry=registry)


def _higher_observation_level(
    left: ObservationLevel,
    right: ObservationLevel,
) -> ObservationLevel:
    rank = {
        ObservationLevel.NORMAL: 0,
        ObservationLevel.VERBOSE: 1,
        ObservationLevel.MODEL: 2,
    }
    return left if rank[left] >= rank[right] else right
