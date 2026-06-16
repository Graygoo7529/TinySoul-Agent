"""Model chain routing, retry, and switching."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import time
from typing import Callable, TypeVar

T = TypeVar("T")


class TaskProfile(StrEnum):
    """Built-in LLM task profiles."""

    FRAMEWORK_DEFAULT = "framework.default"
    ACTION_BEHAVIOR = "action.behavior"


@dataclass(frozen=True)
class RetryPolicy:
    """Retry and wait policy for a model chain."""

    max_retries_per_model: int = 1
    retry_wait_seconds: float = 0.0
    switch_wait_seconds: float = 0.0
    max_cycles: int | None = 10
    prefer_successful_model_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.max_retries_per_model < 1:
            raise ValueError("max_retries_per_model must be at least 1")
        if self.retry_wait_seconds < 0:
            raise ValueError("retry_wait_seconds cannot be negative")
        if self.switch_wait_seconds < 0:
            raise ValueError("switch_wait_seconds cannot be negative")
        if self.max_cycles is not None and self.max_cycles < 1:
            raise ValueError("max_cycles must be None or at least 1")
        if (
            self.prefer_successful_model_seconds is not None
            and self.prefer_successful_model_seconds < 0
        ):
            raise ValueError("prefer_successful_model_seconds cannot be negative")


@dataclass(frozen=True)
class ModelChain:
    """An ordered model chain for a task profile."""

    profile: str
    model_ids: tuple[str, ...]
    retry_policy: RetryPolicy = RetryPolicy()

    def __post_init__(self) -> None:
        if not self.profile:
            raise ValueError("profile must be non-empty")
        if not self.model_ids:
            raise ValueError("model_ids must be non-empty")


class ModelChainTable:
    """Registry of model chains by task profile."""

    def __init__(self, chains: list[ModelChain] | None = None) -> None:
        self._chains: dict[str, ModelChain] = {}
        for chain in chains or []:
            self.register(chain)

    def register(self, chain: ModelChain) -> None:
        if chain.profile in self._chains:
            raise ValueError(f"Model chain already registered: {chain.profile}")
        self._chains[chain.profile] = chain

    def get(self, profile: TaskProfile | str) -> ModelChain:
        profile_name = profile.value if isinstance(profile, TaskProfile) else profile
        try:
            return self._chains[profile_name]
        except KeyError as exc:
            raise KeyError(f"Unknown task profile: {profile_name}") from exc


class ModelChainState:
    """Mutable current-position state for model chains."""

    def __init__(self) -> None:
        self._indices: dict[str, int] = {}
        self._success_times: dict[str, float] = {}

    def current_index(self, chain: ModelChain, *, now: float) -> int:
        if self._should_return_to_head(chain, now=now):
            self.reset(chain.profile)
            return 0
        index = self._indices.get(chain.profile, 0)
        if index >= len(chain.model_ids):
            return 0
        return index

    def mark_success(self, chain: ModelChain, model_id: str, *, now: float) -> None:
        previous_index = self._indices.get(chain.profile)
        index = chain.model_ids.index(model_id)
        self._indices[chain.profile] = index
        if index == 0:
            self._success_times.pop(chain.profile, None)
        elif previous_index != index or chain.profile not in self._success_times:
            self._success_times[chain.profile] = now

    def reset(self, profile: TaskProfile | str | None = None) -> None:
        if profile is None:
            self._indices.clear()
            self._success_times.clear()
            return
        profile_name = profile.value if isinstance(profile, TaskProfile) else profile
        self._indices.pop(profile_name, None)
        self._success_times.pop(profile_name, None)

    def _should_return_to_head(self, chain: ModelChain, *, now: float) -> bool:
        seconds = chain.retry_policy.prefer_successful_model_seconds
        if seconds is None:
            return False
        index = self._indices.get(chain.profile, 0)
        if index == 0:
            return False
        success_time = self._success_times.get(chain.profile)
        if success_time is None:
            return False
        return now - success_time >= seconds


class ModelChainPlanner:
    """Produce model attempt sequences for a chain."""

    def model_order(self, chain: ModelChain, *, start_index: int) -> tuple[str, ...]:
        if start_index < 0 or start_index >= len(chain.model_ids):
            raise ValueError("start_index must point to a model in the chain")
        return chain.model_ids[start_index:]


class Sleeper:
    """Sleep boundary for retry tests."""

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


class Clock:
    """Time boundary for model chain state tests."""

    def now(self) -> float:
        return time.monotonic()


class ModelChainRunner:
    """Run a model chain with retry and switching policy."""

    def __init__(
        self,
        *,
        state: ModelChainState | None = None,
        planner: ModelChainPlanner | None = None,
        sleeper: Sleeper | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._state = state or ModelChainState()
        self._planner = planner or ModelChainPlanner()
        self._sleeper = sleeper or Sleeper()
        self._clock = clock or Clock()

    def run(
        self,
        chain: ModelChain,
        attempt: Callable[[str], T],
        *,
        is_fatal: Callable[[Exception], bool],
    ) -> T:
        start_index = self._state.current_index(chain, now=self._clock.now())
        cycles = 0
        last_error: Exception | None = None

        while chain.retry_policy.max_cycles is None or cycles < chain.retry_policy.max_cycles:
            cycles += 1
            for model_id in self._planner.model_order(chain, start_index=start_index):
                try:
                    result = attempt(model_id)
                except Exception as exc:
                    if is_fatal(exc):
                        raise
                    last_error = exc
                    self._sleeper.sleep(chain.retry_policy.switch_wait_seconds)
                    continue

                self._state.mark_success(chain, model_id, now=self._clock.now())
                return result

            start_index = 0

        raise ModelChainExhaustedError("Model chain exhausted") from last_error

    def reset(self, profile: TaskProfile | str | None = None) -> None:
        self._state.reset(profile)


class ModelChainExhaustedError(Exception):
    """Raised when a model chain cannot produce a result."""
