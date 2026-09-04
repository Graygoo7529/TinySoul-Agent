"""Model chain routing, retry, and switching."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import time
from typing import Callable, TypeVar

from .errors import LLMContractError, LLMInvariantError
from .requests import CallSettings, TaskProfile

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
        if self.max_retries_per_provider < 0:
            raise LLMContractError("max_retries_per_provider cannot be negative")
        if self.retry_wait_seconds < 0:
            raise LLMContractError("retry_wait_seconds cannot be negative")
        if self.provider_switch_wait_seconds < 0:
            raise LLMContractError("provider_switch_wait_seconds cannot be negative")
        if self.model_switch_wait_seconds < 0:
            raise LLMContractError("model_switch_wait_seconds cannot be negative")
        if self.max_cycles is not None and self.max_cycles < 1:
            raise LLMContractError("max_cycles must be None or at least 1")
        if self.prefer_successful_provider_seconds < 0:
            raise LLMContractError("prefer_successful_provider_seconds cannot be negative")
        if self.prefer_successful_model_seconds < 0:
            raise LLMContractError("prefer_successful_model_seconds cannot be negative")


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


class TaskSpecTable:
    """Registry of configured LLM tasks."""

    def __init__(self, specs: list[TaskSpec] | None = None) -> None:
        self._specs: dict[str, TaskSpec] = {}
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: TaskSpec) -> None:
        if spec.profile in self._specs:
            raise LLMInvariantError(f"Task already registered: {spec.profile}")
        self._specs[spec.profile] = spec

    def get(self, profile: TaskProfile | str) -> TaskSpec:
        profile_name = profile.value if isinstance(profile, TaskProfile) else profile
        try:
            return self._specs[profile_name]
        except KeyError as exc:
            raise LLMContractError(f"Unknown task profile: {profile_name}") from exc

    def profiles(self) -> tuple[str, ...]:
        """Return configured task-profile identities in stable order."""

        return tuple(sorted(self._specs))

    def has(self, profile: TaskProfile | str) -> bool:
        profile_name = profile.value if isinstance(profile, TaskProfile) else profile
        return profile_name in self._specs


class LLMRouteState:
    """Mutable model and provider success preferences for LLM routing."""

    def __init__(self) -> None:
        self._indices: dict[str, int] = {}
        self._success_times: dict[str, float] = {}
        self._provider_success: dict[tuple[str, str], tuple[str, float]] = {}

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
            self._provider_success.clear()
            return
        profile_name = profile.value if isinstance(profile, TaskProfile) else profile
        self._indices.pop(profile_name, None)
        self._success_times.pop(profile_name, None)
        for key in tuple(self._provider_success):
            if key[0] == profile_name:
                self._provider_success.pop(key, None)

    def _should_return_to_head(self, chain: ModelChain, *, now: float) -> bool:
        seconds = chain.retry_policy.prefer_successful_model_seconds
        index = self._indices.get(chain.profile, 0)
        if index == 0:
            return False
        success_time = self._success_times.get(chain.profile)
        if success_time is None:
            return False
        return now - success_time >= seconds

    def provider_order(
        self,
        profile: str,
        model_id: str,
        provider_ids: tuple[str, ...],
        *,
        now: float,
        prefer_seconds: float,
    ) -> tuple[str, ...]:
        if not provider_ids:
            return ()
        key = (profile, model_id)
        preferred = self._provider_success.get(key)
        if preferred is None or now - preferred[1] >= prefer_seconds:
            self._provider_success.pop(key, None)
            return provider_ids
        provider_id = preferred[0]
        if provider_id not in provider_ids:
            self._provider_success.pop(key, None)
            return provider_ids
        return (provider_id, *(item for item in provider_ids if item != provider_id))

    def mark_provider_success(
        self,
        profile: str,
        model_id: str,
        provider_id: str,
        provider_ids: tuple[str, ...],
        *,
        now: float,
    ) -> None:
        index = provider_ids.index(provider_id)
        key = (profile, model_id)
        if index == 0:
            self._provider_success.pop(key, None)
            return
        previous = self._provider_success.get(key)
        if previous is None or previous[0] != provider_id:
            self._provider_success[key] = (provider_id, now)


class ModelChainPlanner:
    """Produce model attempt sequences for a chain."""

    def model_order(self, chain: ModelChain, *, start_index: int) -> tuple[str, ...]:
        if start_index < 0 or start_index >= len(chain.model_ids):
            raise LLMContractError("start_index must point to a model in the chain")
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
        state: LLMRouteState | None = None,
        planner: ModelChainPlanner | None = None,
        sleeper: Sleeper | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._state = state or LLMRouteState()
        self._planner = planner or ModelChainPlanner()
        self._sleeper = sleeper or Sleeper()
        self._clock = clock or Clock()

    @property
    def state(self) -> LLMRouteState:
        return self._state

    def run(
        self,
        chain: ModelChain,
        attempt: Callable[[str], T],
        *,
        classify_error: Callable[[Exception], ChainErrorDisposition],
    ) -> T:
        start_index = self._state.current_index(chain, now=self._clock.now())
        cycles = 0
        last_error: Exception | None = None
        blocked_models: set[str] = set()
        attempted_models: set[str] = set()

        while chain.retry_policy.max_cycles is None or cycles < chain.retry_policy.max_cycles:
            cycles += 1
            retry_next_cycle = False
            order = self._planner.model_order(chain, start_index=start_index)
            for model_id in order:
                if model_id in blocked_models:
                    continue
                attempted_models.add(model_id)
                try:
                    result = attempt(model_id)
                except Exception as exc:
                    disposition = classify_error(exc)
                    if disposition is ChainErrorDisposition.ABORT:
                        raise
                    last_error = exc
                    if disposition is ChainErrorDisposition.SWITCH:
                        blocked_models.add(model_id)
                    else:
                        retry_next_cycle = True
                    self._sleeper.sleep(chain.retry_policy.model_switch_wait_seconds)
                    continue

                self._state.mark_success(chain, model_id, now=self._clock.now())
                return result

            start_index = 0
            untried_models = any(
                model_id not in attempted_models and model_id not in blocked_models
                for model_id in chain.model_ids
            )
            if not retry_next_cycle and not untried_models:
                break

        raise ModelChainExhaustedError(
            "Model chain exhausted",
            last_error=last_error,
        ) from last_error

    def reset(self, profile: TaskProfile | str | None = None) -> None:
        self._state.reset(profile)

    def current_model_id(self, chain: ModelChain) -> str:
        index = self._state.current_index(chain, now=self._clock.now())
        return chain.model_ids[index]

    def now(self) -> float:
        return self._clock.now()


class ModelChainExhaustedError(Exception):
    """Raised when a model chain cannot produce a result."""

    def __init__(
        self,
        message: str,
        *,
        last_error: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.last_error = last_error
