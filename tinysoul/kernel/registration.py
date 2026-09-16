"""Explicit, typed contributions resolved before profile activation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Mapping, Protocol, cast

from .action import ActionEngineBuilder
from .context import ContextEngine
from .context.errors import ContextError
from .context.segments import RegisteredSegment, SegmentRegistry


class RegistrationError(Exception):
    """Declared capabilities cannot form a consistent profile."""


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
                raise RegistrationError("Registered service does not implement its facade")
            services[registration.facade] = registration.value
        self._services: Mapping[type[object], object] = MappingProxyType(services)

    def get[T](self, facade: type[T]) -> T:
        if facade not in self._services:
            raise RegistrationError("The requested service is not declared")
        # The heterogeneous table is sealed after the registration check above.
        return cast(T, self._services[facade])


@dataclass(frozen=True)
class PluginDeclaration:
    id: str
    services: tuple[ServiceRegistration, ...] = ()
    requires: tuple[type[object], ...] = ()
    segments: tuple[RegisteredSegment, ...] = ()
    actions: Callable[[ActionEngineBuilder], ActionEngineBuilder] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or re.fullmatch(r"[a-z][a-z0-9_]*", self.id) is None:
            raise RegistrationError("Plugin identity must use lower_snake_case")
        object.__setattr__(self, "services", tuple(self.services))
        object.__setattr__(self, "requires", tuple(self.requires))
        object.__setattr__(self, "segments", tuple(self.segments))


class ResolvedPlugins:
    """Only validated contributions can be installed into a profile."""

    def __init__(self, declarations: tuple[PluginDeclaration, ...], services: ServiceRegistry, context: ContextEngine) -> None:
        self._declarations = declarations
        self.services = services
        self._context = context
        self._activated = False

    def activate(self, action: ActionEngineBuilder) -> None:
        if self._activated:
            raise RegistrationError("Resolved profile plugins can only be activated once")
        self._activated = True
        self._context.register_segments(tuple(segment for declaration in self._declarations for segment in declaration.segments))
        for declaration in self._declarations:
            if declaration.actions is not None:
                declaration.actions(action)


class PluginRegistry:
    def __init__(self, declarations: tuple[PluginDeclaration, ...]) -> None:
        self._declarations = tuple(declarations)

    def resolve(self, context: ContextEngine) -> ResolvedPlugins:
        declarations = self._declarations
        by_id = {declaration.id: declaration for declaration in declarations}
        if len(by_id) != len(declarations):
            raise RegistrationError("Plugin identities must be unique")
        services = ServiceRegistry(tuple(service for declaration in declarations for service in declaration.services))
        providers = {service.facade: declaration.id for declaration in declarations for service in declaration.services}
        segments = tuple(segment for declaration in declarations for segment in declaration.segments)
        try:
            SegmentRegistry(segments)
            context.validate_segments(segments)
        except ContextError as exc:
            raise RegistrationError("Plugin segment identities or routes conflict") from exc
        ordered: list[PluginDeclaration] = []
        active: set[str] = set()
        complete: set[str] = set()

        def visit(declaration: PluginDeclaration) -> None:
            if declaration.id in complete:
                return
            if declaration.id in active:
                raise RegistrationError("Plugin dependencies contain a cycle")
            active.add(declaration.id)
            for facade in declaration.requires:
                owner = providers.get(facade)
                if owner is None:
                    raise RegistrationError("Plugin requires an undeclared service facade")
                if owner != declaration.id:
                    visit(by_id[owner])
            active.remove(declaration.id)
            complete.add(declaration.id)
            ordered.append(declaration)

        for declaration in declarations:
            visit(declaration)
        return ResolvedPlugins(tuple(ordered), services, context)
