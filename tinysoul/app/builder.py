"""TinySoul application assembly entry point."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tinysoul.action import ActionCatalogLoader, ActionEngine
from tinysoul.action.backends.llm_action import LLMActionBackendOptionsValidator
from tinysoul.action.core.specs import ActionBackendKind
from tinysoul.action.config import (
    ActionSettings,
    parse_action_settings,
    validate_llm_action_routes,
)
from tinysoul.capabilities import CapabilitiesSettings, parse_capabilities_settings
from tinysoul.capabilities.supervised_process import (
    compile_supervised_process_wait_policy,
)
from tinysoul.context import ContextEngine, ContextSettings, parse_context_settings
from tinysoul.endpoint import (
    EndpointEngine,
    EndpointEventBuffer,
    EndpointEventJournal,
    EndpointHost,
    EndpointReady,
    EndpointSettings,
)
from tinysoul.home import (
    AgentHomeEngine,
    AgentHomeEngineBuilder,
    parse_agent_home_settings,
)
from tinysoul.home.errors import AgentHomeError
from tinysoul.memory import MemoryEngine, parse_memory_settings
from tinysoul.memory.errors import MemoryError
from tinysoul.infra.config import (
    ConfigController,
    ConfigCatalogError,
    ConfigEnvironment,
    ConfigError,
    load_config_catalog,
    PreparedConfigActivation,
)
from tinysoul.infra import (
    EmbeddingClient,
    build_embedding_client,
    parse_infra_settings,
)
from tinysoul.llm.config import LLMConfigParser
from tinysoul.llm.adapter import adapter_specs_json
from tinysoul.llm.provider import ProviderError
from tinysoul.llm.provider.factory import build_provider_registry
from tinysoul.llm.task import LLMTaskRunner
from tinysoul.loop.config import (
    LoopSettings,
    parse_loop_settings,
    validate_cycle_task_profiles,
)
from tinysoul.loop.completion import TurnCompletionHandler
from tinysoul.loop.phases import LLMRunner
from tinysoul.loop.prompts import DomainSkillProvider
from tinysoul.loop.user import UserTurnBuilder
from tinysoul.maintenance import (
    BusinessClock,
    MaintenanceBuilder,
    MaintenanceEngine,
    MaintenanceRuntimeBridge,
    MaintenanceSettings,
    parse_maintenance_settings,
)
from tinysoul.runtime import (
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RuntimeException,
    RuntimeHandle,
    RuntimeGenerationError,
    SignalBus,
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
from tinysoul.session.errors import SessionError
from tinysoul.workspace import (
    WorkspaceEngine,
    WorkspaceEngineBuilder,
    parse_workspace_settings,
)
from tinysoul.workspace.errors import WorkspaceError

from .config import AppSettings, parse_app_settings
from .errors import AppError, AppInvariantError
from .gateway import AppCommandGateway
from .inputs import InputCommandParser, InputDispatcher, InputSource
from .outputs import ConsoleOutputSink, ObservationRoute, ObservationRouter, OutputSink
from .program import ProgramRunner
from .runtime import TinySoulApp
from .generation import AppConfigPlan, AppRuntimeGeneration
from .runtime_policy import build_program_trap
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
        self._user_action: ActionEngine | None = None
        self._user_context: ContextEngine | None = None
        self._session: SessionEngine | None = None
        self._memory: MemoryEngine | None = None
        self._business_clock: BusinessClock | None = None
        self._bus: SignalBus | None = None
        self._user_domain_skills: DomainSkillProvider | None = None
        self._input_parser: InputCommandParser | None = None
        self._input_sources: list[InputSource] = []
        self._user_turn_completion_handlers: list[TurnCompletionHandler] = []
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

    def with_user_action_engine(self, action: ActionEngine) -> "TinySoulAppBuilder":
        self._user_action = action
        return self

    def with_user_context_engine(self, context: ContextEngine) -> "TinySoulAppBuilder":
        self._user_context = context
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

    def with_user_domain_skills(
        self,
        domain_skills: DomainSkillProvider,
    ) -> "TinySoulAppBuilder":
        self._user_domain_skills = domain_skills
        return self

    def with_input_parser(self, parser: InputCommandParser) -> "TinySoulAppBuilder":
        self._input_parser = parser
        return self

    def with_input_source(self, source: InputSource) -> "TinySoulAppBuilder":
        self._input_sources.append(source)
        return self

    def with_user_turn_completion_handler(
        self,
        handler: TurnCompletionHandler,
    ) -> "TinySoulAppBuilder":
        self._user_turn_completion_handlers.append(handler)
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
        maintenance_bridge = MaintenanceRuntimeBridge()
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
                    "action",
                    "loop",
                    "llm",
                    "context",
                    "home",
                    "memory",
                    "infra",
                    "maintenance",
                    "session",
                    "workspace",
                    "capabilities",
                }
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
                journal = None
                if self._endpoint_settings.journal_enabled:
                    journal_root = (
                        self._endpoint_settings.journal_root
                        or (self._root / "runtime" / "endpoint" / "events")
                    )
                    journal = EndpointEventJournal(
                        journal_root,
                        max_segment_bytes=(
                            self._endpoint_settings.journal_segment_bytes
                        ),
                        max_total_bytes=self._endpoint_settings.journal_total_bytes,
                    )
                endpoint_events = EndpointEventBuffer(
                    capacity=self._endpoint_settings.event_capacity,
                    max_bytes=self._endpoint_settings.event_bytes,
                    page_bytes=self._endpoint_settings.event_page_bytes,
                    journal=journal,
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
            generation = self._build_generation(
                config,
                observations=observations,
                bus=bus,
                map_config_errors=True,
            )
            user_turn = generation.user_turn
            maintenance_engine = generation.maintenance
            workspace = generation.workspace
            parser = generation.input_parser
            generation_handle = RuntimeHandle(generation)
            program_trap = build_program_trap()
            program_runner = ProgramRunner(
                user_turn=user_turn,
                maintenance=maintenance_engine,
                bus=bus,
                trap=program_trap,
                retained_outcomes=app_settings.retained_outcomes,
                maintenance_bridge=maintenance_bridge,
                observations=observations,
                generation_handle=generation_handle,
            )
            dispatcher = InputDispatcher(
                parser=parser,
                bus=bus,
                program_inputs=program_runner.input_queue,
                active_turn_scope=lambda: generation_handle.snapshot().generation.user_turn.active_scope,
                observations=observations,
                program_scope=program_runner.scope,
                request_turn_cancel=lambda kind: generation_handle.snapshot().generation.user_turn.request_cancel(kind),
                parser_provider=lambda: generation_handle.snapshot().generation.input_parser,
            )
            gateway = AppCommandGateway(
                dispatcher=dispatcher,
                bus=bus,
                active_turn_scope=lambda: generation_handle.snapshot().generation.user_turn.active_scope,
                program_scope=program_runner.scope,
            )
            endpoint: EndpointEngine | None = None
            services = ()
            input_sources = tuple(self._input_sources)

            def current_maintenance_schedule():
                current = generation_handle.snapshot().generation
                return (
                    current.maintenance_settings.schedule,
                    current.maintenance_settings.timezone,
                )

            scheduler = MaintenanceScheduler(
                maintenance_settings.schedule,
                timezone=maintenance_settings.timezone,
                settings_provider=current_maintenance_schedule,
            )
            config_controller = ConfigController(
                root=self._root,
                environment=config,
                validator=self._validate_config_candidate,
                activator=lambda candidate: self._prepare_generation_activation(
                    generation_handle,
                    candidate,
                    observations=observations,
                    bus=bus,
                    after_commit=scheduler.refresh,
                ),
                activity=lambda: generation_handle.activity.value,
                generation_id=lambda: generation_handle.generation_id,
                activation_observer=lambda state, payload: observations.emit(
                    ObservationEvent(
                        name=f"config.activation.{state}",
                        level=ObservationLevel.NORMAL,
                        source="app.config",
                        message=f"Configuration activation {state}.",
                        payload=payload,
                    )
                ),
                catalog=load_config_catalog().with_rules(
                    {"llm": {"adapters": adapter_specs_json()}}
                ),
            )
            if self._endpoint_settings is not None:
                if endpoint_events is None:
                    raise AppInvariantError("Endpoint event buffer was not assembled")
                endpoint = EndpointEngine(
                    settings=self._endpoint_settings,
                    events=endpoint_events,
                    gateway=gateway,
                    workspace=workspace,
                    maintenance=maintenance_engine,
                    config=config_controller,
                    runtime_handle=generation_handle,
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
                (scheduler,)
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
        except ConfigCatalogError as exc:
            raise infra_bridge.startup_failure(
                message=str(exc),
                payload={"error_type": type(exc).__name__},
            ) from exc
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

    def _prepare_generation_activation(
        self,
        handle: RuntimeHandle[AppRuntimeGeneration],
        candidate: ConfigEnvironment,
        *,
        observations: ObservationEmitter,
        bus: SignalBus,
        after_commit: Callable[[], None] | None = None,
    ) -> PreparedConfigActivation:
        try:
            handle.begin_activation()
        except RuntimeGenerationError as exc:
            raise ConfigError(
                "Configuration changes require an idle runtime",
                key="config.activation_unavailable",
            ) from exc
        try:
            generation = self._build_generation(
                candidate,
                observations=observations,
                bus=bus,
            )
        except BaseException:
            handle.fail_activation()
            raise

        def commit() -> None:
            previous = handle.snapshot().generation
            with handle.write():
                handle.activate(generation)
            previous.close()
            if after_commit is not None:
                after_commit()

        return PreparedConfigActivation(commit=commit, abort=handle.fail_activation)

    def _build_generation(
        self,
        config: ConfigEnvironment,
        *,
        observations: ObservationEmitter,
        bus: SignalBus,
        map_config_errors: bool = False,
    ) -> AppRuntimeGeneration:
        """Compile module settings and construct one complete business generation."""

        plan = self._compile_config_plan(
            config,
            map_runtime_errors=map_config_errors,
        )
        infra_settings = plan.infra
        loop_settings = plan.loop
        maintenance_settings = plan.maintenance
        context_settings = plan.context
        action_settings = plan.action
        capabilities_settings = plan.capabilities
        app_settings = plan.app
        llm = (
            self._llm
            if self._llm is not None
            else self._build_llm(
                config,
                RuntimeLLMBridge(),
                observations,
                context_trigger_ratio=context_settings.compression_trigger_ratio,
            )
        )
        home = self._build_home(config, RuntimeAgentHomeBridge())
        session = (
            self._session
            if self._session is not None
            else self._build_session(config, RuntimeSessionBridge())
        )
        memory = self._memory
        if memory is None:
            memory = self._build_memory(
                config,
                RuntimeMemoryBridge(),
                session_root=session.root,
                embedding_client=build_embedding_client(
                    infra_settings.embedding,
                    env=config.runtime_env,
                ),
            )
        if memory.active_session_root is None:
            memory.bind_active_session_root(session.root)
        workspace = self._build_workspace(
            config,
            RuntimeWorkspaceBridge(),
            observations,
        )
        user_builder = UserTurnBuilder(
            root=self._root,
            context_settings=context_settings,
            loop_settings=loop_settings,
            capabilities_settings=capabilities_settings,
            supervised_process_wait=plan.supervised_process_wait,
            runtime_env=config.runtime_env,
            llm=llm,
            home=home,
            memory=memory,
            session=session,
            workspace=workspace,
            bus=bus,
            observations=observations,
            action_settings=action_settings,
            action_catalog=plan.action_catalog,
        )
        if self._user_context is not None:
            user_builder.with_context(self._user_context)
        if self._user_action is not None:
            user_builder.with_action(self._user_action)
        if self._user_domain_skills is not None:
            user_builder.with_domain_skills(self._user_domain_skills)
        for handler in self._user_turn_completion_handlers:
            user_builder.add_completion_handler(handler)
        user_turn = user_builder.build()
        maintenance = MaintenanceBuilder(
            context_settings=context_settings,
            loop_settings=loop_settings,
            settings=maintenance_settings,
            llm=llm,
            home=home,
            memory=memory,
            session=session,
            workspace=workspace,
            bus=bus,
            observations=observations,
            clock=self._business_clock,
            action_catalog=plan.action_catalog,
        ).build()
        return AppRuntimeGeneration(
            config=config,
            plan=plan,
            user_turn=user_turn,
            maintenance=maintenance,
            workspace=workspace,
            input_parser=(
                self._input_parser
                if self._input_parser is not None
                else InputCommandParser(app_settings.input_commands)
            ),
            app_settings=app_settings,
            maintenance_settings=maintenance_settings,
        )

    def _validate_config_candidate(self, config: ConfigEnvironment) -> None:
        self._compile_config_plan(config)

    def _compile_config_plan(
        self,
        config: ConfigEnvironment,
        *,
        map_runtime_errors: bool = False,
    ) -> AppConfigPlan:
        try:
            return self._compile_config_plan_values(config)
        except ConfigError as exc:
            if map_runtime_errors:
                raise self._map_owned_config_error(exc) from exc
            raise

    def _compile_config_plan_values(
        self,
        config: ConfigEnvironment,
    ) -> AppConfigPlan:
        config.validate_sections(
            {
                "config",
                "app",
                "action",
                "loop",
                "llm",
                "context",
                "home",
                "memory",
                "infra",
                "maintenance",
                "session",
                "workspace",
                "capabilities",
            }
        )
        action_settings = config.parse_section("action", parse_action_settings)
        action_catalog = ActionCatalogLoader(
            backend_kind_options_validators={
                ActionBackendKind.LLM_ACTION: LLMActionBackendOptionsValidator(),
            },
            llm_action_timeout_seconds=action_settings.llm_action.timeout_seconds,
        ).load_documents(config.document_set("action.catalog"))
        supervised_process_wait = compile_supervised_process_wait_policy(
            action_catalog
        )
        plan = AppConfigPlan(
            environment=config,
            infra=config.parse_section("infra", parse_infra_settings),
            app=(
                self._app_settings
                if self._app_settings is not None
                else config.parse_section("app", parse_app_settings)
            ),
            action=action_settings,
            action_catalog=action_catalog,
            capabilities=config.parse_section(
                "capabilities", parse_capabilities_settings
            ),
            supervised_process_wait=supervised_process_wait,
            context=config.parse_section("context", parse_context_settings),
            llm=config.parse_section(
                "llm",
                lambda tree: LLMConfigParser().parse(
                    tree,
                    require_enabled_providers=self._llm is None,
                ),
            ),
            loop=(
                self._loop_settings
                if self._loop_settings is not None
                else config.parse_section("loop", parse_loop_settings)
            ),
            maintenance=(
                self._maintenance_settings
                if self._maintenance_settings is not None
                else config.parse_section(
                    "maintenance",
                    lambda tree: parse_maintenance_settings(
                        tree,
                        project_root=self._root,
                    ),
                )
            ),
            home=config.parse_section(
                "home",
                lambda tree: parse_agent_home_settings(
                    tree,
                    project_root=self._root,
                ),
            ),
            memory=config.parse_section(
                "memory",
                lambda tree: parse_memory_settings(
                    tree,
                    project_root=self._root,
                ),
            ),
            session=config.parse_section(
                "session",
                lambda tree: parse_session_settings(
                    tree,
                    project_root=self._root,
                ),
            ),
            workspace=config.parse_section(
                "workspace",
                lambda tree: parse_workspace_settings(
                    tree,
                    project_root=self._root,
                ),
            ),
        )
        try:
            validate_cycle_task_profiles(
                plan.loop.cycle,
                task_profiles=plan.llm.tasks.profiles(),
            )
            validate_llm_action_routes(
                plan.action.llm_action,
                catalog=plan.action_catalog.catalog,
                task_profiles=plan.llm.tasks.profiles(),
            )
        except ConfigError as exc:
            enriched = config.enrich_error(exc)
            if enriched is exc:
                raise
            raise enriched from exc
        return plan

    @staticmethod
    def _map_owned_config_error(error: ConfigError) -> RuntimeException:
        key = error.key.split(".", 1)[0] if error.key else "infra"
        if error.source.startswith("project-document:action.catalog:"):
            return RuntimeActionBridge().from_config_error(error)
        if error.key == "capabilities.script" or error.key.startswith(
            "capabilities.script."
        ):
            return RuntimeScriptBridge().from_config_error(error)
        if error.key == "capabilities.shell" or error.key.startswith(
            "capabilities.shell."
        ):
            return RuntimeShellBridge().from_config_error(error)
        if error.key == "capabilities.supervised_process" or error.key.startswith(
            "capabilities.supervised_process."
        ):
            return RuntimeSupervisedProcessBridge().from_config_error(error)
        bridges = {
            "app": RuntimeAppBridge(),
            "action": RuntimeActionBridge(),
            "context": RuntimeContextBridge(),
            "home": RuntimeAgentHomeBridge(),
            "llm": RuntimeLLMBridge(),
            "loop": RuntimeLoopBridge(),
            "memory": RuntimeMemoryBridge(),
            "session": RuntimeSessionBridge(),
            "workspace": RuntimeWorkspaceBridge(),
            "maintenance": MaintenanceRuntimeBridge(),
            "infra": RuntimeInfraBridge(),
        }
        bridge = bridges.get(key, RuntimeInfraBridge())
        return bridge.from_config_error(error)

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

    def _build_action_settings(
        self,
        config: ConfigEnvironment,
        bridge: RuntimeActionBridge,
    ) -> ActionSettings:
        try:
            return config.parse_section("action", parse_action_settings)
        except ConfigError as exc:
            raise bridge.from_config_error(exc) from exc

    def _build_maintenance_settings(
        self,
        config: ConfigEnvironment,
        bridge: MaintenanceRuntimeBridge,
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
        *,
        session_root: Path,
        embedding_client: EmbeddingClient | None,
    ) -> MemoryEngine:
        try:
            settings = config.parse_section(
                "memory",
                lambda tree: parse_memory_settings(tree, project_root=self._root),
            )
            return MemoryEngine(
                settings=settings,
                active_session_root=session_root,
                embedding_client=embedding_client,
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
