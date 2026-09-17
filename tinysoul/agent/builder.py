"""TinySoul application assembly entry point."""

from __future__ import annotations

import asyncio
from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.runtime import RunLevel, RunScope
from collections.abc import Callable, Mapping
from pathlib import Path

from tinysoul.kernel.action import ActionCatalogLoader, ActionEngine
from tinysoul.kernel.action.backends.llm_action import LLMActionBackendOptionsValidator
from tinysoul.kernel.action.core.specs import ActionBackendKind
from tinysoul.kernel.action.config import (
    ActionSettings,
    parse_action_settings,
    validate_llm_action_routes,
)
from tinysoul.plugins.capabilities import CapabilitiesSettings, parse_capabilities_settings
from tinysoul.kernel.context import ContextEngine, ContextSettings, parse_context_settings
from tinysoul.plugins.home import (
    AgentHomeEngine,
    AgentHomeEngineBuilder,
    parse_agent_home_settings,
)
from tinysoul.plugins.home.errors import AgentHomeError
from tinysoul.plugins.memory import MemoryEngine, parse_memory_settings
from tinysoul.plugins.memory.errors import MemoryError
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
from tinysoul.infra.concurrency import AsyncResourceScope, CleanupDiagnostic
from tinysoul.llm.config import LLMConfigParser
from tinysoul.llm.config_types import LLMConfig
from tinysoul.llm.adapter import adapter_specs_json
from tinysoul.llm.provider import ProviderError
from tinysoul.llm.provider.factory import build_provider_registry
from tinysoul.llm.task import LLMTaskRunner
from tinysoul.kernel.loop.config import (
    LoopSettings,
    parse_loop_settings,
    validate_cycle_task_profiles,
)
from tinysoul.kernel.loop.completion import TurnCompletionHandler
from tinysoul.kernel.loop.phases import LLMRunner
from tinysoul.kernel.loop.prompts import DomainSkillProvider
from tinysoul.agent.user import UserTurnBuilder
from tinysoul.plugins.capabilities.assembly import CommonActionAssembly
from tinysoul.infra.clock import BusinessClock
from tinysoul.plugins.reflection import (ReflectionBuilder, ReflectionEngine, ReflectionRuntimeBridge, ReflectionSettings, parse_maintenance_settings)
from tinysoul.runtime import (
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RuntimeException,
    RuntimeHandle,
    RuntimeGenerationError,
    SignalBus,
)
from tinysoul.kernel.action.runtime_bridge import RuntimeActionBridge
from tinysoul.plugins.home.runtime_bridge import RuntimeAgentHomeBridge
from tinysoul.agent.runtime_bridge import RuntimeAgentBridge
from tinysoul.kernel.context.runtime_bridge import RuntimeContextBridge
from tinysoul.llm.runtime_bridge import RuntimeLLMBridge
from tinysoul.kernel.loop.runtime_bridge import RuntimeLoopBridge
from tinysoul.plugins.memory.runtime_bridge import RuntimeMemoryBridge
from tinysoul.plugins.session.runtime_bridge import RuntimeSessionBridge
from tinysoul.plugins.capabilities.script.runtime_bridge import RuntimeScriptBridge
from tinysoul.plugins.capabilities.shell.runtime_bridge import RuntimeShellBridge
from tinysoul.plugins.capabilities.supervised_process.runtime_bridge import RuntimeSupervisedProcessBridge
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge
from tinysoul.plugins.session import SessionEngine, parse_session_settings
from tinysoul.plugins.session.errors import SessionError
from tinysoul.plugins.workspace import (
    WorkspaceEngine,
    WorkspaceEngineBuilder,
    parse_workspace_settings,
)
from tinysoul.plugins.workspace.errors import WorkspaceError

from .config import AgentSettings, parse_agent_settings
from .errors import AgentError, AgentInvariantError
from .ingress import AgentIngress
from .inputs import InputCommandParser, InputDispatcher, InputSource
from .outputs import ObservationRoute, ObservationRouter, OutputSink
from tinysoul.agent.scheduler import RootScheduler
from .assembly import AgentAssembly
from .generation import AgentConfigPlan, AgentRuntimeGeneration
from .day import AgentDayCoordinator
from tinysoul.plugins.archive import DailyLifecycleCoordinator
from tinysoul.infra.clock import IanaBusinessClock
from .runtime_policy import build_agent_trap
from tinysoul.environment.scheduler import ReflectionScheduler


class AgentBuilder:
    """Assemble TinySoul runtime modules into a runnable application."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path.cwd()
        self._loop_settings: LoopSettings | None = None
        self._maintenance_settings: ReflectionSettings | None = None
        self._app_settings: AgentSettings | None = None
        self._config_env: ConfigEnvironment | None = None
        self._llm: LLMRunner | None = None
        self._session: SessionEngine | None = None
        self._memory: MemoryEngine | None = None
        self._business_clock: BusinessClock | None = None
        self._bus: SignalBus | None = None
        self._user_domain_skills: DomainSkillProvider | None = None
        self._input_parser: InputCommandParser | None = None
        self._input_sources: list[InputSource] = []
        self._user_turn_completion_handlers: list[TurnCompletionHandler] = []
        self._output_sinks: list[OutputSink] = []

    def with_loop_settings(self, settings: LoopSettings) -> "AgentBuilder":
        self._loop_settings = settings
        return self

    def with_maintenance_settings(
        self,
        settings: ReflectionSettings,
    ) -> "AgentBuilder":
        self._maintenance_settings = settings
        return self

    def with_agent_settings(self, settings: AgentSettings) -> "AgentBuilder":
        self._app_settings = settings
        return self

    def with_config_environment(
        self,
        config: ConfigEnvironment,
    ) -> "AgentBuilder":
        self._config_env = config
        return self

    def with_llm_runner(self, llm: LLMRunner) -> "AgentBuilder":
        self._llm = llm
        return self

    def with_session_engine(self, session: SessionEngine) -> "AgentBuilder":
        self._session = session
        return self

    def with_memory_engine(self, memory: MemoryEngine) -> "AgentBuilder":
        self._memory = memory
        return self

    def with_business_clock(
        self,
        clock: BusinessClock,
    ) -> "AgentBuilder":
        self._business_clock = clock
        return self

    def with_signal_bus(self, bus: SignalBus) -> "AgentBuilder":
        self._bus = bus
        return self

    def with_user_domain_skills(
        self,
        domain_skills: DomainSkillProvider,
    ) -> "AgentBuilder":
        self._user_domain_skills = domain_skills
        return self

    def with_input_parser(self, parser: InputCommandParser) -> "AgentBuilder":
        self._input_parser = parser
        return self

    def with_input_source(self, source: InputSource) -> "AgentBuilder":
        self._input_sources.append(source)
        return self

    def with_user_turn_completion_handler(
        self,
        handler: TurnCompletionHandler,
    ) -> "AgentBuilder":
        self._user_turn_completion_handlers.append(handler)
        return self

    def with_output_sink(self, sink: OutputSink) -> "AgentBuilder":
        self._output_sinks.append(sink)
        return self

    async def build(self) -> AgentAssembly:
        resources = AsyncResourceScope()
        try:
            return await self._build(resources)
        except BaseException:
            try:
                await resources.close()
            except asyncio.CancelledError:
                pass
            raise

    async def _build(self, resources: AsyncResourceScope) -> AgentAssembly:
        app_bridge = RuntimeAgentBridge()
        llm_bridge = RuntimeLLMBridge()
        maintenance_bridge = ReflectionRuntimeBridge()
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
            observations = ObservationRouter(
                mode=app_settings.output.mode,
                routes=tuple(
                    ObservationRoute(sink=sink, mode=app_settings.output.mode)
                    for sink in self._output_sinks
                ),
            )
            bus = self._bus if self._bus is not None else SignalBus()
            generation = await self._build_generation(
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
            resources.register(
                "generation", lambda: generation_handle.snapshot().generation.close()
            )
            agent_trap = build_agent_trap()
            agent_runner = RootScheduler(
                user_turn=user_turn,
                maintenance=maintenance_engine,
                day=generation.day,
                bus=bus,
                trap=agent_trap,
                retained_outcomes=app_settings.retained_outcomes,
                maintenance_bridge=maintenance_bridge,
                observations=observations,
                generation_handle=generation_handle,
            )
            from tinysoul.agent.commands import AgentCommands

            commands = AgentCommands(agent_runner)
            dispatcher = InputDispatcher(
                parser=parser,
                commands=commands,
                observations=observations,
                agent_scope=agent_runner.scope,
                parser_provider=lambda: generation_handle.snapshot().generation.input_parser,
            )
            gateway = AgentIngress(
                dispatcher=dispatcher,
                bus=bus,
                active_turn_scope=lambda: dispatcher.active_turn_scope,
                agent_scope=agent_runner.scope,
            )
            input_sources = tuple(self._input_sources)

            def current_maintenance_schedule():
                current = generation_handle.snapshot().generation
                return (
                    current.maintenance_settings.schedule,
                    current.maintenance_settings.timezone,
                )

            scheduler = ReflectionScheduler(
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
                activity=lambda: ("queued" if agent_runner.queued_turn_ids else generation_handle.activity.value),
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
            agent_request_sources = (
                (scheduler,)
            )
            return AgentAssembly(
                configuration=config_controller,
                generation_handle=generation_handle,
                commands=commands,
                agent_runner=agent_runner,
                input_dispatcher=dispatcher,
                gateway=gateway,
                input_sources=input_sources,
                agent_request_sources=agent_request_sources,
                observations=observations,
                resources=resources,
            )
        except ConfigCatalogError as exc:
            raise app_bridge.startup_failure(
                message="Project configuration catalog could not be loaded.",
                payload={"error_type": type(exc).__name__},
            ) from exc
        except ConfigError as exc:
            raise self._map_owned_config_error(exc) from exc
        except ProviderError as exc:
            raise llm_bridge.startup_failure(
                message="LLM provider could not be initialized.",
                payload={"error_type": type(exc).__name__},
            ) from exc
        except AgentError as exc:
            raise app_bridge.from_agent_error(exc) from exc
        except RuntimeException:
            raise

    async def _prepare_generation_activation(
        self,
        handle: RuntimeHandle[AgentRuntimeGeneration],
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
            generation = await self._build_generation(
                candidate,
                observations=observations,
                bus=bus,
            )
        except BaseException:
            handle.fail_activation()
            raise

        previous = handle.snapshot().generation

        async def commit() -> None:
            async with handle.write():
                scope = RunScope().push(RunLevel.AGENT, "config_activation")
                transition = await generation.day.preflight(scope=scope)
                operations = JoinedOperations()
                await operations.run(lambda: generation.maintenance.refresh_availability(transition, scope=scope))
                operations.check_cancelled()
                handle.activate(generation)

        async def abort() -> tuple[CleanupDiagnostic, ...]:
            try:
                return await generation.close()
            finally:
                handle.fail_activation()

        async def retire() -> tuple[CleanupDiagnostic, ...]:
            diagnostics: tuple[CleanupDiagnostic, ...] = ()
            if after_commit is not None:
                try:
                    after_commit()
                except Exception as exc:
                    diagnostics = (CleanupDiagnostic("scheduler.refresh", type(exc).__name__),)
            return (*diagnostics, *await previous.close())

        return PreparedConfigActivation(commit=commit, abort=abort, retire=retire)

    async def _build_generation(
        self,
        config: ConfigEnvironment,
        *,
        observations: ObservationEmitter,
        bus: SignalBus,
        map_config_errors: bool = False,
    ) -> AgentRuntimeGeneration:
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
        resources = AsyncResourceScope()
        try:
            llm = self._llm
            if llm is None:
                owned_llm = await self._build_llm(
                    plan.llm,
                    RuntimeLLMBridge(),
                    observations,
                    env=config.runtime_env,
                    context_trigger_ratio=context_settings.compression_trigger_ratio,
                )
                resources.register("llm", owned_llm.close)
                llm = owned_llm
            home = self._build_home(config, RuntimeAgentHomeBridge())
            session = (
                self._session
                if self._session is not None
                else self._build_session(config, RuntimeSessionBridge())
            )
            memory = self._memory
            if memory is None:
                embedding = build_embedding_client(infra_settings.embedding, env=config.runtime_env)
                if embedding is not None:
                    resources.register("embedding", embedding.close)
                memory = self._build_memory(
                    config,
                    RuntimeMemoryBridge(),
                    session_root=session.root,
                    embedding_client=embedding,
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
            if self._user_domain_skills is not None:
                user_builder.with_domain_skills(self._user_domain_skills)
            for handler in self._user_turn_completion_handlers:
                user_builder.add_completion_handler(handler)
            user_turn = user_builder.build()
            archive = DailyLifecycleCoordinator(
                session=session, archive_root=maintenance_settings.archive_root,
                workspace=workspace, memory=memory, observations=observations,
            )
            day = AgentDayCoordinator(
                archive, memory, self._business_clock or IanaBusinessClock(maintenance_settings.timezone),
                active_day=session.active_day,
            )
            reflection = ReflectionBuilder(
                action_assembly=CommonActionAssembly(
                    root=self._root, home=home, workspace=workspace,
                    bus=bus, llm=llm, observations=observations,
                    action_settings=action_settings,
                    capabilities_settings=capabilities_settings,
                    runtime_env=config.runtime_env,
                ),
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
                archive=archive,
                action_catalog=plan.action_catalog,
            ).build()
            surfaces = tuple(profile.action for profile in (user_turn.profile, *reflection.profiles))
            try:
                home.reconcile_prompt_mounts(
                    domains=tuple(sorted({name for action in surfaces for name in action.domain_names()})),
                    actions=tuple(sorted({identity for action in surfaces for identity in action.action_identifiers()})),
                )
            except AgentHomeError as exc:
                raise RuntimeAgentHomeBridge().startup_failure(
                    message="Profile action guidance could not be validated.",
                    payload={"error_type": type(exc).__name__},
                ) from exc
            return AgentRuntimeGeneration(
                config=config,
                plan=plan,
                llm_provider_credentials=plan.llm.provider_credential_statuses(
                    config.runtime_env
                ),
                user_turn=user_turn,
                maintenance=reflection.engine,
                day=day,
                workspace=workspace,
                input_parser=(
                    self._input_parser
                    if self._input_parser is not None
                    else InputCommandParser(app_settings.input_commands)
                ),
                app_settings=app_settings,
                maintenance_settings=maintenance_settings,
                resources=resources,
            )
        except BaseException:
            try:
                await resources.close()
            except asyncio.CancelledError:
                pass
            raise

    def _validate_config_candidate(self, config: ConfigEnvironment) -> None:
        self._compile_config_plan(config)

    def _compile_config_plan(
        self,
        config: ConfigEnvironment,
        *,
        map_runtime_errors: bool = False,
    ) -> AgentConfigPlan:
        try:
            return self._compile_config_plan_values(config)
        except ConfigError as exc:
            if map_runtime_errors:
                raise self._map_owned_config_error(exc) from exc
            raise

    def _compile_config_plan_values(
        self,
        config: ConfigEnvironment,
    ) -> AgentConfigPlan:
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
        plan = AgentConfigPlan(
            environment=config,
            infra=config.parse_section("infra", parse_infra_settings),
            app=(
                self._app_settings
                if self._app_settings is not None
                else config.parse_section("app", parse_agent_settings)
            ),
            action=action_settings,
            action_catalog=action_catalog,
            capabilities=config.parse_section(
                "capabilities", parse_capabilities_settings
            ),
            context=config.parse_section("context", parse_context_settings),
            llm=config.parse_section("llm", LLMConfigParser().parse),
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
            if self._llm is None:
                plan.llm.validate_enabled_provider_credentials(config.runtime_env)
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
            "app": RuntimeAgentBridge(),
            "action": RuntimeActionBridge(),
            "context": RuntimeContextBridge(),
            "home": RuntimeAgentHomeBridge(),
            "llm": RuntimeLLMBridge(),
            "loop": RuntimeLoopBridge(),
            "memory": RuntimeMemoryBridge(),
            "session": RuntimeSessionBridge(),
            "workspace": RuntimeWorkspaceBridge(),
            "maintenance": ReflectionRuntimeBridge(),
        }
        bridge = bridges.get(key, RuntimeAgentBridge())
        return bridge.from_config_error(error)

    async def _build_llm(
        self,
        llm_config: LLMConfig,
        bridge: RuntimeLLMBridge,
        observations: ObservationEmitter,
        *,
        env: Mapping[str, str],
        context_trigger_ratio: float,
    ) -> LLMTaskRunner:
        providers = await build_provider_registry(llm_config.providers, env=env)
        try:
            return LLMTaskRunner(
                models=llm_config.models,
                providers=providers,
                tasks=llm_config.tasks,
                runtime_bridge=bridge,
                observations=observations,
                context_trigger_ratio=context_trigger_ratio,
            )
        except BaseException:
            await providers.close()
            raise

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
        bridge: ReflectionRuntimeBridge,
    ) -> ReflectionSettings:
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
        bridge: RuntimeAgentBridge,
    ) -> AgentSettings:
        try:
            return config.parse_section("app", parse_agent_settings)
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
                message="Home could not be initialized.",
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
                message="Workspace could not be initialized.",
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
                message="Memory could not be initialized.",
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
                message="Session could not be initialized.",
                payload={"error_type": type(exc).__name__},
            ) from exc
