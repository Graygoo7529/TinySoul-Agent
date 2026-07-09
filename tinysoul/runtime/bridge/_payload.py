"""Shared payload helpers for runtime bridge modules."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import TypeVar

from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject, to_json_value

from ..exception import RuntimeException

K = TypeVar("K", bound=StrEnum)


def runtime_exception(
    *,
    module: str,
    kind: K,
    reason_map: Mapping[K, str],
    message: str,
    payload: JsonObject | None = None,
) -> RuntimeException:
    runtime_payload: JsonObject = {}
    if payload is not None:
        runtime_payload = payload
    runtime_payload = {
        **runtime_payload,
        "module": module,
        "kind": kind.value,
    }
    return RuntimeException(
        reason=reason_map[kind],
        message=message,
        payload=runtime_payload,
    )


def exception_payload(
    error: Exception,
    payload: JsonObject | None = None,
) -> JsonObject:
    runtime_payload: JsonObject = {"error_type": type(error).__name__}
    if payload is not None:
        runtime_payload = {**runtime_payload, **payload}
    return runtime_payload


def config_error_payload(error: ConfigError) -> JsonObject:
    payload: JsonObject = {
        "key": error.key,
        "source": error.source,
        "expected": error.expected,
    }
    if error.value is not None:
        payload = {**payload, "value": to_json_value(error.value)}
    return payload
