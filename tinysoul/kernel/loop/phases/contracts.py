"""Loop phase execution units."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from tinysoul.kernel.action import ActionNormalization, ActionPhaseResult, ActionResult
from tinysoul.kernel.context import ControlResult
from tinysoul.infra.json import JsonObject
from tinysoul.llm.protocol.requests import TaskCall
from tinysoul.llm.protocol.responses import TaskResult
from tinysoul.runtime import CyclePhase

from ..errors import LoopContractError
from ..lifecycle.completion import WaitRequest
from ..interaction.inbox import QuestionRequest


class LLMRunner(Protocol):
    """The LLM runner surface needed by loop phases."""

    async def run(self, call: TaskCall) -> TaskResult:
        """Run one LLM task call."""
        ...


@dataclass(frozen=True)
class PhaseFailure:
    """A model-correctable failure at a framework phase boundary."""

    phase: CyclePhase
    reason: str
    feedback: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.phase, CyclePhase):
            raise LoopContractError("PhaseFailure.phase must be a CyclePhase")
        if not self.reason:
            raise LoopContractError("PhaseFailure.reason must be non-empty")
        if any(not isinstance(item, str) or not item for item in self.feedback):
            raise LoopContractError(
                "PhaseFailure.feedback must contain non-empty strings"
            )
        object.__setattr__(self, "feedback", tuple(self.feedback))


@dataclass(frozen=True)
class Phase1Outcome:
    """Phase1 selected domains and local control feedback."""

    selected_domains: tuple[str, ...]
    control_results: tuple[ControlResult, ...] = field(default_factory=tuple)
    attempts: int = 1
    failure: PhaseFailure | None = None


@dataclass(frozen=True)
class Phase2Outcome:
    """Phase2 normalized action calls and local phase feedback."""

    normalization: ActionNormalization
    phase_results: tuple[ActionPhaseResult, ...] = field(default_factory=tuple)
    attempts: int = 1
    failure: PhaseFailure | None = None


@dataclass(frozen=True)
class Phase3Outcome:
    """Phase3 action results when the phase does not complete the Turn."""

    results: tuple[ActionResult, ...] = field(default_factory=tuple)
    phase_results: tuple[ActionPhaseResult, ...] = field(default_factory=tuple)
    completion: JsonObject | None = None
    question: QuestionRequest | None = None
    wait: WaitRequest | None = None
    failure: PhaseFailure | None = None


class TurnCompletionDetector(Protocol):
    """Detect a successful Turn completion from Phase3 action results."""

    def detect(self, results: tuple[ActionResult, ...]) -> JsonObject | None: ...


class NoTurnCompletionDetector:
    def detect(self, results: tuple[ActionResult, ...]) -> JsonObject | None:
        return None
