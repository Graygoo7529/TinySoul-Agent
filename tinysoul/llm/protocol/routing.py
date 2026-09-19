"""Model chain routing, retry, and switching."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypeVar

from ..errors import LLMContractError
from ..protocol.requests import CallSettings

T = TypeVar("T")


class ChainErrorDisposition(StrEnum):
    """How a model-chain call should handle one model failure."""

    ABORT = "abort"
    SWITCH = "switch"
    RETRY_NEXT_CYCLE = "retry_next_cycle"


@dataclass(frozen=True)
class RetryPolicy:
    """Retry and wait policy for a model chain."""

    max_retries_per_provider: int = 1
    retry_wait_seconds: float = 0.0
    provider_switch_wait_seconds: float = 0.0
    model_switch_wait_seconds: float = 0.0
    max_cycles: int | None = 10
    prefer_successful_provider_seconds: float = 600.0
    prefer_successful_model_seconds: float = 600.0

    def __post_init__(self) -> None:
        _require_non_negative_int(
            self.max_retries_per_provider,
            name="max_retries_per_provider",
        )
        _require_optional_positive_int(self.max_cycles, name="max_cycles")
        for name, value in (
            ("retry_wait_seconds", self.retry_wait_seconds),
            ("provider_switch_wait_seconds", self.provider_switch_wait_seconds),
            ("model_switch_wait_seconds", self.model_switch_wait_seconds),
            (
                "prefer_successful_provider_seconds",
                self.prefer_successful_provider_seconds,
            ),
            (
                "prefer_successful_model_seconds",
                self.prefer_successful_model_seconds,
            ),
        ):
            object.__setattr__(
                self,
                name,
                _require_finite_non_negative_number(value, name=name),
            )


def _require_non_negative_int(value: object, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LLMContractError(f"{name} must be a non-negative integer")


def _require_optional_positive_int(value: object, *, name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LLMContractError(f"{name} must be None or a positive integer")


def _require_finite_non_negative_number(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LLMContractError(f"{name} must be a finite non-negative number")
    try:
        normalized = float(value)
    except OverflowError as exc:
        raise LLMContractError(f"{name} must be a finite non-negative number") from exc
    if not math.isfinite(normalized) or normalized < 0:
        raise LLMContractError(f"{name} must be a finite non-negative number")
    return normalized


@dataclass(frozen=True)
class ModelChain:
    """An ordered model chain for a task profile."""

    profile: str
    model_ids: tuple[str, ...]
    retry_policy: RetryPolicy = RetryPolicy()

    def __post_init__(self) -> None:
        if not isinstance(self.profile, str) or not self.profile:
            raise LLMContractError("profile must be non-empty")
        try:
            model_ids = tuple(self.model_ids)
        except TypeError as exc:
            raise LLMContractError("model_ids must be an iterable of strings") from exc
        if not model_ids:
            raise LLMContractError("model_ids must be non-empty")
        if any(not isinstance(model_id, str) or not model_id for model_id in model_ids):
            raise LLMContractError("model_ids must contain non-empty strings")
        if len(set(model_ids)) != len(model_ids):
            raise LLMContractError("model_ids must be unique")
        if not isinstance(self.retry_policy, RetryPolicy):
            raise LLMContractError("retry_policy must be a RetryPolicy")
        object.__setattr__(self, "model_ids", model_ids)


@dataclass(frozen=True)
class TaskSpec:
    """Configured LLM task behavior."""

    profile: str
    chain: ModelChain
    settings: CallSettings = field(default_factory=CallSettings)

    def __post_init__(self) -> None:
        if not isinstance(self.profile, str) or not self.profile:
            raise LLMContractError("TaskSpec.profile must be non-empty")
        if not isinstance(self.chain, ModelChain):
            raise LLMContractError("TaskSpec.chain must be a ModelChain")
        if self.chain.profile != self.profile:
            raise LLMContractError("TaskSpec.profile must match ModelChain.profile")
        if not isinstance(self.settings, CallSettings):
            raise LLMContractError("TaskSpec.settings must be CallSettings")
