"""Tests for the context runtime bridge."""

from __future__ import annotations

from tinysoul.context import (
    ContextBudgetError,
    ContextContractError,
    ContextInvariantError,
)
from tinysoul.context.failures import ContextFailureKind
from tinysoul.runtime import (
    CONTEXT_COMPRESSION_REQUIRED,
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
)
from tinysoul.runtime.bridge import RuntimeContextBridge


def test_budget_error_maps_to_compression_reason() -> None:
    bridge = RuntimeContextBridge()
    error = ContextBudgetError(
        "over budget",
        estimated_chars=1200,
        max_chars=1000,
    )
    exc = bridge.from_context_error(error)
    assert exc.reason == CONTEXT_COMPRESSION_REQUIRED
    assert exc.payload["module"] == "context"
    assert exc.payload["kind"] == ContextFailureKind.BUDGET_EXCEEDED.value
    assert exc.payload["estimated_chars"] == 1200
    assert exc.payload["max_chars"] == 1000


def test_contract_and_invariant_errors_end_turn() -> None:
    bridge = RuntimeContextBridge()
    assert bridge.from_context_error(ContextContractError("bad")).reason == RUNTIME_TURN_END
    assert bridge.from_context_error(ContextInvariantError("bad")).reason == RUNTIME_TURN_END
    assert (
        bridge.from_context_error(ValueError("other")).payload["kind"]
        == ContextFailureKind.INTERNAL_FAILURE.value
    )


def test_startup_failure_maps_to_startup_reason() -> None:
    bridge = RuntimeContextBridge()
    exc = bridge.startup_failure(message="bad config", payload={"key": "context.budget"})
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["key"] == "context.budget"
