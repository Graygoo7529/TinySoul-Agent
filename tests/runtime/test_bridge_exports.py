from __future__ import annotations

from tinysoul.infra.config import ConfigError
from tinysoul.llm.failures import LLMFailureKind
from tinysoul.runtime import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END
from tinysoul.runtime.bridge import RuntimeLLMBridge


def test_runtime_bridge_exports_are_lazily_importable() -> None:
    from tinysoul.runtime.bridge import (
        RuntimeContextBridge,
        RuntimeLLMBridge,
        RuntimeLoopBridge,
        RuntimeSessionBridge,
    )

    assert RuntimeContextBridge.__name__ == "RuntimeContextBridge"
    assert RuntimeLLMBridge.__name__ == "RuntimeLLMBridge"
    assert RuntimeLoopBridge.__name__ == "RuntimeLoopBridge"
    assert RuntimeSessionBridge.__name__ == "RuntimeSessionBridge"


def test_runtime_bridge_payload_helpers_keep_stable_fields() -> None:
    bridge = RuntimeLLMBridge()

    config_exc = bridge.from_config_error(
        ConfigError(
            "bad config",
            key="llm.tasks.framework.models",
            source="test",
            value=["missing"],
            expected="known model",
        )
    )

    assert config_exc.reason == RUNTIME_STARTUP_FAILED
    assert config_exc.payload == {
        "key": "llm.tasks.framework.models",
        "source": "test",
        "expected": "known model",
        "value": ["missing"],
        "module": "llm",
        "kind": LLMFailureKind.CONFIGURATION_FAILED.value,
    }

    failure_exc = bridge.from_exception(
        LLMFailureKind.INTERNAL_FAILURE,
        ValueError("bad"),
        payload={"profile": "framework"},
    )

    assert failure_exc.reason == RUNTIME_TURN_END
    assert failure_exc.payload["module"] == "llm"
    assert failure_exc.payload["kind"] == LLMFailureKind.INTERNAL_FAILURE.value
    assert failure_exc.payload["error_type"] == "ValueError"
    assert failure_exc.payload["profile"] == "framework"
