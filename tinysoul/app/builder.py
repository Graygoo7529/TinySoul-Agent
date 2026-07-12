"""TinySoul application assembly entry point."""

from __future__ import annotations

from pathlib import Path

from tinysoul.action import (
    ActionEngine,
    ActionEngineBuilder,
    ActionError,
    parse_action_settings,
)
from tinysoul.action.backends.llm_action import LLMActionTaskRunner
from tinysoul.action.builtins.core import register_core_actions
from tinysoul.context import (
    ContextEngine,
    ContextEngineBuilder,
    parse_context_settings,
)
from tinysoul.context.actions import register_context_actions
from tinysoul.context.errors import ContextError
from tinysoul.home import (
    AgentHomeEngine,
    AgentHomeEngineBuilder,
    AgentHomeRuntimeCopyRecovery,
    AgentHomeRuntimeCopyTrapHandler,
    HomeActionHowProvider,
    HomeBackgroundContentLoader,
    HomeDomainHowProvider,
    parse_agent_home_settings,
    register_home_actions,
)
from tinysoul.home.errors import AgentHomeError
from tinysoul.infra.config import ConfigEnvironment, ConfigError
from tinysoul.llm.config import LLMConfigParser
from tinysoul.llm.provider import ProviderError
from tinysoul.llm.provider.factory import build_provider_registry
from tinysoul.llm.task import LLMTaskRunner
from tinysoul.loop.config import LoopSettings, parse_loop_settings
from tinysoul.loop.completion import TurnCompletionHandler, TurnCompletionPipeline
from tinysoul.loop.context_signals import ContextSignalConsumer
from tinysoul.loop.cycle import CycleRunner
from tinysoul.loop.phases import LLMRunner, Phase1Unit, Phase2Unit, Phase3Unit
from tinysoul.loop.preparation import TurnPreparationPipeline
from tinysoul.loop.pressure import ContextPressureRecovery
from tinysoul.loop.program import ProgramRunner
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
    RuntimeSessionBridge,
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
    WorkspacePromptReferenceResolver,
    WorkspaceTurnPreparationHandler,
    parse_workspace_settings,
    register_workspace_actions,
)
from tinysoul.workspace.errors import WorkspaceError

from .config import AppSettings, parse_app_settings
from .errors import AppError
from .inputs import InputCommandParser, InputDispatcher, InputSource
from .outputs import ConsoleOutputSink, ObservationRouter, OutputSink
from .runtime import TinySoulApp
from .sources import TerminalInputSource


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
        self._bus: SignalBus | None = None
        self._domain_how: DomainHowProvider | None = None
        self._input_parser: InputCommandParser | None = None
        self._input_sources: list[InputSource] = []
        self._turn_completion_handlers: list[TurnCompletionHandler] = []
        self._output_sinks: list[OutputSink] = []

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
                    "action",
                    "context",
                    "home",
                    "session",
                    "workspace",
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
            output_sinks = tuple(self._output_sinks)
            if not output_sinks and app_settings.interactive:
                output_sinks = (
                    ConsoleOutputSink(max_chars=app_settings.output.model_max_chars),
                )
            observations = ObservationRouter(
                mode=app_settings.output.mode,
                sinks=output_sinks,
            )
            bus = self._bus if self._bus is not None else SignalBus()
            llm = (
                self._llm
                if self._llm is not None
                else self._build_llm(config, llm_bridge, observations)
            )
            home = self._build_home(config, home_bridge)
            workspace = self._build_workspace(config, workspace_bridge)
            session = (
                self._session
                if self._session is not None
                else self._build_session(config, session_bridge)
            )
            context = (
                self._context
                if self._context is not None
                else self._build_context(
                    config,
                    home,
                    context_bridge,
                    home_bridge,
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
            action = self._action if self._action is not None else self._build_action(
                config=config,
                bus=bus,
                workspace=workspace,
                context=context,
                session=session,
                home=home,
                home_bridge=home_bridge,
                workspace_bridge=workspace_bridge,
                action_bridge=action_bridge,
                llm_action=llm_action,
                observations=observations,
            )
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
            )
            phase3 = Phase3Unit(
                context=context,
                action=action,
                bus=bus,
                module_runner=module_runner,
                signal_consumer=signal_consumer,
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
            program_runner = ProgramRunner(
                turn_runner=turn_runner,
                bus=bus,
                trap=trap,
                retained_outcomes=app_settings.retained_turn_outcomes,
                observations=observations,
            )
            parser = self._input_parser or InputCommandParser(app_settings.input_commands)
            dispatcher = InputDispatcher(
                parser=parser,
                bus=bus,
                program_inputs=program_runner.input_queue,
                active_turn_scope=lambda: turn_runner.active_scope,
            )
            input_sources = tuple(self._input_sources)
            if not input_sources and app_settings.interactive:
                input_sources = (
                    TerminalInputSource(
                        eof_command=app_settings.input_commands.exit_commands[0],
                    ),
                )
            return TinySoulApp(
                program_runner=program_runner,
                input_dispatcher=dispatcher,
                input_sources=input_sources,
                observations=observations,
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
            return config.parse_section("loop", parse_loop_settings)
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
    ) -> WorkspaceEngine:
        try:
            settings = config.parse_section(
                "workspace",
                lambda tree: parse_workspace_settings(
                    tree,
                    project_root=self._root,
                ),
            )
            return WorkspaceEngineBuilder(settings).build()
        except ConfigError as exc:
            raise bridge.from_config_error(exc) from exc
        except WorkspaceError as exc:
            raise bridge.startup_failure(
                message=str(exc),
                payload={"error_type": type(exc).__name__},
            ) from exc

    def _build_context(
        self,
        config: ConfigEnvironment,
        home: AgentHomeEngine,
        bridge: RuntimeContextBridge,
        home_bridge: RuntimeAgentHomeBridge,
    ) -> ContextEngine:
        try:
            settings = config.parse_section("context", parse_context_settings)
            recovery = AgentHomeRuntimeCopyRecovery.startup(home)
            builder = (
                ContextEngineBuilder(system_text=settings.system_text)
                .with_journal(settings.journal)
                .with_budget_max_chars(settings.budget_max_chars)
                .with_budget_max_image_bytes(settings.budget_max_image_bytes)
                .with_trace_heap(
                    chunk_max_chars=settings.trace_chunk_max_chars,
                    branch_factor=settings.trace_branch_factor,
                    min_hot_entries=settings.trace_min_hot_entries,
                )
                .with_trace_recall_max_chars(settings.trace_recall_max_chars)
                .with_compression_target_ratio(settings.compression_target_ratio)
            )
            for entry in recovery.run(home.default_background_entries):
                builder.add_default_background(entry.link, entry.content)
            for link in home.loadable_background_links():
                builder.add_lazy_background(
                    link,
                    HomeBackgroundContentLoader(
                        home=home,
                        link=link,
                        runtime_bridge=home_bridge,
                    ),
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
        config: ConfigEnvironment,
        bus: SignalBus,
        workspace: WorkspaceEngine,
        context: ContextEngine,
        session: SessionEngine,
        home: AgentHomeEngine,
        home_bridge: RuntimeAgentHomeBridge,
        workspace_bridge: RuntimeWorkspaceBridge,
        action_bridge: RuntimeActionBridge,
        llm_action: LLMActionTaskRunner,
        observations: ObservationEmitter,
    ) -> ActionEngine:
        try:
            settings = config.parse_section(
                "action",
                lambda tree: parse_action_settings(
                    tree,
                    project_root=self._root,
                ),
            )
            builder = ActionEngineBuilder(settings.catalog_root)
            builder.with_observations(observations)
            register_context_actions(builder, context=context)
            register_session_actions(builder, session=session)
            register_workspace_actions(
                builder,
                workspace=workspace,
                bus=bus,
                llm_action=llm_action,
                runtime_bridge=workspace_bridge,
            )
            register_home_actions(
                builder,
                home=home,
                runtime_bridge=home_bridge,
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
