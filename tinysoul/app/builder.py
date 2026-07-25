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
    AgentHomeEngine,
    AgentHomeEngineBuilder,
    AgentHomeRuntimeCopyTrapHandler,
    HomeActionHowProvider,
    HomeBackgroundEntryProvider,
    HomeDomainHowProvider,
    LLMHomeMaintenanceReviewer,
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
from tinysoul.loop.day import BusinessClock, IanaBusinessClock
from tinysoul.loop.daily import DailyLifecycleCoordinator
from tinysoul.loop.completion import TurnCompletionHandler, TurnCompletionPipeline
from tinysoul.loop.context_signals import ContextSignalConsumer
from tinysoul.loop.cycle import CycleRunner
from tinysoul.loop.phases import LLMRunner, Phase1Unit, Phase2Unit, Phase3Unit
from tinysoul.loop.preparation import TurnPreparationPipeline
from tinysoul.loop.pressure import ContextPressureRecovery
from tinysoul.loop.program import ProgramRunner
from tinysoul.loop.maintenance import ProgramMaintenanceRunner
from tinysoul.loop.prompts import DomainHowProvider
from tinysoul.loop.trap_handlers import (
    ContextPressureTrapHandler,
    EndFrameTrapHandler,
    EndTurnOrProgramTrapHandler,
    TurnOutputTrapHandler,
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
    RUNTIME_TURN_OUTPUT,
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
    RuntimeMemoryBridge,
    RuntimeSessionBridge,
    RuntimeScriptBridge,
    RuntimeShellBridge,
    RuntimeSupervisedProcessBridge,
    RuntimeWorkspaceBridge,
)
from tinysoul.session import SessionEngine, parse_session_settings
from tinysoul.session.actions import register_session_actions
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
from .maintenance import HomeDecisionBroker
from .outputs import ConsoleOutputSink, ObservationRoute, ObservationRouter, OutputSink
from .runtime import TinySoulApp
from .sources import MaintenanceScheduler, TerminalInputSource


class TinySoulAppBuilder:
    """Assemble TinySoul runtime modules into a runnable application."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path.cwd()
        self._loop_settings: LoopSettings | None = None
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
            home = self._build_home(config, home_bridge, observations)
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
            try:
                home.reconcile_prompt_mounts(
                    domains=action.domain_names(),
                    actions=action.action_identifiers(),
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
                action=action,
                llm=llm,
                bus=bus,
                retry_limit=loop_settings.phase_retry_limit,
                signal_consumer=signal_consumer,
            )
            phase2 = Phase2Unit(
                context=context,
                action=action,
                llm=llm,
                bus=bus,
                retry_limit=loop_settings.phase_retry_limit,
                domain_how=domain_how,
                signal_consumer=signal_consumer,
                observations=observations,
            )
            phase3 = Phase3Unit(
                context=context,
                action=action,
                bus=bus,
                module_runner=module_runner,
                signal_consumer=signal_consumer,
                observations=observations,
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
            turn_runner = TurnRunner(
                context=context,
                bus=bus,
                trap=trap,
                cycle_runner=cycle_runner,
                settings=loop_settings,
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
                archive_root=loop_settings.daily.archive_root,
                session=session,
                workspace=workspace,
                observations=observations,
            )
            decision_broker = HomeDecisionBroker(
                observations=observations,
            )
            maintenance_runner = ProgramMaintenanceRunner(
                home=home,
                memory=memory,
                session=session,
                daily_lifecycle=daily_lifecycle,
                timezone=loop_settings.daily.timezone,
                automatic_home_reviewer=LLMHomeMaintenanceReviewer(llm),
                memory_consolidator=LLMMemoryConsolidator(llm),
                manual_home_decisions=decision_broker,
            )
            program_runner = ProgramRunner(
                turn_runner=turn_runner,
                bus=bus,
                trap=trap,
                daily_lifecycle=daily_lifecycle,
                maintenance_runner=maintenance_runner,
                retained_outcomes=app_settings.retained_turn_outcomes,
                business_clock=(
                    self._business_clock
                    or IanaBusinessClock(loop_settings.daily.timezone)
                ),
                loop_bridge=loop_bridge,
                observations=observations,
            )
            parser = self._input_parser or InputCommandParser(app_settings.input_commands)
            dispatcher = InputDispatcher(
                parser=parser,
                bus=bus,
                program_inputs=program_runner.input_queue,
                active_turn_scope=lambda: turn_runner.active_scope,
                observations=observations,
                program_scope=program_runner.scope,
            )
            gateway = AppCommandGateway(
                dispatcher=dispatcher,
                decisions=decision_broker,
                bus=bus,
                active_turn_scope=lambda: turn_runner.active_scope,
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
                    daily_lifecycle=daily_lifecycle,
                    maintenance=maintenance_runner,
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
            program_event_sources = (
                (
                    MaintenanceScheduler(
                        app_settings.scheduler,
                        timezone=loop_settings.daily.timezone,
                    ),
                )
                if app_settings.scheduler.enabled
                else ()
            )
            return TinySoulApp(
                program_runner=program_runner,
                input_dispatcher=dispatcher,
                gateway=gateway,
                input_sources=input_sources,
                program_event_sources=program_event_sources,
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
                lambda tree: parse_loop_settings(tree, project_root=self._root),
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
        observations: ObservationEmitter,
    ) -> AgentHomeEngine:
        try:
            settings = config.parse_section(
                "home",
                lambda tree: parse_agent_home_settings(
                    tree,
                    project_root=self._root,
                ),
            )
            home = AgentHomeEngineBuilder(
                settings,
                observations=observations,
            ).build()
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

    def _build_trap(
        self,
        context: ContextEngine,
        home: AgentHomeEngine,
        workspace: WorkspaceEngine,
    ) -> RuntimeTrap:
        registry = TrapHandlerRegistry()
        registry.register(RUNTIME_TURN_END, EndFrameTrapHandler(RunLevel.TURN))
        registry.register(RUNTIME_TURN_OUTPUT, TurnOutputTrapHandler())
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
