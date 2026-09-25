"""Explicit, typed contributions resolved before profile activation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import IntEnum, StrEnum
import re
from types import MappingProxyType
from typing import Protocol, cast
from pathlib import Path

from .action import ActionEngineBuilder
from .action.tasks import ActionTaskFactory
from .action.models import ModelUseDescriptor
from .retrieval.policy import SearchCapability
from .context import ContextEngine
from .context.errors import ContextError
from .context.segments import RegisteredSegment, SegmentRegistry
from .loop.interaction.events import TurnEventSubscription
from .loop.lifecycle.preparation import TurnPreparationHandler, TurnPreparationPipeline
from .loop.lifecycle.completion import TurnCompletionHandler, TurnCompletionPipeline
from tinysoul.runtime.sources import RuntimeSource
from tinysoul.infra.concurrency import AsyncCloser
from tinysoul.infra.services import ServiceScope
from tinysoul.runtime import TrapHandlerRegistry
from tinysoul.runtime.trap.handler import TrapHandler
from tinysoul.infra.concurrency import CleanupDiagnostic, AsyncResourceScope
from tinysoul.infra.clock import CalendarClock
from tinysoul.infra.config import ConfigEnvironment, ConfigError, reject_unknown_keys
from tinysoul.runtime import ObservationEmitter, RuntimeException
from .loop.phases import LLMRunner


class RegistrationError(Exception):
    """Declared capabilities cannot form a consistent profile."""


class ProfileKind(StrEnum):
    USER = "user"
    HOME_REFLECTION = "home_reflection"
    MEMORY_REFLECTION = "memory_reflection"


class ServiceRegistration(Protocol):
    @property
    def facade(self) -> type[object]: ...

    @property
    def value(self) -> object: ...


@dataclass(frozen=True)
class Service[T]:
    facade: type[T]
    value: T

    def __post_init__(self) -> None:
        if not isinstance(self.facade, type) or not isinstance(self.value, self.facade):
            raise RegistrationError("A service must implement its declared facade")


class ServiceRegistry:
    """Resolve concrete facade types; never expose mutable registry storage."""

    def __init__(self, registrations: tuple[ServiceRegistration, ...]) -> None:
        services: dict[type[object], object] = {}
        for registration in registrations:
            if registration.facade in services:
                raise RegistrationError("A service facade has more than one owner")
            if not isinstance(registration.value, registration.facade):
                raise RegistrationError(
                    "Registered service does not implement its facade"
                )
            services[registration.facade] = registration.value
        self._services: Mapping[type[object], object] = MappingProxyType(services)

    def get[T](self, facade: type[T]) -> T:
        if facade not in self._services:
            raise RegistrationError("The requested service is not declared")
        # The heterogeneous table is sealed after the registration check above.
        return cast(T, self._services[facade])

    def select(self, facades: tuple[type[object], ...]) -> ServiceRegistry:
        return ServiceRegistry(
            tuple(Service(facade, self.get(facade)) for facade in facades)
        )


@dataclass(frozen=True)
class ProfileBuildContext:
    context: ContextEngine
    tasks: ActionTaskFactory
    llm: LLMRunner
    bindings: ServiceRegistry


class TurnResourceOwner(Protocol):
    async def close_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]: ...


class TurnResourceStage(IntEnum):
    RELEASE = 0
    SYNCHRONIZE = 1


@dataclass(frozen=True)
class PluginTurnResource:
    owner: TurnResourceOwner
    stage: TurnResourceStage = TurnResourceStage.RELEASE


@dataclass(frozen=True)
class PluginTrapHandler:
    reason: str
    handler: TrapHandler


@dataclass(frozen=True)
class PluginProfileExtension:
    id: str
    services: tuple[ServiceRegistration, ...] = ()
    requires: tuple[type[object], ...] = ()
    segments: tuple[RegisteredSegment, ...] = ()
    actions: Callable[[ActionEngineBuilder], ActionEngineBuilder] | None = None
    events: tuple[TurnEventSubscription, ...] = ()
    preparation: tuple[TurnPreparationHandler, ...] = ()
    completion: tuple[TurnCompletionHandler, ...] = ()
    recorder: TurnCompletionHandler | None = None
    trap_handlers: tuple[PluginTrapHandler, ...] = ()
    turn_resources: tuple[PluginTurnResource, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, str)
            or re.fullmatch(r"[a-z][a-z0-9_]*", self.id) is None
        ):
            raise RegistrationError("Plugin identity must use lower_snake_case")
        object.__setattr__(self, "services", tuple(self.services))
        object.__setattr__(self, "requires", tuple(self.requires))
        object.__setattr__(self, "segments", tuple(self.segments))
        for name in (
            "events",
            "preparation",
            "completion",
            "trap_handlers",
            "turn_resources",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))


class ServiceLifetime(StrEnum):
    GENERATION = "generation"
    DAY = "day"


class ServiceExport(Protocol):
    @property
    def facade(self) -> type[object]: ...

    @property
    def lifetime(self) -> ServiceLifetime: ...

    def bind(self, scope: ServiceScope) -> ServiceRegistration: ...


@dataclass(frozen=True)
class PluginServiceExport[T]:
    facade: type[T]
    factory: Callable[[ServiceScope], T]
    lifetime: ServiceLifetime = ServiceLifetime.GENERATION

    def bind(self, scope: ServiceScope) -> Service[T]:
        return Service(self.facade, self.factory(scope))


class PluginConfiguration(Protocol):
    @property
    def section(self) -> str: ...

    @property
    def settings(self) -> type[object]: ...

    def load(self, config: ConfigEnvironment, root: Path) -> ServiceRegistration: ...

    def failure(self, error: ConfigError, /) -> RuntimeException: ...


@dataclass(frozen=True)
class PluginConfig[T]:
    section: str
    settings: type[T]
    parse: Callable[[Mapping[str, object], Path], T]
    failure: Callable[[ConfigError], RuntimeException]
    validate: Callable[[T, Mapping[str, str]], object] | None = None

    def load(self, config: ConfigEnvironment, root: Path) -> Service[T]:
        value = config.parse_section(self.section, lambda tree: self.parse(tree, root))
        if self.validate is not None:
            self.validate(value, config.runtime_env)
        return Service(self.settings, value)


@dataclass(frozen=True)
class GenerationBuildContext:
    """Parsed settings plus only the selected plugin's declared build services."""

    root: Path
    runtime_env: Mapping[str, str]
    settings: ServiceRegistry
    services: ServiceRegistry
    llm: LLMRunner
    observations: ObservationEmitter
    clock: CalendarClock


class AgentPlugin(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def provides(self) -> tuple[type[object], ...]: ...

    @property
    def requires(self) -> tuple[type[object], ...]: ...

    @property
    def configuration(self) -> tuple[PluginConfiguration, ...]: ...

    @property
    def model_uses(self) -> tuple[ModelUseDescriptor, ...]: ...

    @property
    def search_capabilities(self) -> tuple[SearchCapability, ...]: ...

    async def build_generation(
        self, context: GenerationBuildContext
    ) -> PluginGeneration: ...


@dataclass(frozen=True)
class PluginGeneration:
    """Resources and declarations owned by one plugin in one Agent generation."""

    id: str
    services: tuple[ServiceRegistration, ...] = ()
    profile_extension_factory: (
        Callable[[ProfileKind, ProfileBuildContext], PluginProfileExtension | None]
        | None
    ) = None
    sources: tuple[RuntimeSource, ...] = ()
    sdk_exports: tuple[ServiceExport, ...] = ()
    release_day: AsyncCloser | None = None
    close: AsyncCloser | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, str)
            or re.fullmatch(r"[a-z][a-z0-9_]*", self.id) is None
        ):
            raise RegistrationError(
                "Plugin generation identity must use lower_snake_case"
            )
        for name in ("services", "sources", "sdk_exports"):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    def extend_profile(
        self, kind: ProfileKind, context: ProfileBuildContext
    ) -> PluginProfileExtension | None:
        factory = self.profile_extension_factory
        return factory(kind, context) if factory is not None else None


def _configuration_scopes_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(right + ".") or right.startswith(left + ".")


def _validate_configuration_sections(
    sections: tuple[str, ...], *, conflict_message: str
) -> None:
    for index, section in enumerate(sections):
        if re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*", section) is None:
            raise RegistrationError(
                "Configuration sections must use dotted lower_snake_case"
            )
        if any(
            _configuration_scopes_overlap(section, other) for other in sections[:index]
        ):
            raise RegistrationError(conflict_message)


class PluginDefinitions:
    """Validate the complete recipe before creating any runtime resource."""

    def __init__(
        self,
        plugins: tuple[AgentPlugin, ...],
        *,
        host_services: tuple[type[object], ...] = (),
        reserved_configuration_sections: tuple[str, ...] = (),
    ) -> None:
        by_id: dict[str, AgentPlugin] = {}
        owners: dict[type[object], AgentPlugin | None] = {
            key: None for key in host_services
        }
        configurations: list[PluginConfiguration] = []
        reserved_sections = tuple(reserved_configuration_sections)
        _validate_configuration_sections(
            reserved_sections,
            conflict_message="Reserved configuration scopes overlap",
        )
        for plugin in plugins:
            if (
                re.fullmatch(r"[a-z][a-z0-9_]*", plugin.id) is None
                or plugin.id in by_id
            ):
                raise RegistrationError(
                    "Agent plugin identities must be unique lower_snake_case"
                )
            by_id[plugin.id] = plugin
            for service in plugin.provides:
                if service in owners:
                    raise RegistrationError("A build service has more than one owner")
                owners[service] = plugin
            configurations.extend(plugin.configuration)
        sections = tuple(item.section for item in configurations)
        _validate_configuration_sections(
            sections,
            conflict_message="Plugin configuration scopes overlap",
        )
        if any(
            _configuration_scopes_overlap(section, reserved)
            for section in sections
            for reserved in reserved_sections
        ):
            raise RegistrationError(
                "Plugin configuration scopes overlap reserved host configuration"
            )
        settings_facades: set[type[object]] = set()
        for configuration in configurations:
            if configuration.settings in settings_facades:
                raise RegistrationError(
                    "A plugin settings facade has more than one owner"
                )
            settings_facades.add(configuration.settings)
        ordered: list[AgentPlugin] = []
        visiting: set[str] = set()
        complete: set[str] = set()

        def visit(plugin: AgentPlugin) -> None:
            if plugin.id in complete:
                return
            if plugin.id in visiting:
                raise RegistrationError(
                    "Agent plugin build dependencies contain a cycle"
                )
            visiting.add(plugin.id)
            for service in plugin.requires:
                if service not in owners:
                    raise RegistrationError(
                        "Agent plugin requires an undeclared build service"
                    )
                owner = owners[service]
                if owner is not None:
                    visit(owner)
            visiting.remove(plugin.id)
            complete.add(plugin.id)
            ordered.append(plugin)

        for plugin in plugins:
            visit(plugin)
        self.plugins = tuple(ordered)
        self.configuration = tuple(configurations)
        self.model_uses = tuple(
            item for plugin in ordered for item in plugin.model_uses
        )
        self.search_capabilities = tuple(
            item for plugin in ordered for item in plugin.search_capabilities
        )

    def configure(
        self, config: ConfigEnvironment, root: Path, *, map_errors: bool = False
    ) -> tuple[ServiceRegistration, ...]:
        containers: dict[str, set[str]] = {}
        for item in self.configuration:
            parts = item.section.split(".")
            for index in range(1, len(parts)):
                containers.setdefault(".".join(parts[:index]), set()).add(parts[index])
        for parent, children in containers.items():
            reject_unknown_keys(config.section_tree(parent), children, key=parent)
        parsed: list[ServiceRegistration] = []
        for item in self.configuration:
            try:
                parsed.append(item.load(config, root))
            except ConfigError as exc:
                if map_errors:
                    raise item.failure(exc) from exc
                raise
        return tuple(parsed)

    async def build(
        self,
        context: GenerationBuildContext,
        resources: AsyncResourceScope,
        *,
        host_services: tuple[ServiceRegistration, ...] = (),
    ) -> tuple[PluginGeneration, ...]:
        services = list(host_services)
        generations: list[PluginGeneration] = []
        exports: set[type[object]] = set()
        for plugin in self.plugins:
            dependencies = ServiceRegistry(tuple(services)).select(plugin.requires)
            generation = await plugin.build_generation(
                GenerationBuildContext(
                    context.root,
                    context.runtime_env,
                    context.settings,
                    dependencies,
                    context.llm,
                    context.observations,
                    context.clock,
                )
            )
            # The factory transfers ownership on return, including candidates
            # whose declarations are rejected below.
            if generation.close is not None:
                resources.register(plugin.id, generation.close)
            if generation.id != plugin.id or {
                item.facade for item in generation.services
            } != set(plugin.provides):
                raise RegistrationError(
                    "Plugin generation does not match its declared build services"
                )
            ServiceRegistry(generation.services)
            for export in generation.sdk_exports:
                if export.facade in exports:
                    raise RegistrationError("An SDK service has more than one owner")
                exports.add(export.facade)
            services.extend(generation.services)
            generations.append(generation)
        return tuple(generations)


class ResolvedProfileExtensions:
    """Only validated contributions can be installed into a profile."""

    def __init__(
        self,
        declarations: tuple[PluginProfileExtension, ...],
        services: ServiceRegistry,
        context: ContextEngine,
    ) -> None:
        self._declarations = declarations
        self.services = services
        self._context = context
        self._activated = False
        self.trap_handlers = tuple(
            item for declaration in declarations for item in declaration.trap_handlers
        )
        reasons = tuple(item.reason for item in self.trap_handlers)
        if len(set(reasons)) != len(reasons):
            raise RegistrationError("Profile Trap reasons must be unique")
        self.turn_resources = tuple(
            sorted(
                (
                    item
                    for declaration in declarations
                    for item in declaration.turn_resources
                ),
                key=lambda item: item.stage,
            )
        )
        self.events = tuple(
            item for declaration in declarations for item in declaration.events
        )
        self.preparation = TurnPreparationPipeline(
            tuple(
                item for declaration in declarations for item in declaration.preparation
            )
        )
        recorders = tuple(
            item.recorder for item in declarations if item.recorder is not None
        )
        if len(recorders) > 1:
            raise RegistrationError(
                "A profile can declare only one completion recorder"
            )
        self.completion = TurnCompletionPipeline(
            tuple(
                item for declaration in declarations for item in declaration.completion
            ),
            recorders[0] if recorders else None,
        )

    def install_traps(self, registry: TrapHandlerRegistry) -> None:
        for contribution in self.trap_handlers:
            registry.register(contribution.reason, contribution.handler)

    def activate(self, action: ActionEngineBuilder) -> None:
        if self._activated:
            raise RegistrationError(
                "Resolved profile plugins can only be activated once"
            )
        self._activated = True
        self._context.register_segments(
            tuple(
                segment
                for declaration in self._declarations
                for segment in declaration.segments
            )
        )
        for declaration in self._declarations:
            if declaration.actions is not None:
                declaration.actions(action)


class PluginRegistry:
    def __init__(self, declarations: tuple[PluginProfileExtension, ...]) -> None:
        self._declarations = tuple(declarations)

    def resolve(self, context: ContextEngine) -> ResolvedProfileExtensions:
        declarations = self._declarations
        by_id = {declaration.id: declaration for declaration in declarations}
        if len(by_id) != len(declarations):
            raise RegistrationError("Plugin identities must be unique")
        services = ServiceRegistry(
            tuple(
                service
                for declaration in declarations
                for service in declaration.services
            )
        )
        providers = {
            service.facade: declaration.id
            for declaration in declarations
            for service in declaration.services
        }
        segments = tuple(
            segment for declaration in declarations for segment in declaration.segments
        )
        try:
            SegmentRegistry(segments)
            if segments:
                context.validate_segments(segments)
        except ContextError as exc:
            raise RegistrationError(
                "Plugin segment identities or routes conflict"
            ) from exc
        ordered: list[PluginProfileExtension] = []
        active: set[str] = set()
        complete: set[str] = set()

        def visit(declaration: PluginProfileExtension) -> None:
            if declaration.id in complete:
                return
            if declaration.id in active:
                raise RegistrationError("Plugin dependencies contain a cycle")
            active.add(declaration.id)
            for facade in declaration.requires:
                owner = providers.get(facade)
                if owner is None:
                    raise RegistrationError(
                        "Plugin requires an undeclared service facade"
                    )
                if owner != declaration.id:
                    visit(by_id[owner])
            active.remove(declaration.id)
            complete.add(declaration.id)
            ordered.append(declaration)

        for declaration in declarations:
            visit(declaration)
        return ResolvedProfileExtensions(tuple(ordered), services, context)
