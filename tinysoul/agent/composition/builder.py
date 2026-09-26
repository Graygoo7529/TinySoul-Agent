"""TinySoul application assembly entry point."""

from __future__ import annotations

import asyncio
import copy
from dataclasses import replace
from types import MappingProxyType
from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.runtime import RunLevel, RunScope
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

from tinysoul.kernel.action import ActionCatalogLoader
from tinysoul.kernel.action.models import ModelUseRegistry
from tinysoul.kernel.action.config import ActionSettings
from tinysoul.kernel.action.catalog.catalog import ActionCatalog
from tinysoul.kernel.retrieval.policy import (
    retrieval_schema,
    resolve_retrieval_policies,
)
from tinysoul.kernel.action.config import (
    parse_action_settings,
)
from tinysoul.kernel.context import parse_context_settings
from tinysoul.plugins.home import AgentHomeEngine
from tinysoul.plugins.home.errors import AgentHomeError
from tinysoul.plugins.memory import MemoryEngine
from tinysoul.infra.config import (
    ConfigController,
    ConfigCatalogError,
    ConfigEnvironment,
    ConfigError,
    load_config_catalog,
    PreparedConfigActivation,
)
from tinysoul.infra import parse_infra_settings
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
from .actions import CorePlugin, ProfileAssembly
from tinysoul.infra.clock import CalendarClock
from tinysoul.plugins.reflection import (
    ReflectionBuilder,
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
from tinysoul.plugins.session import SessionEngine
from tinysoul.plugins.workspace import WorkspaceEngine

from ..config import AgentSettings, parse_agent_settings
from ..errors import (
    AgentError,
    AgentInvariantError,
    AgentClosedError,
    AgentQueueFullError,
)
from ..dispatch.ingress import AgentIngress
from ..dispatch.inputs import InputCommandParser, InputDispatcher, InputSource
from ..observation.outputs import ObservationRoute, ObservationRouter, OutputSink
from tinysoul.agent.dispatch.scheduler import RootScheduler
from .assembly import AgentAssembly, AgentRuntime
from ..lifecycle.generation import AgentConfigPlan, AgentGeneration
from ..lifecycle.day import AgentDayCoordinator
from tinysoul.plugins.archive import DailyLifecycleCoordinator
from tinysoul.infra.clock import IanaCalendarClock
from ..lifecycle.runtime_policy import build_agent_trap
from tinysoul.environment.sources.scheduler import DeadlineTimer
from tinysoul.plugins.reflection.schedule import (
    ReflectionSchedulePlugin,
    ReflectionSubmission,
)
from tinysoul.kernel.registration import (
    AgentPlugin,
    GenerationBuildContext,
    PluginGeneration,
    RegistrationError,
    PluginDefinitions,
    Service,
    ServiceRegistry,
)
from tinysoul.environment.sources.fswatch import FileWatcher
from tinysoul.runtime.sources import RuntimeTimer, RuntimeWatcher
from ..lifecycle.sources import GenerationSources

from tinysoul.plugins.home.plugin import HomePlugin
from tinysoul.plugins.home.services import HomeService
from tinysoul.plugins.session.plugin import SessionPlugin
from tinysoul.plugins.memory.plugin import MemoryPlugin
from tinysoul.plugins.memory.actions import MemoryWriteSession
from tinysoul.plugins.workspace.plugin import WorkspacePlugin
from tinysoul.plugins.execution.plugin import ExecutionPlugin
from tinysoul.plugins.capabilities.expand.plugin import ExpandPlugin
from tinysoul.plugins.capabilities.subagent.plugin import SubagentPlugin
from tinysoul.plugins.capabilities.web.plugin import WebPlugin
from tinysoul.plugins.capabilities.resource.plugin import ResourcePlugin
from tinysoul.kernel.jobs import JobRegistry
from tinysoul.infra import InfraSettings
from tinysoul.infra.model_services import ModelServices
from tinysoul.infra.references import ReferenceResolver


_HARNESS_CONFIGURATION_SECTIONS = (
    "config",
    "agent",
    "action",
    "loop",
    "llm",
    "context",
    "infra",
    "reflection",
)


class AgentBuilder:
    """Assemble TinySoul runtime modules into a runnable application."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path.cwd()
        self._loop_settings: LoopSettings | None = None
        self._reflection_settings: ReflectionSettings | None = None
        self._agent_settings: AgentSettings | None = None
        self._config_env: ConfigEnvironment | None = None
        self._llm: LLMRunner | None = None
        self._calendar_clock: CalendarClock | None = None
        self._bus: SignalBus | None = None
        self._user_domain_skills: DomainSkillProvider | None = None
        self._input_parser: InputCommandParser | None = None
        self._input_sources: list[InputSource] = []
        self._user_turn_completion_handlers: list[TurnCompletionHandler] = []
        self._output_sinks: list[OutputSink] = []
        self._plugins: list[AgentPlugin] = []

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

    def use(self, plugin: AgentPlugin) -> "AgentBuilder":
        """Select one statically owned plugin for each materialized generation."""
        plugin_id = getattr(plugin, "id", None)
        if not isinstance(plugin_id, str) or not plugin_id:
            raise AgentInvariantError("Agent plugin identity must be non-empty")
        if any(existing.id == plugin_id for existing in self._plugins):
            raise AgentInvariantError(f"Agent plugin is already selected: {plugin_id}")
        self._plugins.append(plugin)
        return self

    @property
    def _definitions(self) -> PluginDefinitions:
        return PluginDefinitions(
            tuple(self._plugins),
            host_services=(
                ReflectionSubmission,
                RuntimeTimer,
                RuntimeWatcher,
                ModelServices,
                ReferenceResolver,
            ),
            reserved_configuration_sections=_HARNESS_CONFIGURATION_SECTIONS,
        )

    def build(self) -> AgentAssembly:
        """Validate and freeze composition without creating owners or I/O resources."""
        definitions = self._definitions
        if {plugin.id for plugin in _standard_plugins()} - {
            plugin.id for plugin in definitions.plugins
        }:
            raise RegistrationError(
                "TinySoul requires the complete standard plugin recipe"
            )
        required = {
            AgentHomeEngine,
            HomeService,
            SessionEngine,
            MemoryEngine,
            MemoryWriteSession,
            WorkspaceEngine,
            JobRegistry,
        }
        if required - {
            service for plugin in definitions.plugins for service in plugin.provides
        }:
            raise RegistrationError(
                "The standard recipe is missing required owner services"
            )
        builder = copy.copy(self)
        builder._input_sources = list(self._input_sources)
        builder._user_turn_completion_handlers = list(
            self._user_turn_completion_handlers
        )
        builder._output_sinks = list(self._output_sinks)
        builder._plugins = list(definitions.plugins)
        config = self._config_env or ConfigEnvironment.from_project_root(self._root)
        builder._compile_config_plan(config, map_runtime_errors=True)

        async def materialize() -> AgentRuntime:
            runtime_builder = copy.copy(builder)
            runtime_builder._config_env = config.reload()
            resources = AsyncResourceScope()
            try:
                return await runtime_builder._build_runtime(resources)
            except BaseException:
                try:
                    await resources.close()
                except asyncio.CancelledError:
                    pass
                raise

        return AgentAssembly(
            root=self._root,
            runtime_factory=materialize,
            plugin_ids=tuple(plugin.id for plugin in definitions.plugins),
        )

    async def _build_runtime(self, resources: AsyncResourceScope) -> AgentRuntime:
        return await self._build(resources)

    async def _build(self, resources: AsyncResourceScope) -> AgentRuntime:
        agent_bridge = RuntimeAgentBridge()
        llm_bridge = RuntimeLLMBridge()
        reflection_bridge = ReflectionRuntimeBridge()
        try:
            config = (
                self._config_env
                if self._config_env is not None
                else ConfigEnvironment.from_project_root(self._root)
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

            commands = AgentCommands(
                agent_runner,
                source_statuses=lambda: (
                    generation_handle.snapshot().generation.sources.statuses
                ),
            )
            dispatcher = InputDispatcher(
                parser=parser,
                commands=commands,
                observations=observations,
                agent_scope=agent_runner.scope,
                parser_provider=lambda: (
                    generation_handle.snapshot().generation.input_parser
                ),
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
            return AgentRuntime(
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
        handle: RuntimeHandle[AgentGeneration],
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
    ) -> AgentGeneration:
        """Compile module settings and construct one complete business generation."""

        plan = self._compile_config_plan(
            config,
            map_runtime_errors=map_config_errors,
        )
        loop_settings = plan.loop
        reflection_settings = plan.reflection
        context_settings = plan.context
        action_settings = plan.action
        agent_settings = plan.agent
        resources = AsyncResourceScope()
        plugin_generations: tuple[PluginGeneration, ...] = ()
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
            model_services = ModelServices(
                plan.infra.model_services, env=config.runtime_env
            )
            references = ReferenceResolver()
            resources.register("model_services", model_services.close)
            clock = self._calendar_clock or IanaCalendarClock(
                reflection_settings.timezone
            )
            plugin_generations = await self._definitions.build(
                GenerationBuildContext(
                    root=self._root,
                    runtime_env=MappingProxyType(dict(config.runtime_env)),
                    settings=ServiceRegistry(
                        (
                            Service(InfraSettings, plan.infra),
                            Service(ActionSettings, plan.action),
                            Service(ModelUseRegistry, plan.model_uses),
                            Service(ReflectionSettings, reflection_settings),
                            *plan.plugin_settings,
                        )
                    ),
                    services=ServiceRegistry(()),
                    llm=llm,
                    observations=observations,
                    clock=clock,
                ),
                resources,
                host_services=(
                    Service(ModelServices, model_services),
                    Service(ReferenceResolver, references),
                    Service(
                        ReflectionSubmission, ReflectionSubmission(submit_reflection)
                    ),
                    Service(RuntimeTimer, DeadlineTimer()),
                    Service(RuntimeWatcher, FileWatcher()),
                ),
            )
            services = ServiceRegistry(
                tuple(item for plugin in plugin_generations for item in plugin.services)
            )
            home, memory = services.get(AgentHomeEngine), services.get(MemoryEngine)
            session, workspace = (
                services.get(SessionEngine),
                services.get(WorkspaceEngine),
            )
            references.bind(
                {
                    "home": home.canonical_reference,
                    "memory": memory.canonical_reference,
                    "workspace": workspace.canonical_reference,
                }
            )
            jobs = services.get(JobRegistry)
            sources = GenerationSources(
                tuple(
                    source for plugin in plugin_generations for source in plugin.sources
                )
            )
            action_assembly = ProfileAssembly(
                plugins=plugin_generations,
                llm=llm,
                home=services.get(HomeService),
                jobs=jobs,
                observations=observations,
                action_settings=action_settings,
                models=plan.model_uses,
            )
            user_builder = UserTurnBuilder(
                context_settings=context_settings,
                loop_settings=loop_settings,
                llm=llm,
                bus=bus,
                observations=observations,
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
                release_day=tuple(
                    plugin.release_day
                    for plugin in plugin_generations
                    if plugin.release_day is not None
                ),
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
                memory_controller=services.get(MemoryWriteSession),
            ).build()
            surfaces = tuple(
                profile.action for profile in (user_turn.profile, *reflection.profiles)
            )
            self._validate_selected_models(
                plan,
                frozenset(
                    name
                    for surface in surfaces
                    for _, name in surface.action_identifiers()
                ),
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
            day.bind_sources(sources)
            return AgentGeneration(
                jobs=jobs,
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
                plugin_generations=plugin_generations,
            )
        except BaseException:
            try:
                await resources.close()
            except asyncio.CancelledError:
                pass
            raise

    def _validate_config_candidate(
        self, config: ConfigEnvironment, generation: AgentGeneration
    ) -> None:
        plan = self._compile_config_plan(config)
        declared: set[str] = set()
        selected: set[str] = set()
        for profile in generation.profiles:
            selected.update(
                profile.action.validate_candidate(plan.action_catalog.catalog)
            )
            declared.update(profile.action.declared_actions())
        self._validate_selected_models(plan, frozenset(selected))
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
        definitions = self._definitions
        config.validate_sections(
            {
                *_HARNESS_CONFIGURATION_SECTIONS,
                *(item.section.split(".", 1)[0] for item in definitions.configuration),
            }
        )
        plugin_settings = definitions.configure(config, self._root)
        action_settings = config.parse_section("action", parse_action_settings)
        action_catalog = ActionCatalogLoader().load_documents(
            config.document_set("action.catalog")
        )
        model_uses = ModelUseRegistry(definitions.model_uses, action_settings.bindings)
        retrieval_policies = action_settings.retrieval_policies
        retrieval_policies = resolve_retrieval_policies(
            definitions.search_capabilities, retrieval_policies,
            {binding.consumer: binding.implementation.value for binding in action_settings.bindings},
        )
        action_settings = replace(action_settings, retrieval_policies=retrieval_policies)
        action_ids = {action.name for action in action_catalog.catalog.actions()}
        if any(
            policy.action_id not in action_ids for policy in retrieval_policies
        ):
            raise ConfigError(
                "Search policy names an unknown action",
                key="action.retrieval",
            )
        action_catalog = replace(
            action_catalog,
            catalog=ActionCatalog(
                domains=action_catalog.catalog.domains(),
                actions=tuple(
                    replace(
                        action,
                        tool=replace(
                            action.tool,
                            schema=(
                                retrieval_schema(
                                    action.tool.schema,
                                    next(item for item in retrieval_policies if item.action_id == action.name),
                                )
                            ),
                        ),
                    )
                    if any(policy.action_id == action.name for policy in retrieval_policies)
                    else action
                    for action in action_catalog.catalog.actions()
                ),
            ),
        )
        plan = AgentConfigPlan(
            environment=config,
            infra=config.parse_section("infra", parse_infra_settings),
            agent=(
                self._agent_settings
                if self._agent_settings is not None
                else config.parse_section("agent", parse_agent_settings)
            ),
            action=action_settings,
            model_uses=model_uses,
            action_catalog=action_catalog,
            plugin_settings=plugin_settings,
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
        )
        try:
            if self._llm is None:
                plan.llm.validate_enabled_provider_credentials(config.runtime_env)
            validate_cycle_task_profiles(
                plan.loop.cycle,
                task_profiles=plan.llm.tasks.profiles(),
            )
            plan.model_uses.validate_targets(
                plan.llm.tasks.profiles(), plan.infra.model_services
            )
        except ConfigError as exc:
            enriched = config.enrich_error(exc)
            if enriched is exc:
                raise
            raise enriched from exc
        return plan

    def _validate_selected_models(
        self, plan: AgentConfigPlan, actions: frozenset[str]
    ) -> None:
        from tinysoul.plugins.home.config import AgentHomeSettings
        from tinysoul.plugins.memory.config import MemorySettings

        embedding_uses = {}
        for setting in plan.plugin_settings:
            if isinstance(setting.value, AgentHomeSettings):
                embedding_uses["home"] = setting.value.search.embedding_use
            elif isinstance(setting.value, MemorySettings):
                embedding_uses["memory"] = setting.value.search.embedding_use
        plan.model_uses.validate_selected(
            actions=actions,
            retrieval_policies=plan.action.retrieval_policies,
            services=plan.infra.model_services,
            env=plan.environment.runtime_env,
            embedding_uses=embedding_uses,
        )

    def _map_owned_config_error(self, error: ConfigError) -> RuntimeException:
        for item in self._definitions.configuration:
            if error.key == item.section or error.key.startswith(item.section + "."):
                return item.failure(error)
        key = error.key.split(".", 1)[0] if error.key else "infra"
        if error.source.startswith("project-document:action.catalog:"):
            return RuntimeActionBridge().from_config_error(error)
        bridges = {
            "agent": RuntimeAgentBridge(),
            "action": RuntimeActionBridge(),
            "context": RuntimeContextBridge(),
            "llm": RuntimeLLMBridge(),
            "loop": RuntimeLoopBridge(),
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


def _standard_plugins() -> tuple[AgentPlugin, ...]:
    return (
        HomePlugin(),
        SessionPlugin(),
        MemoryPlugin(),
        WorkspacePlugin(),
        CorePlugin(),
        ExecutionPlugin(),
        ExpandPlugin(),
        SubagentPlugin(),
        WebPlugin(),
        ResourcePlugin(),
        ReflectionSchedulePlugin(),
    )


def standard_agent(root: Path | None = None) -> AgentBuilder:
    """The complete TinySoul owner recipe, extensible by explicit host plugins."""
    builder = AgentBuilder(root)
    for plugin in _standard_plugins():
        builder.use(plugin)
    return builder
