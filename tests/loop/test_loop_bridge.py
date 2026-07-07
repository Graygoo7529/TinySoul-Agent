from __future__ import annotations

from tinysoul.loop import LoopContractError, LoopFailureKind
from tinysoul.runtime import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END
from tinysoul.runtime.bridge import RuntimeLoopBridge


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
