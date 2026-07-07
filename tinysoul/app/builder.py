"""TinySoul application assembly entry point."""

from __future__ import annotations

from pathlib import Path

from tinysoul.action import ActionEngine, ActionEngineBuilder
from tinysoul.action.backends.llm_step import LLMStepActionExecutor
from tinysoul.context import ContextEngine, ContextEngineBuilder
from tinysoul.context.errors import ContextError
from tinysoul.infra.config import ConfigEnvironment, ConfigError
from tinysoul.llm.config import LLMConfigParser
from tinysoul.llm.provider import ProviderError
from tinysoul.llm.provider.factory import build_provider_registry
from tinysoul.llm.task import LLMTaskRunner
from tinysoul.loop.config import LoopSettings, parse_loop_settings
from tinysoul.loop.cycle import CycleRunner
from tinysoul.loop.phases import LLMRunner, Phase1Unit, Phase2Unit, Phase3Unit
from tinysoul.loop.program import ProgramRunner
from tinysoul.loop.prompts import DomainGuidanceProvider, EmptyDomainGuidanceProvider
from tinysoul.loop.trap_handlers import ContextCompressionTrapHandler, EndFrameTrapHandler
from tinysoul.loop.turn import TurnRunner
from tinysoul.runtime import (
    CONTEXT_COMPRESSION_REQUIRED,
    RUNTIME_CYCLE_END,
    RUNTIME_PROGRAM_END,
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RunLevel,
    RuntimeException,
    RuntimeTrap,
    SignalBus,
    TrapHandlerRegistry,
)
from tinysoul.runtime.bridge import (
    RuntimeActionBridge,
    RuntimeAppBridge,
    RuntimeContextBridge,
    RuntimeInfraBridge,
    RuntimeLLMBridge,
)

from .config import AppSettings, parse_app_settings
from .errors import AppError
from .inputs import InputCommandParser, InputDispatcher, InputSource
from .native_actions import core_answer, workspace_scan
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
        self._bus: SignalBus | None = None
        self._guidance: DomainGuidanceProvider = EmptyDomainGuidanceProvider()
        self._input_parser: InputCommandParser | None = None
        self._input_sources: list[InputSource] = []

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

    def with_signal_bus(self, bus: SignalBus) -> "TinySoulAppBuilder":
        self._bus = bus
        return self

    def with_domain_guidance(
        self,
        guidance: DomainGuidanceProvider,
    ) -> "TinySoulAppBuilder":
        self._guidance = guidance
        return self

    def with_input_parser(self, parser: InputCommandParser) -> "TinySoulAppBuilder":
        self._input_parser = parser
        return self

    def with_input_source(self, source: InputSource) -> "TinySoulAppBuilder":
        self._input_sources.append(source)
        return self

    def build(self) -> TinySoulApp:
        app_bridge = RuntimeAppBridge()
        infra_bridge = RuntimeInfraBridge()
        llm_bridge = RuntimeLLMBridge()
        action_bridge = RuntimeActionBridge()
        context_bridge = RuntimeContextBridge()
        try:
            config = (
                self._config_env
                if self._config_env is not None
                else ConfigEnvironment.from_project_root(self._root)
            )
            loop_settings = (
                self._loop_settings
                if self._loop_settings is not None
                else parse_loop_settings(config.section_tree("loop"))
            )
            app_settings = (
                self._app_settings
                if self._app_settings is not None
                else parse_app_settings(config.section_tree("app"))
            )
            bus = self._bus if self._bus is not None else SignalBus()
            llm = self._llm if self._llm is not None else self._build_llm(config, llm_bridge)
            context = (
                self._context
                if self._context is not None
                else self._build_context(context_bridge)
            )
            action = self._action if self._action is not None else self._build_action(
                llm=llm,
                context=context,
                bus=bus,
                action_bridge=action_bridge,
            )
            trap = self._build_trap(context)
            phase1 = Phase1Unit(
                context=context,
                action=action,
                llm=llm,
                bus=bus,
                retry_limit=loop_settings.phase_retry_limit,
            )
            phase2 = Phase2Unit(
                context=context,
                action=action,
                llm=llm,
                bus=bus,
                retry_limit=loop_settings.phase_retry_limit,
                guidance=self._guidance,
            )
            phase3 = Phase3Unit(context=context, action=action, bus=bus)
            cycle_runner = CycleRunner(
                context=context,
                bus=bus,
                trap=trap,
                phase1=phase1,
                phase2=phase2,
                phase3=phase3,
            )
            turn_runner = TurnRunner(
                context=context,
                bus=bus,
                trap=trap,
                cycle_runner=cycle_runner,
                settings=loop_settings,
            )
            program_runner = ProgramRunner(
                turn_runner=turn_runner,
                bus=bus,
                trap=trap,
            )
            parser = self._input_parser or InputCommandParser(app_settings.input_commands)
            dispatcher = InputDispatcher(
                parser=parser,
                bus=bus,
                program_inputs=program_runner.input_queue,
                is_turn_active=lambda: context.turn_active,
                scope_provider=lambda: program_runner.scope,
            )
            input_sources = tuple(self._input_sources)
            if not input_sources and app_settings.interactive:
                input_sources = (TerminalInputSource(),)
            return TinySoulApp(
                program_runner=program_runner,
                input_dispatcher=dispatcher,
                input_sources=input_sources,
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
        except Exception as exc:
            raise app_bridge.startup_failure(
                message=str(exc),
                payload={"error_type": type(exc).__name__},
            ) from exc

    def _build_llm(
        self,
        config: ConfigEnvironment,
        bridge: RuntimeLLMBridge,
    ) -> LLMTaskRunner:
        try:
            llm_config = LLMConfigParser().parse(config.section_tree("llm"))
            providers = build_provider_registry(
                llm_config.providers,
                env=config.runtime_env,
            )
            return LLMTaskRunner(
                models=llm_config.models,
                providers=providers,
                tasks=llm_config.tasks,
                runtime_bridge=bridge,
            )
        except ConfigError:
            raise

    def _build_context(self, bridge: RuntimeContextBridge) -> ContextEngine:
        agent_path = self._root / "AGENT.md"
        if not agent_path.is_file():
            raise bridge.startup_failure(
                message="AGENT.md is missing",
                payload={"path": str(agent_path)},
            )
        try:
            agent_text = agent_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise bridge.startup_failure(
                message=f"Failed to read AGENT.md: {exc}",
                payload={"path": str(agent_path), "error_type": type(exc).__name__},
            ) from exc
        try:
            return (
                ContextEngineBuilder(system_text="You are TinySoul.")
                .add_default_background("home:agent@core", agent_text)
                .build()
            )
        except ContextError as exc:
            raise bridge.startup_failure(
                message=str(exc),
                payload={"error_type": type(exc).__name__},
            ) from exc

    def _build_action(
        self,
        *,
        llm: LLMRunner,
        context: ContextEngine,
        bus: SignalBus,
        action_bridge: RuntimeActionBridge,
    ) -> ActionEngine:
        catalog_root = self._root / "tinysoul" / "action" / "builtin"
        try:
            return (
                ActionEngineBuilder(catalog_root)
                .register_native("core.answer", core_answer)
                .register_native("workspace.scan", workspace_scan(self._root, bus))
                .register_executor(
                    "llm_step.context_task",
                    LLMStepActionExecutor(llm_runner=llm, context=context),
                )
                .build()
            )
        except ConfigError:
            raise
        except Exception as exc:
            raise action_bridge.startup_failure(
                message=str(exc),
                payload={"error_type": type(exc).__name__},
            ) from exc

    def _build_trap(self, context: ContextEngine) -> RuntimeTrap:
        registry = TrapHandlerRegistry()
        registry.register(RUNTIME_TURN_END, EndFrameTrapHandler(RunLevel.TURN))
        registry.register(RUNTIME_CYCLE_END, EndFrameTrapHandler(RunLevel.CYCLE))
        registry.register(RUNTIME_PROGRAM_END, EndFrameTrapHandler(RunLevel.PROGRAM))
        registry.register(RUNTIME_STARTUP_FAILED, EndFrameTrapHandler(RunLevel.PROGRAM))
        registry.register(CONTEXT_COMPRESSION_REQUIRED, ContextCompressionTrapHandler(context))
        return RuntimeTrap(registry=registry)
