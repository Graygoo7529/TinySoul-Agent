"""Configuration and Action catalog routes."""

from __future__ import annotations

from typing import Literal

from fastapi import FastAPI

from tinysoul.infra.config import ConfigError, ConfigMutation
from tinysoul.infra.json import JsonObject

from ...engine import EndpointEngine
from ...errors import EndpointRequestError
from ..schemas import (
    ConfigApplyRequest,
    ConfigDeleteMutationRequest,
    ConfigMutationRequest,
    ConfigPatchRequest,
    ConfigSetMutationRequest,
    PresetCreateRequest,
    PresetUpdateRequest,
)


def register_configuration_routes(app: FastAPI, engine: EndpointEngine) -> None:
    @app.get("/v2/config")
    async def config_status(view: Literal["saved", "active"] = "saved") -> JsonObject:
        return await engine.configuration.status(view=view)

    @app.get("/v2/config/catalog")
    def config_catalog() -> JsonObject:
        return engine.configuration.catalog()

    @app.get("/v2/config/actions")
    async def action_catalog(scenario: str = "user") -> JsonObject:
        return await engine.configuration.actions(scenario=scenario)

    @app.patch("/v2/config")
    async def patch_config(body: ConfigPatchRequest) -> JsonObject:
        return await engine.configuration.patch(_config_mutations(body.operations))

    @app.post("/v2/config/reload")
    async def reload_config() -> JsonObject:
        return await engine.configuration.reload()

    @app.post("/v2/config/apply")
    async def apply_config(body: ConfigApplyRequest) -> JsonObject:
        operations = (
            _config_mutations(body.operations) if body.operations is not None else ()
        )
        return await engine.configuration.apply(operations, preset_id=body.preset_id)

    @app.get("/v2/config/presets")
    def presets() -> JsonObject:
        return engine.configuration.presets()

    @app.post("/v2/config/presets")
    async def create_preset(body: PresetCreateRequest) -> JsonObject:
        return await engine.configuration.save_preset(
            name=body.name,
            description=body.description,
            source=body.source,
            include_budgets=body.include_budgets,
            mutations=_config_mutations(body.operations),
        )

    @app.get("/v2/config/presets/{preset_id}")
    def get_preset(preset_id: str) -> JsonObject:
        return engine.configuration.preset(preset_id)

    @app.put("/v2/config/presets/{preset_id}")
    async def update_preset(preset_id: str, body: PresetUpdateRequest) -> JsonObject:
        capture = body.capture
        return await engine.configuration.update_preset(
            preset_id,
            name=body.name,
            description=body.description,
            capture_source=capture.source if capture else None,
            mutations=_config_mutations(capture.operations) if capture else (),
            include_budgets=capture.include_budgets if capture else True,
        )

    @app.delete("/v2/config/presets/{preset_id}")
    async def delete_preset(preset_id: str) -> JsonObject:
        return await engine.configuration.delete_preset(preset_id)


def _config_mutations(
    operations: list[ConfigMutationRequest],
) -> tuple[ConfigMutation, ...]:
    try:
        return tuple(_config_mutation(operation) for operation in operations)
    except ConfigError as exc:
        raise EndpointRequestError(
            status_code=422,
            code="config.invalid",
            message=exc.message,
            details={
                **({"key": exc.key} if exc.key else {}),
                **({"source": exc.source} if exc.source else {}),
                **({"expected": exc.expected} if exc.expected else {}),
            },
        ) from exc


def _config_mutation(
    operation: ConfigMutationRequest,
) -> ConfigMutation:
    if isinstance(operation, ConfigSetMutationRequest):
        return ConfigMutation(
            source_id=operation.source_id,
            path=operation.path,
            op="set",
            value=operation.value,
        )
    if isinstance(operation, ConfigDeleteMutationRequest):
        return ConfigMutation(
            source_id=operation.source_id,
            path=operation.path,
            op="delete",
        )
    raise EndpointRequestError(
        status_code=422,
        code="config.invalid",
        message="Unsupported configuration operation.",
        details={"operation_type": type(operation).__name__},
    )
