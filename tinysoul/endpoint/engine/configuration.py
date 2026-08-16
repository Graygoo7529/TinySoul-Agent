"""Endpoint configuration and Action catalog engine."""

from __future__ import annotations

from typing import Generic

from tinysoul.infra.config import ConfigError, ConfigMutation
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import RuntimeException

from ..errors import EndpointRequestError
from .contracts import EndpointGenerationT
from .context import EndpointEngineContext


class EndpointConfigurationEngine(Generic[EndpointGenerationT]):
    """Expose Infra configuration and the current Action runtime projection."""

    def __init__(self, context: EndpointEngineContext[EndpointGenerationT]) -> None:
        self._context = context

    def status(self) -> JsonObject:
        result = self._context.config_controller().status()
        runtime_handle = self._context.runtime_handle
        if runtime_handle is not None:
            snapshot = runtime_handle.snapshot()
            result["runtime"] = {
                "generation_id": snapshot.generation_id,
                "activity": snapshot.activity.value,
                "activation": snapshot.activation.value,
            }
        result["process_shell"] = {
            "writable": False,
            "reason": "process_owned",
            "endpoint": {
                "host": self._context.settings.host,
                "port": self._context.settings.port,
                "instance_id": self._context.settings.instance_id,
            },
        }
        return result

    def catalog(self) -> JsonObject:
        return self._context.config_controller().catalog()

    def actions(self) -> JsonObject:
        runtime_handle = self._context.runtime_handle
        if runtime_handle is None:
            raise EndpointRequestError(
                status_code=404,
                code="actions.unavailable",
                message="Action catalog is not available.",
            )
        with runtime_handle.read() as generation:
            return generation.user_turn.action_catalog()

    def patch(self, mutations: tuple[ConfigMutation, ...]) -> JsonObject:
        try:
            return self._context.config_controller().patch(mutations)
        except ConfigError as exc:
            raise _config_error(exc) from exc
        except RuntimeException as exc:
            raise EndpointRequestError(
                status_code=500,
                code="config.activation_failed",
                message="Configuration activation failed; the previous runtime remains active.",
                details={
                    "reason": exc.reason,
                    "error_type": type(exc).__name__,
                },
            ) from exc


def _config_error(error: ConfigError) -> EndpointRequestError:
    if error.key == "config.activation_unavailable":
        return EndpointRequestError(
            status_code=409,
            code="config.activation_unavailable",
            message="Configuration changes require an idle runtime.",
        )
    return EndpointRequestError(
        status_code=422,
        code="config.invalid",
        message=error.message,
        details={
            **({"key": error.key} if error.key else {}),
            **({"source": error.source} if error.source else {}),
            **({"expected": error.expected} if error.expected else {}),
        },
    )
