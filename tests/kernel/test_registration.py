"""Plugin resolution must fail before any contribution is activated."""

from dataclasses import replace

import pytest

from tinysoul.kernel.action import ActionCatalog, ActionEngineBuilder
from tinysoul.kernel.context import ContextEngineBuilder
from tinysoul.kernel.jobs import jobs_segment_registration
from tinysoul.kernel.registration import PluginDeclaration, PluginRegistry, RegistrationError, Service


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
