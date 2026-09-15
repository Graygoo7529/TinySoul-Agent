"""Tests for the context runtime bridge."""

from __future__ import annotations

from tinysoul.context import (
    ContextBudgetError,
    ContextContractError,
    ContextInvariantError,
)
from tinysoul.context.failures import ContextFailureKind
from tinysoul.context.failures import CONTEXT_COMPRESSION_REQUIRED
from tinysoul.runtime import (
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
)
from tinysoul.context.runtime_bridge import RuntimeContextBridge
from tinysoul.infra.config import ConfigError


def test_context_bridge_projects_config_and_internal_failures() -> None:
    bridge = RuntimeContextBridge()
    config = bridge.from_config_error(ConfigError(
        "private config", key="context.limit", source="C:/private/config.toml",
        value="private credential", expected="positive integer",
    ))
    assert config.reason == RUNTIME_STARTUP_FAILED
    assert config.payload["key"] == "context.limit"
    assert "private" not in str(config) + repr(config.payload)
    internal = bridge.from_context_error(ContextInvariantError("private state"))
    assert internal.payload["kind"] == ContextFailureKind.INTERNAL_FAILURE.value
    assert internal.payload["error_type"] == "ContextInvariantError"
    assert "private" not in str(internal) + repr(internal.payload)


def test_budget_error_maps_to_compression_reason() -> None:
    bridge = RuntimeContextBridge()
    error = ContextBudgetError(
        "image budget",
        estimated_chars=1200,
        estimated_image_bytes=2000,
        max_image_bytes=1000,
    )
    exc = bridge.from_context_error(error)
    assert exc.reason == CONTEXT_COMPRESSION_REQUIRED
    assert exc.payload["module"] == "context"
    assert exc.payload["kind"] == ContextFailureKind.BUDGET_EXCEEDED.value
    assert exc.payload["estimated_chars"] == 1200
    assert exc.payload["estimated_image_bytes"] == 2000
    assert exc.payload["max_image_bytes"] == 1000


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
