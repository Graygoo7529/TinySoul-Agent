"""Reflection semantics over the common profile contribution path."""

from typing import Protocol

from tinysoul.prompts.plugins import reflection as prompt_text
from tinysoul.kernel.action import ActionEngine, ActionEngineBuilder, LoadedActionCatalog
from tinysoul.kernel.action.catalog.specs import ActionSemanticSpec
from tinysoul.kernel.context import ContextEngine
from tinysoul.kernel.registration import ProfileKind, ResolvedProfileExtensions, ServiceRegistry
from tinysoul.kernel.loop.turn import TurnActivityController


class ProfileAssemblyPort(Protocol):
    def prepare(
        self, context: ContextEngine, catalog: LoadedActionCatalog, *,
        kind: ProfileKind, bindings: ServiceRegistry | None = None,
    ) -> tuple[ActionEngineBuilder, TurnActivityController, ResolvedProfileExtensions]: ...


def build_reflection_action(
    *, kind: ProfileKind, context: ContextEngine, action_catalog: LoadedActionCatalog,
    assembly: ProfileAssemblyPort, bindings: ServiceRegistry | None = None,
) -> tuple[ActionEngine, TurnActivityController, ResolvedProfileExtensions]:
    builder, jobs, services = assembly.prepare(context, action_catalog, kind=kind, bindings=bindings)
    builder.with_action_semantics(
        "core.answer",
        description=prompt_text.ANSWER_DESCRIPTION,
        semantic=ActionSemanticSpec(
            use_when=(prompt_text.ANSWER_USE_WHEN,),
            avoid_when=(prompt_text.ANSWER_AVOID_WHEN,),
        ),
    )
    return builder.with_scenario(kind.value).build(), jobs, services
