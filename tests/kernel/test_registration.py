"""Plugin resolution must fail before any contribution is activated."""

from pathlib import Path
from dataclasses import replace
from typing import cast

import pytest

from tinysoul.kernel.action import ActionCatalog, ActionEngineBuilder
from tinysoul.kernel.context import ContextEngineBuilder
from tinysoul.kernel.jobs import jobs_segment_registration
from tinysoul.kernel.registration import (
    GenerationBuildContext,
    PluginConfiguration,
    PluginDefinitions,
    PluginGeneration,
    PluginProfileExtension,
    PluginRegistry,
    PluginTrapHandler,
    RegistrationError,
    Service,
    ServiceRegistration,
    ServiceRegistry,
)
from tinysoul.infra.config import ConfigEnvironment, ConfigError
from tinysoul.infra.clock import CalendarClock
from tinysoul.infra.concurrency import AsyncResourceScope
from tinysoul.kernel.loop.phases import LLMRunner
from tinysoul.runtime import ObservationEmitter
from tinysoul.kernel.loop.interaction.events import TurnEventSubscription
from tinysoul.kernel.loop.interaction.inbox import TurnInbox
from tinysoul.kernel.loop.turn import TurnRunner
from tinysoul.kernel.loop.cycle import CycleOutcome, CycleRunner
from tinysoul.kernel.loop.config import TurnSettings
from tinysoul.infra.time import CalendarDay
from tinysoul.runtime import (
    RunScope,
    RunLevel,
    SignalBus,
    RuntimeException,
    RuntimeTrap,
    TrapHandlerRegistry,
)
from tinysoul.runtime.events import EnvironmentEvent, EventKind, EventFilter
from tinysoul.runtime.trap.handler import TrapResult
from tinysoul.runtime.trap.snap import TrapSnap
from tinysoul.kernel.loop.lifecycle.completion import TurnCompletion


class Storage:
    pass


class Consumer:
    pass


class _SettingsA:
    pass


class _SettingsB:
    pass


class _Configuration:
    def __init__(self, section: str, settings: type[object]) -> None:
        self.section = section
        self.settings = settings

    def load(
        self, config: ConfigEnvironment, root: Path
    ) -> ServiceRegistration:
        raise AssertionError("configuration loading is outside this declaration test")

    def failure(self, error: ConfigError, /) -> RuntimeException:
        raise AssertionError("failure mapping is outside this declaration test")


class _DefinitionPlugin:
    provides: tuple[type[object], ...] = ()
    requires: tuple[type[object], ...] = ()

    def __init__(
        self, plugin_id: str, *configuration: PluginConfiguration,
        requires: tuple[type[object], ...] = (),
        provides: tuple[type[object], ...] = (),
    ) -> None:
        self.id = plugin_id
        self.configuration = tuple(configuration)
        self.requires = requires
        self.provides = provides

    async def build_generation(
        self, context: GenerationBuildContext
    ) -> PluginGeneration:
        return PluginGeneration(self.id)


@pytest.mark.parametrize(
    ("section", "reserved"),
    [("loop", "loop"), ("loop.extra", "loop"), ("loop", "loop.extra")],
)
def test_plugin_configuration_cannot_claim_host_reserved_scope(
    section: str, reserved: str,
) -> None:
    plugin = _DefinitionPlugin(
        "probe", _Configuration(section, _SettingsA)
    )

    with pytest.raises(RegistrationError, match="reserved host"):
        PluginDefinitions(
            (plugin,), reserved_configuration_sections=(reserved,)
        )


def test_plugin_configuration_allows_sibling_capability_scopes() -> None:
    definitions = PluginDefinitions(
        (
            _DefinitionPlugin(
                "probe", _Configuration("capabilities.probe", _SettingsA)
            ),
            _DefinitionPlugin(
                "web", _Configuration("capabilities.web", _SettingsB)
            ),
        ),
        reserved_configuration_sections=("loop", "reflection"),
    )

    assert tuple(item.section for item in definitions.configuration) == (
        "capabilities.probe",
        "capabilities.web",
    )


@pytest.mark.parametrize("section", ["Capabilities.probe", "capabilities..probe", "probe-"])
def test_plugin_configuration_requires_dotted_lower_snake_case(section: str) -> None:
    with pytest.raises(RegistrationError, match="dotted lower_snake_case"):
        PluginDefinitions(
            (_DefinitionPlugin("probe", _Configuration(section, _SettingsA)),)
        )


def test_plugin_configuration_settings_facade_has_one_owner() -> None:
    with pytest.raises(RegistrationError, match="settings facade"):
        PluginDefinitions(
            (
                _DefinitionPlugin(
                    "first", _Configuration("first", _SettingsA)
                ),
                _DefinitionPlugin(
                    "second", _Configuration("second", _SettingsA)
                ),
            )
        )


def test_plugin_definitions_reject_duplicate_ids_missing_services_and_cycles() -> None:
    duplicate = _DefinitionPlugin("same")
    with pytest.raises(RegistrationError):
        PluginDefinitions((duplicate, _DefinitionPlugin("same")))
    with pytest.raises(RegistrationError, match="undeclared"):
        PluginDefinitions((_DefinitionPlugin("missing", requires=(Storage,)),))
    first = _DefinitionPlugin("first", requires=(Consumer,), provides=(Storage,))
    second = _DefinitionPlugin("second", requires=(Storage,), provides=(Consumer,))
    with pytest.raises(RegistrationError, match="cycle"):
        PluginDefinitions((first, second))


@pytest.mark.parametrize("wrong_id", [True, False], ids=["identity", "provided-services"])
async def test_plugin_generation_declaration_failure_closes_candidate(wrong_id: bool) -> None:
    closed = 0

    class Mismatch(_DefinitionPlugin):
        async def build_generation(self, context: GenerationBuildContext) -> PluginGeneration:
            del context

            async def close() -> None:
                nonlocal closed
                closed += 1

            return PluginGeneration("wrong" if wrong_id else self.id, close=close)

    definitions = PluginDefinitions(
        (Mismatch("declared", provides=(Storage,)),)
    )
    context = GenerationBuildContext(
        root=Path("."), runtime_env={}, settings=ServiceRegistry(()),
        services=ServiceRegistry(()), llm=cast(LLMRunner, object()),
        observations=cast(ObservationEmitter, object()),
        clock=cast(CalendarClock, object()),
    )
    resources = AsyncResourceScope()
    with pytest.raises(RegistrationError, match="does not match"):
        await definitions.build(context, resources)
    await resources.close()
    assert closed == 1


def test_profile_rejects_duplicate_traps_and_completion_recorders_before_activation() -> None:
    class Handler:
        def handle(self, snap: TrapSnap) -> TrapResult:
            raise AssertionError("invalid contributions must not run")

    class Recorder:
        async def handle(self, completion: TurnCompletion) -> None:
            raise AssertionError("invalid contributions must not run")

    context = ContextEngineBuilder(system_text="identity").build()
    trap = PluginTrapHandler("probe.failed", Handler())
    with pytest.raises(RegistrationError, match="Trap reasons"):
        PluginRegistry(tuple(
            PluginProfileExtension(name, trap_handlers=(trap,))
            for name in ("first", "second")
        )).resolve(context)
    with pytest.raises(RegistrationError, match="completion recorder"):
        PluginRegistry(tuple(
            PluginProfileExtension(name, recorder=Recorder())
            for name in ("first", "second")
        )).resolve(context)


def test_plugins_resolve_typed_services_and_activate_in_dependency_order() -> None:
    storage, consumer = Storage(), Consumer()
    activated: list[str] = []

    def activate_storage(builder: ActionEngineBuilder) -> ActionEngineBuilder:
        activated.append("storage")
        return builder

    def activate_consumer(builder: ActionEngineBuilder) -> ActionEngineBuilder:
        activated.append("consumer")
        return builder

    context = ContextEngineBuilder(system_text="identity").build()
    resolved = PluginRegistry((
        PluginProfileExtension("consumer", requires=(Storage,), services=(Service(Consumer, consumer),), actions=activate_consumer),
        PluginProfileExtension("storage", services=(Service(Storage, storage),), actions=activate_storage),
    )).resolve(context)
    assert activated == []
    assert resolved.services.get(Storage) is storage
    assert resolved.services.get(Consumer) is consumer
    builder = ActionEngineBuilder(ActionCatalog(domains=(), actions=()))
    resolved.activate(builder)
    assert activated == ["storage", "consumer"]
    with pytest.raises(RegistrationError, match="once"):
        resolved.activate(builder)


@pytest.mark.parametrize("declarations", [
    (PluginProfileExtension("same"), PluginProfileExtension("same")),
    (PluginProfileExtension("missing", requires=(Storage,)),),
    (PluginProfileExtension("a", services=(Service(Storage, Storage()),)),
     PluginProfileExtension("b", services=(Service(Storage, Storage()),))),
    (PluginProfileExtension("a", requires=(Consumer,), services=(Service(Storage, Storage()),)),
     PluginProfileExtension("b", requires=(Storage,), services=(Service(Consumer, Consumer()),))),
])
def test_invalid_dependencies_or_identities_reject_before_activation(declarations: tuple[PluginProfileExtension, ...]) -> None:
    with pytest.raises(RegistrationError):
        PluginRegistry(declarations).resolve(ContextEngineBuilder(system_text="identity").build())


def test_reserved_segment_rejection_does_not_partially_install_other_segments() -> None:
    context = ContextEngineBuilder(system_text="identity").build()
    jobs = jobs_segment_registration()
    invalid = replace(jobs, descriptor=replace(jobs.descriptor, id="plan"))
    with pytest.raises(RegistrationError):
        PluginRegistry((PluginProfileExtension("jobs", segments=(jobs, invalid)),)).resolve(context)
    # The failed batch left no jobs identity behind.
    context.register_segment(jobs)


async def test_two_plugins_use_the_same_event_and_completion_pipeline() -> None:
    order: list[str] = []
    inbox = TurnInbox()

    class Hooks:
        def __init__(self, name: str) -> None:
            self.name = name

        async def prepare(self, request):
            order.append(f"prepare:{self.name}")
            return ()

        def adapt(self, event, scope):
            order.append(f"event:{self.name}")
            return ()

        async def handle(self, completion):
            order.append(f"complete:{self.name}")

    first, second, recorder = Hooks("first"), Hooks("second"), Hooks("recorder")
    context = ContextEngineBuilder(system_text="identity").build()
    plugins = PluginRegistry(tuple(PluginProfileExtension(
        item.name, preparation=(item,), completion=(item,),
        events=(TurnEventSubscription(EventFilter(topic=item.name), item.adapt),),
        recorder=recorder if item is first else None,
    ) for item in (first, second))).resolve(context)

    class Cycles:
        async def run(self, *, cycle_index: int, **kwargs: object) -> CycleOutcome:
            if cycle_index == 1:
                for item in (first, second):
                    await inbox.accept_event(EnvironmentEvent(EventKind.EVENT, {}, topic=item.name))
                return CycleOutcome(cycle_id="1")
            return CycleOutcome(cycle_id="2", completion={"kind": "complete"})

    runner = TurnRunner(context=context, bus=SignalBus(), trap=RuntimeTrap(registry=TrapHandlerRegistry()),
        cycle_runner=cast(CycleRunner, Cycles()), settings=TurnSettings(),
        events=plugins.events, preparation_pipeline=plugins.preparation,
        completion_pipeline=plugins.completion)
    await runner.run("work", active_day=CalendarDay.parse("2026-09-20"),
                     scope=RunScope().push(RunLevel.AGENT, "test"), inbox=inbox)
    assert order == ["prepare:first", "prepare:second", "event:first", "event:second",
                     "complete:first", "complete:second", "complete:recorder"]
