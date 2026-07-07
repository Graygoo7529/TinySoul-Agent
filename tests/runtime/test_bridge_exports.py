from __future__ import annotations


def test_runtime_bridge_exports_are_lazily_importable() -> None:
    from tinysoul.runtime.bridge import (
        RuntimeContextBridge,
        RuntimeLLMBridge,
        RuntimeLoopBridge,
    )

    assert RuntimeContextBridge.__name__ == "RuntimeContextBridge"
    assert RuntimeLLMBridge.__name__ == "RuntimeLLMBridge"
    assert RuntimeLoopBridge.__name__ == "RuntimeLoopBridge"
