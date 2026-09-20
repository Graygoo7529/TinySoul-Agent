"""Plugin resolution must fail before any contribution is activated."""

from dataclasses import replace
from typing import cast

import pytest

from tinysoul.kernel.action import ActionCatalog, ActionEngineBuilder
from tinysoul.kernel.context import ContextEngineBuilder
from tinysoul.kernel.jobs import jobs_segment_registration
from tinysoul.kernel.registration import PluginDeclaration, PluginRegistry, RegistrationError, Service
from tinysoul.kernel.loop.interaction.events import TurnEventSubscription
from tinysoul.kernel.loop.interaction.inbox import TurnInbox
from tinysoul.kernel.loop.turn import TurnRunner
from tinysoul.kernel.loop.cycle import CycleOutcome, CycleRunner
from tinysoul.kernel.loop.config import TurnSettings
from tinysoul.infra.time import CalendarDay
from tinysoul.runtime import RunScope, RunLevel, SignalBus, RuntimeTrap, TrapHandlerRegistry
from tinysoul.runtime.events import EnvironmentEvent, EventKind, EventFilter


class Storage:
    pass


class Consumer:
    pass


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
        PluginDeclaration("consumer", requires=(Storage,), services=(Service(Consumer, consumer),), actions=activate_consumer),
        PluginDeclaration("storage", services=(Service(Storage, storage),), actions=activate_storage),
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
    (PluginDeclaration("same"), PluginDeclaration("same")),
    (PluginDeclaration("missing", requires=(Storage,)),),
    (PluginDeclaration("a", services=(Service(Storage, Storage()),)),
     PluginDeclaration("b", services=(Service(Storage, Storage()),))),
    (PluginDeclaration("a", requires=(Consumer,), services=(Service(Storage, Storage()),)),
     PluginDeclaration("b", requires=(Storage,), services=(Service(Consumer, Consumer()),))),
])
def test_invalid_dependencies_or_identities_reject_before_activation(declarations: tuple[PluginDeclaration, ...]) -> None:
    with pytest.raises(RegistrationError):
        PluginRegistry(declarations).resolve(ContextEngineBuilder(system_text="identity").build())


def test_reserved_segment_rejection_does_not_partially_install_other_segments() -> None:
    context = ContextEngineBuilder(system_text="identity").build()
    jobs = jobs_segment_registration()
    invalid = replace(jobs, descriptor=replace(jobs.descriptor, id="plan"))
    with pytest.raises(RegistrationError):
        PluginRegistry((PluginDeclaration("jobs", segments=(jobs, invalid)),)).resolve(context)
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
    plugins = PluginRegistry(tuple(PluginDeclaration(
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
