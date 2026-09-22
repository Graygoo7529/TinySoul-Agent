"""Owner-neutral assembly for one reusable Turn kernel."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .errors import LoopContractError

from tinysoul.kernel.action import ActionEngine
from tinysoul.kernel.context import ContextEngine, ContextEngineBuilder, ContextSettings
from tinysoul.kernel.context.errors import ContextError
from tinysoul.kernel.context.runtime_bridge import RuntimeContextBridge
from tinysoul.infra.config import ConfigError
from tinysoul.kernel.registration import ProfileKind, ServiceRegistry
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import (
    NullObservationEmitter,
    ObservationEmitter,
    RuntimeModuleRunner,
    RuntimeTrap,
    SignalBus,
)

from .lifecycle.completion import TurnCompletionPipeline
from .config import CycleSettings, TurnSettings
from .context_signals import ContextSignalConsumer
from .cycle import CycleRunner
from .outcomes import TurnOutput
from .phases import (
    LLMRunner,
    Phase1Unit,
    Phase2Unit,
    Phase3Unit,
    TurnCompletionDetector,
)
from .lifecycle.preparation import TurnPreparationPipeline
from .prompts import DomainSkillProvider, EmptyDomainSkillProvider
from .turn import TurnActivityController, TurnRunner
from .interaction.events import TurnEventSubscription


@dataclass(frozen=True)
class TurnProfile:
    """One declared policy and capability surface for the shared Turn kernel."""

    kind: ProfileKind
    context: ContextEngine
    action: ActionEngine
    services: ServiceRegistry
    trap: RuntimeTrap
    settings: TurnSettings
    cycle_settings: CycleSettings
    turn_guidance: tuple[str, ...]
    completion_detector: TurnCompletionDetector
    preparation_pipeline: TurnPreparationPipeline | None = None
    completion_pipeline: TurnCompletionPipeline | None = None
    completion_to_output: Callable[[JsonObject | None], TurnOutput | None] | None = None
    domain_skills: DomainSkillProvider | None = None
    activity_controller: TurnActivityController | None = None
    events: tuple[TurnEventSubscription, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ProfileKind):
            raise LoopContractError("Turn profile kind must be a ProfileKind")
        if not isinstance(self.context, ContextEngine) or not isinstance(
            self.action, ActionEngine
        ):
            raise LoopContractError(
                "Turn profile requires assembled Context and Action facades"
            )
        if not isinstance(self.settings, TurnSettings) or not isinstance(
            self.cycle_settings, CycleSettings
        ):
            raise LoopContractError("Turn profile settings must be typed")
        if any(not isinstance(line, str) or not line for line in self.turn_guidance):
            raise LoopContractError("Turn guidance must contain non-empty text")
        object.__setattr__(self, "turn_guidance", tuple(self.turn_guidance))


def build_turn_context(
    settings: ContextSettings, observations: ObservationEmitter
) -> ContextEngine:
    """Build core views before domain declarations are resolved."""
    bridge = RuntimeContextBridge()
    try:
        return (
            ContextEngineBuilder.from_settings(settings)
            .with_observations(observations)
            .build()
        )
    except ConfigError as exc:
        raise bridge.from_config_error(exc) from exc
    except ContextError as exc:
        raise bridge.startup_failure(
            message="Turn Context could not be initialized.",
            payload={"error_type": type(exc).__name__},
        ) from exc


def build_turn_kernel(
    *,
    profile: TurnProfile,
    llm: LLMRunner,
    bus: SignalBus,
    observations: ObservationEmitter | None = None,
) -> TurnRunner:
    """Compose the declared profile using the only Turn/Cycle/Phase engine."""

    emitter = observations or NullObservationEmitter()
    recovery_consumer = ContextSignalConsumer(context=profile.context, bus=bus)
    module_runner = RuntimeModuleRunner(
        trap=profile.trap,
        bus=bus,
        observations=emitter,
        consume_recovery_signals=recovery_consumer.consume_recovery,
    )
    signal_consumer = ContextSignalConsumer(
        context=profile.context,
        bus=bus,
        module_runner=module_runner,
    )
    phase1 = Phase1Unit(
        context=profile.context,
        action=profile.action,
        llm=llm,
        bus=bus,
        task_profile=profile.cycle_settings.phase1_task_profile,
        signal_consumer=signal_consumer,
        turn_guidance=profile.turn_guidance,
    )
    phase2 = Phase2Unit(
        context=profile.context,
        action=profile.action,
        llm=llm,
        bus=bus,
        task_profile=profile.cycle_settings.phase2_task_profile,
        domain_skills=profile.domain_skills or EmptyDomainSkillProvider(),
        signal_consumer=signal_consumer,
        observations=emitter,
        turn_guidance=profile.turn_guidance,
    )
    phase3 = Phase3Unit(
        context=profile.context,
        action=profile.action,
        bus=bus,
        module_runner=module_runner,
        signal_consumer=signal_consumer,
        observations=emitter,
        completion_detector=profile.completion_detector,
    )
    cycle = CycleRunner(
        context=profile.context,
        bus=bus,
        trap=profile.trap,
        phase1=phase1,
        phase2=phase2,
        phase3=phase3,
        signal_consumer=signal_consumer,
        observations=emitter,
    )
    return TurnRunner(
        context=profile.context,
        bus=bus,
        trap=profile.trap,
        cycle_runner=cycle,
        settings=profile.settings,
        completion_to_output=profile.completion_to_output,
        signal_consumer=signal_consumer,
        completion_pipeline=profile.completion_pipeline,
        preparation_pipeline=profile.preparation_pipeline,
        activity_controller=profile.activity_controller,
        events=profile.events,
        observations=emitter,
    )
