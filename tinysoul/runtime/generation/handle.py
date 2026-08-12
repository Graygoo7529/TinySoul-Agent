"""Stable, generic handle for the currently active runtime generation."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from threading import Condition, RLock
from typing import Generic, TypeVar
from uuid import uuid4

from .activity import RuntimeActivationState, RuntimeActivity

T = TypeVar("T")


class RuntimeGenerationError(RuntimeError):
    """Invalid generation lifecycle operation."""


@dataclass(frozen=True)
class RuntimeGenerationSnapshot(Generic[T]):
    generation: T
    generation_id: str
    activity: RuntimeActivity
    activation: RuntimeActivationState


class RuntimeGenerationLease(AbstractContextManager[T], Generic[T]):
    def __init__(self, handle: "RuntimeHandle[T]") -> None:
        self._handle = handle
        self._generation: T | None = None

    def __enter__(self) -> T:
        self._generation = self._handle._acquire_reader()
        return self._generation

    def __exit__(self, exception_type, exception, traceback) -> None:
        self._handle._release_reader()
        self._generation = None


class RuntimeWriteLease(AbstractContextManager[None], Generic[T]):
    def __init__(self, handle: "RuntimeHandle[T]") -> None:
        self._handle = handle

    def __enter__(self) -> None:
        self._handle._acquire_writer()

    def __exit__(self, exception_type, exception, traceback) -> None:
        self._handle._release_writer()


class RuntimeActivityLease(AbstractContextManager[None], Generic[T]):
    def __init__(self, handle: "RuntimeHandle[T]", activity: RuntimeActivity) -> None:
        self._handle = handle
        self._activity = activity

    def __enter__(self) -> None:
        self._handle._acquire_activity(self._activity)

    def __exit__(self, exception_type, exception, traceback) -> None:
        self._handle._release_activity(self._activity)


class RuntimeHandle(Generic[T]):
    """Atomically expose one generation and serialize activation against use."""

    def __init__(self, generation: T, *, generation_id: str = "") -> None:
        self._condition = Condition(RLock())
        self._generation = generation
        self._generation_id = generation_id or f"generation_{uuid4().hex}"
        self._activity = RuntimeActivity.IDLE
        self._activation = RuntimeActivationState.ACTIVE
        self._readers = 0
        self._writer = False

    def read(self) -> RuntimeGenerationLease[T]:
        return RuntimeGenerationLease(self)

    def write(self) -> RuntimeWriteLease[T]:
        return RuntimeWriteLease(self)

    def activity_lease(self, activity: RuntimeActivity) -> RuntimeActivityLease[T]:
        if activity in {RuntimeActivity.IDLE, RuntimeActivity.CONFIG_ACTIVATION}:
            raise RuntimeGenerationError("Runtime activity lease kind is invalid")
        return RuntimeActivityLease(self, activity)

    def snapshot(self) -> RuntimeGenerationSnapshot[T]:
        with self._condition:
            return RuntimeGenerationSnapshot(
                generation=self._generation,
                generation_id=self._generation_id,
                activity=self._activity,
                activation=self._activation,
            )

    @property
    def activity(self) -> RuntimeActivity:
        with self._condition:
            return self._activity

    @property
    def generation_id(self) -> str:
        with self._condition:
            return self._generation_id

    def set_activity(self, activity: RuntimeActivity) -> None:
        if not isinstance(activity, RuntimeActivity):
            raise RuntimeGenerationError("Runtime activity is invalid")
        with self._condition:
            if (
                activity is not RuntimeActivity.IDLE
                and self._activity is not RuntimeActivity.IDLE
            ):
                raise RuntimeGenerationError("Runtime activity is already active")
            self._activity = activity
            self._condition.notify_all()

    def begin_activation(self) -> None:
        with self._condition:
            if self._activity is not RuntimeActivity.IDLE:
                raise RuntimeGenerationError(
                    "Runtime generation activation requires an idle runtime"
                )
            if self._activation is RuntimeActivationState.PREPARING:
                raise RuntimeGenerationError("Runtime generation is already activating")
            self._activation = RuntimeActivationState.PREPARING
            self._activity = RuntimeActivity.CONFIG_ACTIVATION

    def activate(self, generation: T, *, generation_id: str = "") -> str:
        with self._condition:
            if not self._writer:
                raise RuntimeGenerationError("Runtime generation write lease is required")
            if self._readers:
                raise RuntimeGenerationError("Runtime generation still has active readers")
            if self._activity not in {
                RuntimeActivity.IDLE,
                RuntimeActivity.CONFIG_ACTIVATION,
            }:
                raise RuntimeGenerationError("Runtime generation activation requires idle")
            self._generation = generation
            self._generation_id = generation_id or f"generation_{uuid4().hex}"
            self._activation = RuntimeActivationState.ACTIVE
            self._activity = RuntimeActivity.IDLE
            self._condition.notify_all()
            return self._generation_id

    def fail_activation(self) -> None:
        with self._condition:
            self._activation = RuntimeActivationState.FAILED
            self._activity = RuntimeActivity.IDLE
            self._condition.notify_all()

    def _acquire_reader(self) -> T:
        with self._condition:
            while self._writer:
                self._condition.wait()
            self._readers += 1
            return self._generation

    def _release_reader(self) -> None:
        with self._condition:
            if self._readers <= 0:
                raise RuntimeGenerationError("Runtime generation reader is not held")
            self._readers -= 1
            self._condition.notify_all()

    def _acquire_writer(self) -> None:
        with self._condition:
            while self._writer or self._readers:
                self._condition.wait()
            self._writer = True

    def _acquire_activity(self, activity: RuntimeActivity) -> None:
        with self._condition:
            while self._activity is RuntimeActivity.CONFIG_ACTIVATION:
                self._condition.wait()
            if self._activity is not RuntimeActivity.IDLE:
                raise RuntimeGenerationError("Runtime activity is already active")
            self._activity = activity

    def _release_activity(self, activity: RuntimeActivity) -> None:
        with self._condition:
            if self._activity is not activity:
                raise RuntimeGenerationError("Runtime activity lease is not held")
            self._activity = RuntimeActivity.IDLE
            self._condition.notify_all()

    def _release_writer(self) -> None:
        with self._condition:
            if not self._writer:
                raise RuntimeGenerationError("Runtime generation writer is not held")
            self._writer = False
            self._condition.notify_all()
