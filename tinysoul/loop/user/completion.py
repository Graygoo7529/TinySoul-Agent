"""User Turn completion policy."""

from __future__ import annotations

from tinysoul.action import ActionResult, ActionResultStatus
from tinysoul.infra.json import JsonObject

from ..errors import LoopContractError
from ..signals import TurnOutput

USER_ANSWER_COMPLETION = "user_answer"


class UserAnswerCompletionDetector:
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
            "kind": USER_ANSWER_COMPLETION,
            "result_id": result.result_id,
            "text": text,
            "references": references,
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
        references=tuple(
            reference for reference in references if isinstance(reference, str)
        ),
        metadata={"action": "core.answer"},
    )
