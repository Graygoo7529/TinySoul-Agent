"""Turn completion records and post-Turn processing pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Protocol

from tinysoul.kernel.action import ActionResult, ActionResultStatus
from tinysoul.kernel.context import ContextTurnCompletion
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import CalendarDay
from tinysoul.runtime import RuntimeException, RuntimeTransferInterrupt

from .errors import LoopContractError, LoopInvariantError
from .outcomes import TurnFailure, TurnOutcomeStatus, TurnOutput
from .runtime_bridge import RuntimeLoopBridge
from .inbox import InboxError, QuestionRequest


@dataclass(frozen=True)
class TurnCompletion:
    """Stable data passed to ordered post-Turn services such as Session."""

    context_completion: ContextTurnCompletion
    business_day: CalendarDay
    status: TurnOutcomeStatus
    output: TurnOutput | None = None
    exhausted: bool = False
    completion: JsonObject | None = None
    failure: TurnFailure | None = None
    finish_failures: tuple[TurnFailure, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.business_day, CalendarDay):
            raise LoopContractError(
                "TurnCompletion.business_day must be a CalendarDay"
            )
        if not isinstance(self.exhausted, bool):
            raise LoopContractError("TurnCompletion.exhausted must be a boolean")
        if not isinstance(self.status, TurnOutcomeStatus):
            raise LoopContractError("TurnCompletion requires an execution status")
        if (self.status is TurnOutcomeStatus.FAILED) != (self.failure is not None):
            raise LoopContractError("TurnCompletion failure and status disagree")
        if any(not isinstance(item, TurnFailure) for item in self.finish_failures):
            raise LoopContractError("TurnCompletion requires typed finish failures")

    @property
    def final_status(self) -> TurnOutcomeStatus:
        return TurnOutcomeStatus.FAILED if self.finish_failures else self.status


class TurnCompletionHandler(Protocol):
    """One ordered post-Turn side effect."""

    async def handle(self, completion: TurnCompletion) -> None:
        """Process a completed Turn or raise a mapped RuntimeException."""
        ...


@dataclass(frozen=True)
class TurnCompletionPipeline:
    """Finish dependent owners, then record even a failed finish exactly once."""

    handlers: tuple[TurnCompletionHandler, ...] = field(default_factory=tuple)
    recorder: TurnCompletionHandler | None = None

    async def run(
        self,
        completion: TurnCompletion,
        *,
        capture_failure: Callable[[RuntimeException | RuntimeTransferInterrupt], TurnFailure],
    ) -> TurnCompletion:
        for handler in self.handlers:
            failure = await self._run_handler(handler, completion, capture_failure)
            if failure is not None:
                completion = replace(completion, finish_failures=(failure,))
                break
        if self.recorder is not None:
            failure = await self._run_handler(self.recorder, completion, capture_failure)
            if failure is not None:
                completion = replace(
                    completion, finish_failures=(*completion.finish_failures, failure)
                )
        return completion

    @staticmethod
    async def _run_handler(
        handler: TurnCompletionHandler,
        completion: TurnCompletion,
        capture_failure: Callable[[RuntimeException | RuntimeTransferInterrupt], TurnFailure],
    ) -> TurnFailure | None:
        try:
            await handler.handle(completion)
        except (RuntimeException, RuntimeTransferInterrupt) as exc:
            return capture_failure(exc)
        except (Exception, asyncio.CancelledError) as exc:
            # An owner must map its own environmental failures before returning.
            mapped = RuntimeLoopBridge().from_loop_error(
                LoopInvariantError("Turn completion handler violated its failure contract"),
                payload={"error_type": type(exc).__name__},
            )
            return capture_failure(mapped)
        return None



def question_from_results(results: tuple[ActionResult, ...]) -> QuestionRequest | None:
    questions = [result for result in results
                 if result.action_name == "core.ask" and result.status is ActionResultStatus.SUCCESS]
    if not questions:
        return None
    if len(questions) != 1:
        raise LoopContractError("Question detection requires one validated intent")
    result = questions[0]
    text = result.payload.get("text")
    options = result.payload.get("options", [])
    timeout = result.payload.get("timeout_seconds")
    if (not isinstance(text, str) or not isinstance(options, list)
            or any(not isinstance(item, str) for item in options)
            or (timeout is not None and type(timeout) not in (int, float))):
        raise LoopContractError("Successful question result violated its contract")
    try:
        return QuestionRequest(result.result_id, text,
                               tuple(item for item in options if isinstance(item, str)),
                               float(timeout) if isinstance(timeout, (int, float)) else None)
    except InboxError as exc:
        raise LoopContractError("Successful question result violated its contract") from exc


class AnswerCompletionDetector:
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
                "A Turn cycle produced multiple successful core.answer results"
            )
        result = answers[0]
        text = result.payload.get("text")
        references = result.payload.get("references", [])
        if not isinstance(text, str) or not text:
            raise LoopContractError(
                "A successful core.answer result must contain non-empty text"
            )
        if not isinstance(references, list) or any(
            not isinstance(item, str) or not item for item in references
        ):
            raise LoopContractError(
                "A successful core.answer result must contain string references"
            )
        return {
            "kind": "answer",
            "result_id": result.result_id,
            "text": text,
            "references": references,
        }
