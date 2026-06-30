"""Infra-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject, to_json_value

from ..exception import RUNTIME_STARTUP_FAILED, RuntimeException


@dataclass(frozen=True)
class RuntimeInfraBridge:
    """Convert infra boundary failures into runtime semantic exceptions."""

    def startup_failure(
        self,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return RuntimeException(
            reason=RUNTIME_STARTUP_FAILED,
            message=message,
            payload=payload if payload is not None else {},
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        payload: JsonObject = {
            "key": error.key,
            "source": error.source,
            "expected": error.expected,
        }
        if error.value is not None:
            payload = {**payload, "value": to_json_value(error.value)}
        return self.startup_failure(message=error.message, payload=payload)
