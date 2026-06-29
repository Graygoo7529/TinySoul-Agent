from __future__ import annotations

import pytest

from tinysoul.infra.json import JsonTypeError
from tinysoul.runtime.exception import (
    CONTEXT_COMPRESSION_REQUIRED,
    RuntimeException,
)


def test_runtime_exception_normalizes_payload() -> None:
    exc = RuntimeException(
        reason=CONTEXT_COMPRESSION_REQUIRED,
        message="too long",
        payload={"a": 1},
    )

    assert str(exc) == "context.compression_required: too long"
    assert exc.payload == {"a": 1}


def test_runtime_exception_rejects_non_object_payload() -> None:
    with pytest.raises(JsonTypeError):
        RuntimeException(
            reason="runtime.bad",
            message="bad",
            payload=["x"],  # type: ignore[arg-type]
        )


def test_runtime_exception_rejects_empty_reason() -> None:
    with pytest.raises(ValueError):
        RuntimeException(reason="", message="bad")
