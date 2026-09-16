"""User Turn completion policy."""

from __future__ import annotations

from tinysoul.infra.json import JsonObject

from tinysoul.kernel.loop.errors import LoopContractError
from tinysoul.kernel.loop.outcomes import TurnOutput

def user_output_from_completion(value: JsonObject | None) -> TurnOutput | None:
    if value is None or value.get("kind") != "answer":
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
