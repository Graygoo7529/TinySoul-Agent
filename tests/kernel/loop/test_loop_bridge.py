from __future__ import annotations

from tinysoul.kernel.loop import LoopContractError, LoopFailureKind
from tinysoul.kernel.loop.errors import LoopInvariantError
from tinysoul.runtime import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END
from tinysoul.kernel.loop.runtime_bridge import RuntimeLoopBridge


def test_loop_bridge_maps_contract_failure_to_turn_end() -> None:
    bridge = RuntimeLoopBridge()

    exc = bridge.from_loop_error(LoopContractError("bad phase"))

    assert exc.reason == RUNTIME_TURN_END
    assert exc.payload["module"] == "loop"
    assert exc.payload["kind"] == LoopFailureKind.CONTRACT_VIOLATION.value


def test_loop_bridge_maps_startup_failure() -> None:
    bridge = RuntimeLoopBridge()

    exc = bridge.startup_failure(message="bad config", payload={"key": "loop.x"})

    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["key"] == "loop.x"


def test_loop_bridge_distinguishes_resource_preparation_and_invariant_failures() -> None:
    bridge = RuntimeLoopBridge()
    resource = bridge.from_exception(LoopFailureKind.RESOURCE_PREPARATION_FAILED,
                                     OSError("C:/private/staging"))
    assert resource.reason == RUNTIME_STARTUP_FAILED
    assert resource.payload["kind"] == "loop.resource_preparation_failed"
    invariant = bridge.from_loop_error(LoopInvariantError("private state"))
    assert invariant.reason == RUNTIME_TURN_END
    assert invariant.payload["kind"] == "loop.internal_failure"
    assert "private" not in str(resource) + str(invariant)
