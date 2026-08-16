"""Configuration and Action catalog routes."""

from __future__ import annotations

from fastapi import FastAPI

from tinysoul.infra.config import ConfigError, ConfigMutation
from tinysoul.infra.json import JsonObject

from ...engine import EndpointEngine
from ...errors import EndpointRequestError
from ..schemas import (
    ConfigDeleteMutationRequest,
    ConfigMutationRequest,
    ConfigPatchRequest,
    ConfigSetMutationRequest,
)


def register_configuration_routes(app: FastAPI, engine: EndpointEngine) -> None:
    @app.get("/v1/config")
    def config_status() -> JsonObject:
        return engine.configuration.status()

    @app.get("/v1/config/catalog")
    def config_catalog() -> JsonObject:
        return engine.configuration.catalog()

    @app.get("/v1/config/actions")
    def action_catalog() -> JsonObject:
        return engine.configuration.actions()

    @app.patch("/v1/config")
    def patch_config(body: ConfigPatchRequest) -> JsonObject:
        return engine.configuration.patch(_config_mutations(body.operations))


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
