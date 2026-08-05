"""Owner-neutral assembly for one reusable Turn kernel."""

from __future__ import annotations

from collections.abc import Callable

from tinysoul.action import ActionEngine
from tinysoul.context import ContextEngine
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import (
    NullObservationEmitter,
    ObservationEmitter,
    RuntimeModuleRunner,
    RuntimeTrap,
    SignalBus,
)

from .completion import TurnCompletionPipeline
from .config import TurnSettings
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
from .preparation import TurnPreparationPipeline
from .prompts import DomainSkillProvider, EmptyDomainSkillProvider
from .turn import TurnActivityController, TurnRunner


def build_turn_kernel(
    *,
    context: ContextEngine,
    action: ActionEngine,
    llm: LLMRunner,
    bus: SignalBus,
    trap: RuntimeTrap,
    settings: TurnSettings,
    phase_retry_limit: int,
    turn_guidance: tuple[str, ...],
    completion_detector: TurnCompletionDetector,
    preparation_pipeline: TurnPreparationPipeline | None = None,
    completion_pipeline: TurnCompletionPipeline | None = None,
    completion_to_output: Callable[[JsonObject | None], TurnOutput | None] | None = None,
    domain_skills: DomainSkillProvider | None = None,
    activity_controller: TurnActivityController | None = None,
    observations: ObservationEmitter | None = None,
) -> TurnRunner:
    """Compose Context, Action and LLM facades into one TurnRunner."""

    emitter = observations or NullObservationEmitter()
    module_runner = RuntimeModuleRunner(
        trap=trap,
        bus=bus,
        observations=emitter,
    )
    signal_consumer = ContextSignalConsumer(
        context=context,
        bus=bus,
        module_runner=module_runner,
    )
    phase1 = Phase1Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        retry_limit=phase_retry_limit,
        signal_consumer=signal_consumer,
        turn_guidance=turn_guidance,
    )
    phase2 = Phase2Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        retry_limit=phase_retry_limit,
        domain_skills=domain_skills or EmptyDomainSkillProvider(),
        signal_consumer=signal_consumer,
        observations=emitter,
        turn_guidance=turn_guidance,
    )
    phase3 = Phase3Unit(
        context=context,
        action=action,
        bus=bus,
        module_runner=module_runner,
        signal_consumer=signal_consumer,
        observations=emitter,
        completion_detector=completion_detector,
    )
    cycle = CycleRunner(
        context=context,
        bus=bus,
        trap=trap,
        phase1=phase1,
        phase2=phase2,
        phase3=phase3,
        signal_consumer=signal_consumer,
        observations=emitter,
    )
    return TurnRunner(
        context=context,
        bus=bus,
        trap=trap,
        cycle_runner=cycle,
        settings=settings,
        completion_to_output=completion_to_output,
        signal_consumer=signal_consumer,
        completion_pipeline=completion_pipeline,
        preparation_pipeline=preparation_pipeline,
        activity_controller=activity_controller,
        observations=emitter,
    )
