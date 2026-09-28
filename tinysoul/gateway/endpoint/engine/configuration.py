"""Endpoint configuration and Action catalog engine."""

from __future__ import annotations

from tinysoul.agent.errors import AgentContractError
from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.infra.config import ConfigError, ConfigMutation
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import RuntimeException

from ..errors import EndpointRequestError
from .context import EndpointEngineContext


class EndpointConfigurationEngine:
    """Expose Infra configuration and the current Action runtime projection."""

    def __init__(self, context: EndpointEngineContext) -> None:
        self._context = context

    async def status(self, *, view: str = "saved") -> JsonObject:
        operations = JoinedOperations()
        result = await operations.run(
            lambda: self._context.config_controller().status(view=view)
        )
        operations.check_cancelled()
        result["runtime"] = self._context.services.runtime_status(credentials=True)
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

    async def apply(
        self,
        mutations: tuple[ConfigMutation, ...] = (),
        *,
        preset_id: str | None = None,
    ) -> JsonObject:
        try:
            return await self._context.config_controller().apply(
                mutations, preset_id=preset_id
            )
        except ConfigError as exc:
            raise _config_error(exc) from exc
        except RuntimeException as exc:
            raise EndpointRequestError(
                status_code=500,
                code="config.activation_failed",
                message="Configuration activation failed; the previous runtime remains active.",
                details={"reason": exc.reason},
            ) from exc

    def presets(self) -> JsonObject:
        return {"presets": list(self._context.config_controller().presets())}

    def preset(self, preset_id: str) -> JsonObject:
        try:
            return self._context.config_controller().preset(preset_id)
        except ConfigError as exc:
            raise _config_error(exc) from exc

    async def save_preset(
        self,
        *,
        name: str,
        description: str = "",
        source: str = "saved",
        include_budgets: bool = True,
        mutations: tuple[ConfigMutation, ...] = (),
    ) -> JsonObject:
        try:
            return await self._context.config_controller().save_preset(
                name=name,
                description=description,
                source=source,
                include_budgets=include_budgets,
                mutations=mutations,
            )
        except ConfigError as exc:
            raise _config_error(exc) from exc

    async def update_preset(
        self,
        preset_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        capture_source: str | None = None,
        mutations: tuple[ConfigMutation, ...] = (),
        include_budgets: bool = True,
    ) -> JsonObject:
        try:
            return await self._context.config_controller().update_preset(
                preset_id,
                name=name,
                description=description,
                capture_source=capture_source,
                mutations=mutations,
                include_budgets=include_budgets,
            )
        except ConfigError as exc:
            raise _config_error(exc) from exc

    async def delete_preset(self, preset_id: str) -> JsonObject:
        try:
            await self._context.config_controller().delete_preset(preset_id)
        except ConfigError as exc:
            raise _config_error(exc) from exc
        return {"deleted": True, "preset_id": preset_id}

    def catalog(self) -> JsonObject:
        return self._context.config_controller().catalog()

    async def actions(self, *, scenario: str = "user") -> JsonObject:
        try:
            return await self._context.services.action_catalog(scenario=scenario)
        except AgentContractError as exc:
            raise EndpointRequestError(
                status_code=422,
                code="config.invalid_scenario",
                message="Unknown Action scenario.",
            ) from exc

    async def patch(self, mutations: tuple[ConfigMutation, ...]) -> JsonObject:
        try:
            return await self._context.config_controller().patch(mutations)
        except ConfigError as exc:
            raise _config_error(exc) from exc
        except RuntimeException as exc:
            raise EndpointRequestError(
                status_code=422,
                code="config.invalid",
                message="Configuration candidate is invalid.",
                details={"reason": exc.reason},
            ) from exc

    async def reload(self) -> JsonObject:
        try:
            return await self._context.config_controller().reload()
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
    if error.key == "preset.not_found":
        return EndpointRequestError(
            status_code=404,
            code="config.preset_not_found",
            message="Preset was not found.",
        )
    if error.key == "config.activation_unavailable":
        return EndpointRequestError(
            status_code=409,
            code="config.activation_unavailable",
            message="Configuration activation requires an idle runtime.",
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
