"""Turn completion records and post-Turn processing pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from tinysoul.action import ActionResult, ActionResultStatus
from tinysoul.context import ContextTurnCompletion
from tinysoul.infra.json import JsonObject

from tinysoul.maintenance import BusinessDay
from .errors import LoopContractError
from .signals import TurnOutput

USER_ANSWER_COMPLETION = "user_answer"


class UserAnswerCompletionDetector:
    """Detect and validate one successful ``core.answer`` result."""

    def detect(self, results: tuple[ActionResult, ...]) -> JsonObject | None:
        answers = tuple(
            result
            for result in results
            if result.action_name == "core.answer"
            and result.status is ActionResultStatus.SUCCESS
        )
        if not answers:
            return None
        if len(answers) != 1:
            raise LoopContractError(
                "A User Turn cycle produced multiple successful core.answer results"
            )
        result = answers[0]
        text = result.payload.get("text")
        references_value = result.payload.get("references", [])
        if not isinstance(text, str) or not text:
            raise LoopContractError(
                "A successful core.answer result must contain non-empty text"
            )
        if not isinstance(references_value, list) or any(
            not isinstance(item, str) or not item for item in references_value
        ):
            raise LoopContractError(
                "A successful core.answer result must contain string references"
            )
        return {
            "kind": USER_ANSWER_COMPLETION,
            "result_id": result.result_id,
            "text": text,
            "references": references_value,
        }


def user_output_from_completion(value: JsonObject | None) -> TurnOutput | None:
    if value is None or value.get("kind") != USER_ANSWER_COMPLETION:
        return None
    text = value.get("text")
    result_id = value.get("result_id")
    references = value.get("references", [])
    if (
        not isinstance(text, str)
        or not isinstance(result_id, str)
        or not isinstance(references, list)
        or any(not isinstance(item, str) for item in references)
    ):
        raise LoopContractError("User Turn completion payload is invalid")
    return TurnOutput(
        text=text,
        result_id=result_id,
        references=tuple(item for item in references if isinstance(item, str)),
        metadata={"action": "core.answer"},
    )


@dataclass(frozen=True)
class TurnCompletion:
    """Stable data passed to ordered post-Turn services such as Session."""

    context_completion: ContextTurnCompletion
    business_day: BusinessDay
    output: TurnOutput | None = None
    exhausted: bool = False
    completion: JsonObject | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.business_day, BusinessDay):
            raise LoopContractError(
                "TurnCompletion.business_day must be a BusinessDay"
            )
        if not isinstance(self.exhausted, bool):
            raise LoopContractError("TurnCompletion.exhausted must be a boolean")


class TurnCompletionHandler(Protocol):
    """One ordered post-Turn side effect."""

    def handle(self, completion: TurnCompletion) -> None:
        """Process a completed Turn or raise a mapped RuntimeException."""
        ...


@dataclass(frozen=True)
class TurnCompletionPipeline:
    """Run post-Turn handlers in deterministic registration order."""

    handlers: tuple[TurnCompletionHandler, ...] = field(default_factory=tuple)

    def run(self, completion: TurnCompletion) -> None:
        for handler in self.handlers:
            handler.handle(completion)
