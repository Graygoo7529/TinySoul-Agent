from __future__ import annotations

from tinysoul.runtime.control.scope import RunFrame, RunLevel
from tinysoul.runtime.control.transfer import RuntimeTransfer, RuntimeTransferAction
from tinysoul.runtime.errors import RuntimeContractError, RuntimeInvariantError
from tinysoul.runtime import (
    RunScope,
    RuntimeException,
    RuntimeTrap,
    TrapHandlerRegistry,
)
from tinysoul.kernel.loop.failures import LOOP_BUDGET_REQUIRED
from tinysoul.kernel.loop.trap_handlers import BudgetSuspendTrapHandler
import pytest


def test_transfer_retry_and_end() -> None:
    frame = RunFrame(RunLevel.PHASE, "phase1")

    retry = RuntimeTransfer.retry(frame)
    end = RuntimeTransfer.end(frame)

    assert retry.action is RuntimeTransferAction.RETRY
    assert retry.target == frame
    assert end.action is RuntimeTransferAction.END
    assert end.target == frame


def test_suspend_only_targets_current_turn_boundary() -> None:
    with pytest.raises(RuntimeContractError):
        RuntimeTransfer.suspend(RunFrame(RunLevel.PHASE, "phase1"))
    scope = RunScope().push(RunLevel.AGENT, "program").push(RunLevel.TURN, "turn")
    registry = TrapHandlerRegistry()
    registry.register(LOOP_BUDGET_REQUIRED, BudgetSuspendTrapHandler())
    trap = RuntimeTrap(registry=registry)
    error = RuntimeException(reason=LOOP_BUDGET_REQUIRED, message="budget")
    assert trap.capture(error, scope).transfer.action is RuntimeTransferAction.SUSPEND
    with pytest.raises(RuntimeInvariantError):
        trap.capture(error, scope.push(RunLevel.CYCLE, "cycle"))
