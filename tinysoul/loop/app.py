"""TinySoul application assembly entry point."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from tinysoul.action import ActionEngine, ActionEngineBuilder
from tinysoul.action.backends.llm_step import LLMStepActionExecutor
from tinysoul.action.core.call import ActionExecution
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.context import ContextEngine, ContextEngineBuilder
from tinysoul.context.signals import build_working_patch_signal
from tinysoul.context.working import WorkingPatch, WorkspaceResource
from tinysoul.infra.config import ConfigEnvironment, ConfigError
from tinysoul.infra.json import JsonObject
from tinysoul.llm.config import LLMConfigParser
from tinysoul.llm.provider import ProviderError
from tinysoul.llm.provider.factory import build_provider_registry
from tinysoul.llm.task import LLMTaskRunner
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
    RuntimeContextBridge,
    RuntimeInfraBridge,
    RuntimeLLMBridge,
    RuntimeLoopBridge,
)

from .config import LoopSettings, parse_loop_settings
from .cycle import CycleRunner
from .inputs import InputListener, InputRouter
from .phases import LLMRunner, Phase1Unit, Phase2Unit, Phase3Unit
from .program import ProgramOutcome, ProgramRunner
from .prompts import DomainGuidanceProvider, EmptyDomainGuidanceProvider
from .trap_handlers import ContextCompressionTrapHandler, EndFrameTrapHandler
from .turn import TurnOutcome, TurnRunner


@dataclass(frozen=True)
class TinySoulApp:
    """Process-level TinySoul application."""

    program_runner: ProgramRunner
    input_listener: InputListener | None = None

    def run(self) -> ProgramOutcome:
        if self.input_listener is not None:
            self.input_listener.start()
        return self.program_runner.run()

    def run_once(self, user_input: str) -> TurnOutcome:
        return self.program_runner.run_once(user_input)

    def submit_input(self, text: str) -> None:
        self.program_runner.submit_input(text)

    def stop_input_listener(self) -> None:
        if self.input_listener is not None:
            self.input_listener.stop()


class TinySoulAppBuilder:
    """Assemble TinySoul runtime modules into a runnable application."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path.cwd()
        self._settings: LoopSettings | None = None
        self._config_env: ConfigEnvironment | None = None
        self._llm: LLMRunner | None = None
        self._action: ActionEngine | None = None
        self._context: ContextEngine | None = None
        self._bus: SignalBus | None = None
        self._guidance: DomainGuidanceProvider = EmptyDomainGuidanceProvider()

    def with_settings(self, settings: LoopSettings) -> "TinySoulAppBuilder":
        self._settings = settings
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

    def build(self) -> TinySoulApp:
        infra_bridge = RuntimeInfraBridge()
        loop_bridge = RuntimeLoopBridge()
        llm_bridge = RuntimeLLMBridge()
        action_bridge = RuntimeActionBridge()
        context_bridge = RuntimeContextBridge()
        try:
            config = self._config_env or ConfigEnvironment.from_project_root(self._root)
            settings = self._settings or parse_loop_settings(config.section_tree("loop"))
            bus = self._bus or SignalBus()
            llm = self._llm or self._build_llm(config, llm_bridge)
            context = self._context or self._build_context(context_bridge)
            action = self._action or self._build_action(
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
                retry_limit=settings.phase_retry_limit,
            )
            phase2 = Phase2Unit(
                context=context,
                action=action,
                llm=llm,
                bus=bus,
                retry_limit=settings.phase_retry_limit,
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
                settings=settings,
            )
            program_runner = ProgramRunner(
                turn_runner=turn_runner,
                bus=bus,
                trap=trap,
                settings=settings,
            )
            listener = None
            if settings.interactive:
                router = InputRouter(
                    settings=settings,
                    bus=bus,
                    initial_inputs=program_runner.input_queue,
                    is_turn_active=lambda: context.turn_active,
                    scope_provider=lambda: program_runner.scope,
                )
                listener = InputListener(router=router)
            return TinySoulApp(program_runner=program_runner, input_listener=listener)
        except ConfigError as exc:
            raise infra_bridge.from_config_error(exc) from exc
        except ProviderError as exc:
            raise llm_bridge.startup_failure(
                message=str(exc),
                payload={"error_type": type(exc).__name__},
            ) from exc
        except RuntimeException:
            raise
        except Exception as exc:
            raise loop_bridge.startup_failure(
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
        agent_text = agent_path.read_text(encoding="utf-8")
        return (
            ContextEngineBuilder(system_text="You are TinySoul.")
            .add_default_background("home:agent@core", agent_text)
            .build()
        )

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
                .register_native("core.answer", _core_answer)
                .register_native("workspace.scan", _workspace_scan(self._root, bus))
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


def _core_answer(
    execution: ActionExecution,
    context: ActionExecutionContext,
) -> JsonObject:
    text = execution.call.params.get("text", "")
    if not isinstance(text, str):
        text = str(text)
    return {"text": text}


def _workspace_scan(root: Path, bus: SignalBus):
    def execute(
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> JsonObject:
        resources = _scan_workspace_resources(root)
        signal_bus = context.signal_bus or bus
        if resources:
            signal_bus.emit(
                build_working_patch_signal(
                    WorkingPatch(set_resources=resources),
                    call_id=execution.call.call_id,
                    scope=execution.framework.scope,
                    source="loop.workspace_scan",
                )
            )
        return {
            "count": len(resources),
            "resources": [
                {"link": resource.link, "summary": resource.summary}
                for resource in resources
            ],
        }

    return execute


def _scan_workspace_resources(root: Path) -> tuple[WorkspaceResource, ...]:
    skip_dirs = {
        ".agents",
        ".codex",
        ".git",
        ".pytest-local-tmp",
        ".pytest_cache",
        ".test-tmp",
        "__pycache__",
    }
    resources: list[WorkspaceResource] = []
    max_files = 100
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name for name in dirnames if name not in skip_dirs and not name.startswith(".")
        ]
        for filename in sorted(filenames):
            if len(resources) >= max_files:
                return tuple(resources)
            path = Path(dirpath) / filename
            try:
                relative = path.relative_to(root).as_posix()
                size = path.stat().st_size
            except OSError:
                continue
            resources.append(
                WorkspaceResource(
                    link=f"workspace:{relative}",
                    summary=f"{path.suffix or 'file'} file, {size} bytes",
                )
            )
    return tuple(resources)
