"""Owner-neutral Context pressure recovery contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from tinysoul.infra.json import JsonValue
from tinysoul.runtime import RunScope


class PressureRecoveryStatus(StrEnum):
    RECOVERED = "recovered"
    NO_PROGRESS = "no_progress"
    FAILED = "failed"


@dataclass(frozen=True)
class PressureRecoveryResult:
    status: PressureRecoveryStatus
    reclaimed_chars: int
    evicted_background_links: tuple[str, ...] = field(default_factory=tuple)
    trashed_refs: tuple[str, ...] = field(default_factory=tuple)
    error: str = ""

    @property
    def changed(self) -> bool:
        return self.status is PressureRecoveryStatus.RECOVERED


class PressureRecovery(Protocol):
    def recover(
        self,
        *,
        payload: Mapping[str, JsonValue],
        scope: RunScope,
    ) -> PressureRecoveryResult: ...


def required_chars(
    payload: Mapping[str, JsonValue],
    *,
    target_ratio: float,
) -> int:
    model_required = _model_required_chars(payload, target_ratio=target_ratio)
    if model_required is not None:
        return model_required
    if _image_budget_exceeded(payload):
        return 0
    estimated = payload.get("estimated_chars")
    maximum = payload.get("max_chars")
    if (
        isinstance(estimated, int)
        and not isinstance(estimated, bool)
        and isinstance(maximum, int)
        and not isinstance(maximum, bool)
        and maximum > 0
    ):
        if estimated <= maximum:
            return 0
        target = int(maximum * target_ratio)
        return max(1, estimated - target)
    return 1


def _image_budget_exceeded(payload: Mapping[str, JsonValue]) -> bool:
    estimated = _non_negative_int(payload.get("estimated_image_bytes"))
    maximum = _non_negative_int(payload.get("max_image_bytes"), positive=True)
    return estimated is not None and maximum is not None and estimated > maximum


def _model_required_chars(
    payload: Mapping[str, JsonValue],
    *,
    target_ratio: float,
) -> int | None:
    window = _non_negative_int(payload.get("context_window_tokens"), positive=True)
    message_tokens = _non_negative_int(payload.get("estimated_message_tokens"))
    non_message_tokens = _non_negative_int(
        payload.get("estimated_non_message_tokens")
    )
    output_tokens = _non_negative_int(payload.get("reserved_output_tokens"))
    message_chars = _non_negative_int(payload.get("estimated_message_chars"))
    if None in (
        window,
        message_tokens,
        non_message_tokens,
        output_tokens,
        message_chars,
    ):
        return None
    assert window is not None
    assert message_tokens is not None
    assert non_message_tokens is not None
    assert output_tokens is not None
    assert message_chars is not None
    target_total_tokens = int(window * target_ratio)
    target_message_tokens = max(
        0,
        target_total_tokens - non_message_tokens - output_tokens,
    )
    reclaim_tokens = max(0, message_tokens - target_message_tokens)
    if reclaim_tokens <= 0 or message_tokens <= 0 or message_chars <= 0:
        return 1
    return max(
        1,
        (message_chars * reclaim_tokens + message_tokens - 1) // message_tokens,
    )


def _non_negative_int(
    value: JsonValue | None,
    *,
    positive: bool = False,
) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or (positive and value <= 0):
        return None
    return value
