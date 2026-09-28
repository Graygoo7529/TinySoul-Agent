"""Bounded read projections using the existing owner-bound continuation protocol."""

from dataclasses import dataclass
from hashlib import sha256

from .continuation import (
    ContinuationError,
    ContinuationFailureReason,
    OpaqueContinuationCodec,
    continue_json_sequence,
)
from .json import JsonObject, JsonValue, dumps_json


@dataclass(frozen=True)
class PageOptions:
    continuation: str | None = None
    limit: int = 30
    max_chars: int = 16000

    def __post_init__(self) -> None:
        if (
            type(self.limit) is not int
            or not 1 <= self.limit <= 100
            or type(self.max_chars) is not int
            or not 1024 <= self.max_chars <= 64000
        ):
            raise ContinuationError(
                ContinuationFailureReason.INVALID_LIMIT,
                "Page limits are outside the supported range",
            )

    def render(
        self,
        values: tuple[JsonValue, ...],
        *,
        owner: str,
        ref: str,
        base: JsonObject | None = None,
        item_field: str = "items",
    ) -> JsonObject:
        return continue_json_sequence(
            values,
            base=base or {},
            item_field=item_field,
            codec=OpaqueContinuationCodec(owner=owner, operation="browse"),
            ref=ref,
            continuation=self.continuation,
            binding={
                "content": sha256(
                    dumps_json({"values": list(values)}).encode("utf-8")
                ).hexdigest()
            },
            max_chars=self.max_chars,
            max_items=self.limit,
        )
