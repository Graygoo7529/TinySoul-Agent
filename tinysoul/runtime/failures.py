"""Public construction of owner-projected Runtime failures."""

from __future__ import annotations

from enum import StrEnum

from tinysoul.infra.json import JsonObject

from .errors import RuntimeContractError
from .control.exception import RuntimeException


def runtime_exception(
    *,
    module: str,
    kind: StrEnum,
    reason: str,
    message: str,
    payload: JsonObject | None = None,
) -> RuntimeException:
    """Build a failure from diagnostics explicitly selected by its owner."""

    if not module or not kind.value.startswith(f"{module}."):
        raise RuntimeContractError("Failure kind must belong to its module")
    return RuntimeException(
        reason=reason,
        message=message,
        payload={**(payload or {}), "module": module, "kind": kind.value},
    )


def exception_payload(
    error: Exception,
    payload: JsonObject | None = None,
) -> JsonObject:
    """Add the exception type without serializing the exception or its message."""

    return {**(payload or {}), "error_type": type(error).__name__}
