"""Build the complete User Turn mainline from typed module facades."""

from __future__ import annotations

from dataclasses import replace

from tinysoul.kernel.action import LoadedActionCatalog
from tinysoul.kernel.context import ContextSettings
from tinysoul.plugins.home import (
    HomeDomainSkillProvider,
)
from tinysoul.kernel.loop.assembly import (
    TurnProfile,
    build_turn_context,
    build_turn_kernel,
)
from tinysoul.kernel.loop.lifecycle.completion import (
    TurnCompletionHandler,
)
from tinysoul.kernel.registration import ProfileKind
from tinysoul.kernel.loop.config import LoopSettings
from tinysoul.kernel.loop.prompts import DomainSkillProvider
from tinysoul.runtime import ObservationEmitter, SignalBus
from tinysoul.plugins.home.runtime_bridge import RuntimeAgentHomeBridge

from tinysoul.kernel.loop.phases import LLMRunner
from ..composition.actions import ProfileAssembly
from tinysoul.kernel.loop.lifecycle.completion import AnswerCompletionDetector
from .completion import user_output_from_completion
from tinysoul.plugins.home.services import HomeService
from .entry import UserTurnEntry
from .prompts import USER_TURN_GUIDANCE
from .runtime import build_user_turn_trap


class UserTurnBuilder:
    """Own User Context, Action and Turn runtime composition."""

    def __init__(
        self,
        *,
        context_settings: ContextSettings,
        loop_settings: LoopSettings,
        llm: LLMRunner,
        bus: SignalBus,
        observations: ObservationEmitter,
        action_catalog: LoadedActionCatalog,
        action_assembly: ProfileAssembly,
    ) -> None:
        self._context_settings = context_settings
        self._loop_settings = loop_settings
        self._action_catalog = action_catalog
        self._action_assembly = action_assembly
        self._llm = llm
        self._bus = bus
        self._observations = observations
        self._domain_skills: DomainSkillProvider | None = None
        self._completion_handlers: list[TurnCompletionHandler] = []

    def with_domain_skills(
        self, domain_skills: DomainSkillProvider
    ) -> "UserTurnBuilder":
        self._domain_skills = domain_skills
        return self

    def add_completion_handler(
        self,
        handler: TurnCompletionHandler,
    ) -> "UserTurnBuilder":
        self._completion_handlers.append(handler)
        return self

    def build(self) -> UserTurnEntry:
        context = build_turn_context(self._context_settings, self._observations)
        builder, process_jobs, plugins = self._action_assembly.prepare(
            context, self._action_catalog, kind=ProfileKind.USER,
        )
        domain_skills = self._domain_skills or HomeDomainSkillProvider(
            plugins.services.get(HomeService),
            runtime_bridge=RuntimeAgentHomeBridge(),
        )
        action = builder.with_scenario("user").build()

        trap = build_user_turn_trap(
            context=context,
            plugins=plugins,
        )
        profile = TurnProfile(
            kind=ProfileKind.USER,
            context=context,
            action=action,
            services=plugins.services,
            trap=trap,
            settings=self._loop_settings.user,
            cycle_settings=self._loop_settings.cycle,
            turn_guidance=USER_TURN_GUIDANCE,
            completion_detector=AnswerCompletionDetector(),
            completion_to_output=user_output_from_completion,
            domain_skills=domain_skills,
            preparation_pipeline=plugins.preparation,
            completion_pipeline=replace(
                plugins.completion,
                handlers=(*plugins.completion.handlers, *self._completion_handlers),
            ),
            events=plugins.events,
            activity_controller=process_jobs,
        )
        runner = build_turn_kernel(
            profile=profile,
            llm=self._llm,
            bus=self._bus,
            observations=self._observations,
        )
        return UserTurnEntry(runner, profile=profile)
