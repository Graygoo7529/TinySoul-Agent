"""Action runtime configuration models — LLM-invisible.

ActionRuntimeConfig 声明在 Action Handler 上（默认值、依赖列表）。
RunConfig 是一次 Action.execute() 调用时的运行时控制对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import threading
import time
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from tinysoul.infra.capabilities import ActionDependency


class TerminationReason(StrEnum):
    """Reason for requesting an action execution to terminate."""

    TIMEOUT = "timeout"
    USER_CANCEL = "user_cancel"
    SHUTDOWN = "shutdown"


@dataclass
class ActionRuntimeConfig:
    """Runtime configuration declared on an Action handler.

    Not exposed to the LLM; used by the framework to control execution
    and filter actions during registration.
    """

    timeout: float | None = None
    llm_timeout: float | None = None
    api_timeout: float | None = None
    api_dependency: bool = False
    dependencies: list[ActionDependency] = field(default_factory=list)


@dataclass
class RunConfig:
    """Runtime control object assembled per action execution call.

    Dispatcher owns RunConfig creation. QueryAction resolves action-level
    defaults into it, and executors consume it to observe cancellation,
    deadlines, and timeout budgets.
    """

    action_name: str = ""
    turn: int = 0
    execution_id: str = field(default_factory=lambda: uuid4().hex[:12])
    timeout: float | None = None
    deadline: float | None = None
    terminate_event: threading.Event = field(default_factory=threading.Event)
    termination_reason: TerminationReason | None = None
    llm_timeout: float | None = None
    api_timeout: float | None = None

    @classmethod
    def create(
        cls,
        *,
        action_name: str,
        turn: int,
        timeout: float | None = None,
        llm_timeout: float | None = None,
        api_timeout: float | None = None,
        execution_id: str | None = None,
        terminate_event: threading.Event | None = None,
        termination_reason: TerminationReason | None = None,
    ) -> "RunConfig":
        deadline = time.monotonic() + timeout if timeout is not None else None
        return cls(
            action_name=action_name,
            turn=turn,
            execution_id=execution_id or uuid4().hex[:12],
            timeout=timeout,
            deadline=deadline,
            terminate_event=terminate_event or threading.Event(),
            termination_reason=termination_reason,
            llm_timeout=llm_timeout,
            api_timeout=api_timeout,
        )

    def apply_timeout(self, timeout: float | None) -> None:
        """Set the effective timeout and initialize deadline if needed."""
        self.timeout = timeout
        if timeout is not None and self.deadline is None:
            self.deadline = time.monotonic() + timeout

    def remaining(self) -> float | None:
        """Return seconds remaining until deadline, or None if unbounded."""
        if self.deadline is None:
            return None
        return max(0.0, self.deadline - time.monotonic())

    def is_expired(self) -> bool:
        remaining = self.remaining()
        return remaining is not None and remaining <= 0.0

    def request_termination(self, reason: TerminationReason) -> None:
        """Request this action execution to terminate."""
        if self.termination_reason is None:
            self.termination_reason = reason
        self.terminate_event.set()

    def is_termination_requested(self) -> bool:
        return self.terminate_event.is_set()

    def raise_if_terminated(self) -> None:
        """Raise the framework-level termination/timeout error if requested."""
        if self.terminate_event.is_set():
            if self.termination_reason == TerminationReason.TIMEOUT:
                from tinysoul.trap import ActionTimeoutError

                raise ActionTimeoutError(
                    f"Action '{self.action_name}' timed out after {self.timeout}s",
                    action_name=self.action_name,
                )
            from tinysoul.trap import ActionCancelledError

            raise ActionCancelledError(
                f"Action '{self.action_name}' was terminated"
                + (
                    f" ({self.termination_reason.value})"
                    if self.termination_reason
                    else ""
                ),
                action_name=self.action_name,
            )
        if self.is_expired():
            self.request_termination(TerminationReason.TIMEOUT)
            from tinysoul.trap import ActionTimeoutError

            raise ActionTimeoutError(
                f"Action '{self.action_name}' timed out after {self.timeout}s",
                action_name=self.action_name,
            )
