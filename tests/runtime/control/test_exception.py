from __future__ import annotations

from typing import cast
from enum import StrEnum

import pytest

from tinysoul.infra.json import JsonObject
from tinysoul.runtime.errors import RuntimeContractError
from tinysoul.runtime.failures import exception_payload, runtime_exception
from tinysoul.runtime import (
    RuntimeException,
)


def test_runtime_exception_normalizes_payload() -> None:
    exc = RuntimeException(
        reason="test.capacity",
        message="too long",
        payload={"a": 1},
    )

    assert str(exc) == "test.capacity: too long"
    assert exc.payload == {"a": 1}


def test_runtime_exception_rejects_non_object_payload() -> None:
    with pytest.raises(RuntimeContractError):
        RuntimeException(
            reason="runtime.bad",
            message="bad",
            payload=cast(JsonObject, ["x"]),
        )


def test_runtime_exception_rejects_empty_reason() -> None:
    with pytest.raises(RuntimeContractError):
        RuntimeException(reason="", message="bad")


class _FailureKind(StrEnum):
    FAILED = "test.failed"


def test_public_failure_constructor_owns_identity_and_copies_details() -> None:
    details: JsonObject = {"module": "forged", "kind": "forged", "usage": [12]}
    failure = runtime_exception(
        module="test",
        kind=_FailureKind.FAILED,
        reason="test.recover",
        message="Test operation failed.",
        payload=details,
    )
    details["usage"] = []
    assert failure.payload == {"module": "test", "kind": "test.failed", "usage": [12]}
    assert failure.reason == "test.recover"
    with pytest.raises(RuntimeContractError):
        runtime_exception(
            module="other",
            kind=_FailureKind.FAILED,
            reason="test.recover",
            message="invalid",
        )


def test_exception_payload_does_not_render_the_exception() -> None:
    class UnrenderableError(Exception):
        def __str__(self) -> str:
            raise AssertionError("Exception text must not enter Runtime diagnostics")

    assert exception_payload(UnrenderableError(), {"operation": "read"}) == {
        "error_type": "UnrenderableError",
        "operation": "read",
    }
