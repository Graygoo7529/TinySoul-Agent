"""TinySoul application assembly entry point."""

from __future__ import annotations

import asyncio
from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.runtime import RunLevel, RunScope
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

from tinysoul.kernel.action import ActionCatalogLoader, ActionEngine
from tinysoul.kernel.action.backends.llm_action import LLMActionBackendOptionsValidator
from tinysoul.kernel.action.catalog.specs import ActionBackendKind
from tinysoul.kernel.action.config import (
    ActionSettings,
    parse_action_settings,
    validate_llm_action_routes,
)
from tinysoul.plugins.capabilities import (
    CapabilitiesSettings,
    parse_capabilities_settings,
)
from tinysoul.plugins.execution import parse_execution_settings
from tinysoul.kernel.jobs.config import parse_job_settings
from tinysoul.kernel.context import (
    ContextEngine,
    ContextSettings,
    parse_context_settings,
)
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
from tinysoul.infra import EmbeddingClient, build_embedding_client, parse_infra_settings
from tinysoul.infra.concurrency import AsyncResourceScope, CleanupDiagnostic
from tinysoul.llm.config.loader import LLMConfigParser
from tinysoul.llm.config.types import LLMConfig
from tinysoul.llm.protocol.adapter import adapter_specs_json
from tinysoul.llm.provider import ProviderError
from tinysoul.llm.provider.factory import build_provider_registry
from tinysoul.llm.execution.task import LLMTaskRunner
from tinysoul.kernel.loop.config import (
    LoopSettings,
    parse_loop_settings,
    validate_cycle_task_profiles,
)
from tinysoul.kernel.loop.lifecycle.completion import TurnCompletionHandler
from tinysoul.kernel.loop.phases import LLMRunner
from tinysoul.kernel.loop.prompts import DomainSkillProvider
from tinysoul.agent.user import UserTurnBuilder
from .actions import CommonActionAssembly
from tinysoul.infra.clock import CalendarClock
from tinysoul.plugins.reflection import (
    ReflectionBuilder,
    ReflectionEngine,
    ReflectionRuntimeBridge,
    ReflectionSettings,
    ReflectionRequest,
    parse_reflection_settings,
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
from tinysoul.kernel.action.runtime_bridge import RuntimeActionBridge
from tinysoul.plugins.home.runtime_bridge import RuntimeAgentHomeBridge
from tinysoul.agent.runtime_bridge import RuntimeAgentBridge
from tinysoul.kernel.context.runtime_bridge import RuntimeContextBridge
from tinysoul.llm.runtime_bridge import RuntimeLLMBridge
from tinysoul.kernel.loop.runtime_bridge import RuntimeLoopBridge
from tinysoul.plugins.memory.runtime_bridge import RuntimeMemoryBridge
from tinysoul.plugins.session.runtime_bridge import RuntimeSessionBridge
from tinysoul.plugins.execution.runtime_bridge import RuntimeExecutionBridge
from tinysoul.kernel.jobs.runtime_bridge import RuntimeJobsBridge
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge
from tinysoul.plugins.session import SessionEngine, parse_session_settings
from tinysoul.plugins.session.errors import SessionError
from tinysoul.plugins.workspace import (
    WorkspaceEngine,
    WorkspaceEngineBuilder,
    parse_workspace_settings,
)
from tinysoul.plugins.workspace.errors import WorkspaceError

from ..config import AgentSettings, parse_agent_settings
from ..errors import AgentError, AgentInvariantError, AgentClosedError, AgentQueueFullError
from ..dispatch.ingress import AgentIngress
from ..dispatch.inputs import InputCommandParser, InputDispatcher, InputSource
from ..observation.outputs import ObservationRoute, ObservationRouter, OutputSink
from tinysoul.agent.dispatch.scheduler import RootScheduler
from .assembly import AgentAssembly
from ..lifecycle.generation import AgentConfigPlan, AgentRuntimeGeneration
from ..lifecycle.day import AgentDayCoordinator
from tinysoul.plugins.archive import DailyLifecycleCoordinator
from tinysoul.infra.clock import IanaCalendarClock
from ..lifecycle.runtime_policy import build_agent_trap
from tinysoul.environment.sources.scheduler import DeadlineTimer
from tinysoul.plugins.reflection.schedule import ReflectionScheduler
from tinysoul.kernel.registration import PluginDeclaration
from tinysoul.environment.sources.fswatch import FileWatcher
from tinysoul.plugins.workspace.events import WorkspaceRuntime
from ..lifecycle.sources import GenerationSources


class AgentBuilder:
    """Assemble TinySoul runtime modules into a runnable application."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path.cwd()
        self._loop_settings: LoopSettings | None = None
        self._reflection_settings: ReflectionSettings | None = None
        self._agent_settings: AgentSettings | None = None
        self._config_env: ConfigEnvironment | None = None
        self._llm: LLMRunner | None = None
        self._session: SessionEngine | None = None
        self._memory: MemoryEngine | None = None
        self._calendar_clock: CalendarClock | None = None
        self._bus: SignalBus | None = None
        self._user_domain_skills: DomainSkillProvider | None = None
        self._input_parser: InputCommandParser | None = None
        self._input_sources: list[InputSource] = []
        self._user_turn_completion_handlers: list[TurnCompletionHandler] = []
        self._output_sinks: list[OutputSink] = []

    def with_loop_settings(self, settings: LoopSettings) -> "AgentBuilder":
        self._loop_settings = settings
        return self

    def with_reflection_settings(
        self,
        settings: ReflectionSettings,
    ) -> "AgentBuilder":
        self._reflection_settings = settings
        return self

    def with_agent_settings(self, settings: AgentSettings) -> "AgentBuilder":
        self._agent_settings = settings
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

    def with_calendar_clock(
        self,
        clock: CalendarClock,
    ) -> "AgentBuilder":
        self._calendar_clock = clock
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
        agent_bridge = RuntimeAgentBridge()
        llm_bridge = RuntimeLLMBridge()
        reflection_bridge = ReflectionRuntimeBridge()
        try:
            config = (
                self._config_env
                if self._config_env is not None
                else ConfigEnvironment.from_project_root(self._root)
            )
            config.validate_sections(
                {
                    "config",
                    "agent",
                    "action",
                    "loop",
                    "llm",
                    "context",
                    "home",
                    "memory",
                    "infra",
                    "reflection",
                    "session",
                    "workspace",
                    "capabilities",
                    "execution",
                    "jobs",
                }
            )
            reflection_settings = (
                self._reflection_settings
                if self._reflection_settings is not None
                else self._build_reflection_settings(config, reflection_bridge)
            )
            agent_settings = (
                self._agent_settings
                if self._agent_settings is not None
                else self._build_agent_settings(config, agent_bridge)
            )
            observations = ObservationRouter(
                mode=agent_settings.output.mode,
                routes=tuple(
                    ObservationRoute(sink=sink, mode=agent_settings.output.mode)
                    for sink in self._output_sinks
                ),
            )
            bus = self._bus if self._bus is not None else SignalBus()

            async def submit_reflection(request: ReflectionRequest) -> bool:
                try:
                    await commands.request_reflection(request)
                except (AgentClosedError, AgentQueueFullError):
                    return False
                return True

            generation = await self._build_generation(
                config,
                submit_reflection=submit_reflection,
                observations=observations,
                bus=bus,
                map_config_errors=True,
            )
            user_turn = generation.user_turn
            reflection_engine = generation.reflection
            workspace = generation.workspace
            parser = generation.input_parser
            generation_handle = RuntimeHandle(generation)
            resources.register(
                "generation", lambda: generation_handle.snapshot().generation.close()
            )
            agent_trap = build_agent_trap()
            agent_runner = RootScheduler(
                user_turn=user_turn,
                reflection=reflection_engine,
                day=generation.day,
                bus=bus,
                trap=agent_trap,
                retained_outcomes=agent_settings.retained_outcomes,
                reflection_bridge=reflection_bridge,
                observations=observations,
                generation_handle=generation_handle,
            )
            from tinysoul.agent.commands import AgentCommands

            commands = AgentCommands(agent_runner,
                source_statuses=lambda: generation_handle.snapshot().generation.sources.statuses)
            dispatcher = InputDispatcher(
                parser=parser,
                commands=commands,
                observations=observations,
                agent_scope=agent_runner.scope,
                parser_provider=lambda: generation_handle.snapshot().generation.input_parser,
            )
            gateway = AgentIngress(
                dispatcher=dispatcher,
                active_turn_scope=lambda: dispatcher.active_turn_scope,
                agent_scope=agent_runner.scope,
                commands=commands,
            )
            input_sources = tuple(self._input_sources)

            config_controller = ConfigController(
                root=self._root,
                environment=config,
                validator=lambda candidate: self._validate_config_candidate(
                    candidate,
                    generation_handle.snapshot().generation,
                ),
                activator=lambda candidate: self._prepare_generation_activation(
                    generation_handle,
                    candidate,
                    observations=observations,
                    bus=bus,
                    submit_reflection=submit_reflection,
                ),
                activity=lambda: (
                    "queued"
                    if agent_runner.queued_turn_ids
                    else generation_handle.activity.value
                ),
                generation_id=lambda: generation_handle.generation_id,
                activation_observer=lambda state, payload: observations.emit(
                    ObservationEvent(
                        name=f"config.activation.{state}",
                        level=ObservationLevel.NORMAL,
                        source="agent.config",
                        message=f"Configuration activation {state}.",
                        payload=payload,
                    )
                ),
                catalog=load_config_catalog().with_rules(
                    {"llm": {"adapters": adapter_specs_json()}}
                ),
            )
            return AgentAssembly(
                configuration=config_controller,
                generation_handle=generation_handle,
                commands=commands,
                agent_runner=agent_runner,
                input_dispatcher=dispatcher,
                gateway=gateway,
                input_sources=input_sources,
                observations=observations,
                resources=resources,
            )
        except ConfigCatalogError as exc:
            raise agent_bridge.startup_failure(
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
            raise agent_bridge.from_agent_error(exc) from exc
        except RuntimeException:
            raise

    async def _prepare_generation_activation(
        self,
        handle: RuntimeHandle[AgentRuntimeGeneration],
        candidate: ConfigEnvironment,
        *,
        observations: ObservationEmitter,
        bus: SignalBus,
        submit_reflection: Callable[[ReflectionRequest], Awaitable[bool]],
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
                submit_reflection=submit_reflection,
                observations=observations,
                bus=bus,
            )
        except BaseException:
            handle.fail_activation()
            raise

        previous = handle.snapshot().generation

        async def commit() -> None:
            await previous.sources.pause()
            async with handle.write():
                scope = RunScope().push(RunLevel.AGENT, "config_activation")
                transition = await generation.day.preflight(scope=scope)
                operations = JoinedOperations()
                await operations.run(
                    lambda: generation.reflection.refresh_availability(
                        transition, scope=scope
                    )
                )
                operations.check_cancelled()
                publisher = previous.sources.publisher
                if publisher is not None:
                    await generation.sources.start(publisher)
                handle.activate(generation)

        async def abort() -> tuple[CleanupDiagnostic, ...]:
            try:
                return await generation.close()
            finally:
                handle.fail_activation()
                await previous.sources.resume()

        async def retire() -> tuple[CleanupDiagnostic, ...]:
            return await previous.close()

        return PreparedConfigActivation(commit=commit, abort=abort, retire=retire)

    async def _build_generation(
        self,
        config: ConfigEnvironment,
        *,
        submit_reflection: Callable[[ReflectionRequest], Awaitable[bool]],
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
        reflection_settings = plan.reflection
        context_settings = plan.context
        action_settings = plan.action
        capabilities_settings = plan.capabilities
        agent_settings = plan.agent
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
                embedding = build_embedding_client(
                    infra_settings.embedding, env=config.runtime_env
                )
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
            workspace_runtime = WorkspaceRuntime(workspace, FileWatcher(), observations=observations)
            resources.register("workspace_events", workspace_runtime.close)
            action_assembly = CommonActionAssembly(
                root=self._root,
                workspace=workspace,
                llm=llm,
                observations=observations,
                action_settings=action_settings,
                capabilities_settings=capabilities_settings,
                runtime_env=config.runtime_env,
                execution_settings=plan.execution,
                job_settings=plan.jobs,
                workspace_source=workspace_runtime,
                runtime_plugins=(PluginDeclaration("reflection_schedule", sources=(
                    ReflectionScheduler(
                        reflection_settings.schedule,
                        clock=self._calendar_clock or IanaCalendarClock(reflection_settings.timezone),
                        timer=DeadlineTimer(), submit=submit_reflection,
                    ),
                )),),
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
                action_assembly=action_assembly,
            )
            if self._user_domain_skills is not None:
                user_builder.with_domain_skills(self._user_domain_skills)
            for handler in self._user_turn_completion_handlers:
                user_builder.add_completion_handler(handler)
            user_turn = user_builder.build()
            archive = DailyLifecycleCoordinator(
                session=session,
                archive_root=reflection_settings.archive_root,
                workspace=workspace,
                memory=memory,
                observations=observations,
            )
            day = AgentDayCoordinator(
                archive,
                memory,
                self._calendar_clock or IanaCalendarClock(reflection_settings.timezone),
                active_day=session.active_day,
            )
            reflection = ReflectionBuilder(
                action_assembly=action_assembly,
                context_settings=context_settings,
                loop_settings=loop_settings,
                settings=reflection_settings,
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
            surfaces = tuple(
                profile.action for profile in (user_turn.profile, *reflection.profiles)
            )
            declared = frozenset(
                name for surface in surfaces for name in surface.declared_actions()
            )
            unknown_actions = {
                action.name for action in plan.action_catalog.catalog.actions()
            } - declared
            if unknown_actions:
                raise ConfigError(
                    "Catalog contains undeclared actions",
                    key="action.catalog",
                    value=sorted(unknown_actions),
                )
            try:
                home.reconcile_prompt_mounts(
                    domains=tuple(
                        sorted(
                            {
                                name
                                for action in surfaces
                                for name in action.domain_names()
                            }
                        )
                    ),
                    actions=tuple(
                        sorted(
                            {
                                identity
                                for action in surfaces
                                for identity in action.action_identifiers()
                            }
                        )
                    ),
                )
            except AgentHomeError as exc:
                raise RuntimeAgentHomeBridge().startup_failure(
                    message="Profile action guidance could not be validated.",
                    payload={"error_type": type(exc).__name__},
                ) from exc
            sources = GenerationSources(tuple(source for profile in (user_turn.profile, *reflection.profiles)
                                               for source in profile.sources))
            day.bind_sources(sources)
            return AgentRuntimeGeneration(
                jobs=action_assembly.jobs,
                sources=sources,
                config=config,
                plan=plan,
                llm_provider_credentials=plan.llm.provider_credential_statuses(
                    config.runtime_env
                ),
                user_turn=user_turn,
                reflection=reflection.engine,
                day=day,
                workspace=workspace,
                input_parser=(
                    self._input_parser
                    if self._input_parser is not None
                    else InputCommandParser(agent_settings.input_commands)
                ),
                agent_settings=agent_settings,
                reflection_settings=reflection_settings,
                resources=resources,
                reflection_profiles=reflection.profiles,
            )
        except BaseException:
            try:
                await resources.close()
            except asyncio.CancelledError:
                pass
            raise

    def _validate_config_candidate(
        self, config: ConfigEnvironment, generation: AgentRuntimeGeneration
    ) -> None:
        plan = self._compile_config_plan(config)
        declared: set[str] = set()
        for profile in generation.profiles:
            profile.action.validate_candidate(plan.action_catalog.catalog)
            declared.update(profile.action.declared_actions())
        if {action.name for action in plan.action_catalog.catalog.actions()} - declared:
            raise ConfigError(
                "Catalog contains undeclared actions", key="action.catalog"
            )

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
                "agent",
                "action",
                "loop",
                "llm",
                "context",
                "home",
                "memory",
                "infra",
                "reflection",
                "session",
                "workspace",
                "capabilities",
                "execution",
                "jobs",
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
            agent=(
                self._agent_settings
                if self._agent_settings is not None
                else config.parse_section("agent", parse_agent_settings)
            ),
            action=action_settings,
            action_catalog=action_catalog,
            capabilities=config.parse_section(
                "capabilities", parse_capabilities_settings
            ),
            execution=config.parse_section("execution", parse_execution_settings),
            jobs=config.parse_section("jobs", parse_job_settings),
            context=config.parse_section("context", parse_context_settings),
            llm=config.parse_section("llm", LLMConfigParser().parse),
            loop=(
                self._loop_settings
                if self._loop_settings is not None
                else config.parse_section("loop", parse_loop_settings)
            ),
            reflection=(
                self._reflection_settings
                if self._reflection_settings is not None
                else config.parse_section(
                    "reflection",
                    lambda tree: parse_reflection_settings(
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
        bridges = {
            "agent": RuntimeAgentBridge(),
            "execution": RuntimeExecutionBridge(),
            "jobs": RuntimeJobsBridge(),
            "action": RuntimeActionBridge(),
            "context": RuntimeContextBridge(),
            "home": RuntimeAgentHomeBridge(),
            "llm": RuntimeLLMBridge(),
            "loop": RuntimeLoopBridge(),
            "memory": RuntimeMemoryBridge(),
            "session": RuntimeSessionBridge(),
            "workspace": RuntimeWorkspaceBridge(),
            "reflection": ReflectionRuntimeBridge(),
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

    def _build_reflection_settings(
        self,
        config: ConfigEnvironment,
        bridge: ReflectionRuntimeBridge,
    ) -> ReflectionSettings:
        try:
            return config.parse_section(
                "reflection",
                lambda tree: parse_reflection_settings(
                    tree,
                    project_root=self._root,
                ),
            )
        except ConfigError as exc:
            raise bridge.from_config_error(exc) from exc

    def _build_agent_settings(
        self,
        config: ConfigEnvironment,
        bridge: RuntimeAgentBridge,
    ) -> AgentSettings:
        try:
            return config.parse_section("agent", parse_agent_settings)
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
