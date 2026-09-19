"""Runtime registry of explicitly configured model descriptions."""

from __future__ import annotations
from ..errors import LLMInvariantError, LLMContractError
from ..protocol.models import ModelSpec


class ModelRegistry:
    """Registry of available models."""

    def __init__(self, models: list[ModelSpec] | None = None) -> None:
        self._models: dict[str, ModelSpec] = {}
        for model in models or []:
            self.register(model)

    def register(self, model: ModelSpec) -> None:
        if model.id in self._models:
            raise LLMInvariantError(f"Model already registered: {model.id}")
        self._models[model.id] = model

    def get(self, model_id: str) -> ModelSpec:
        try:
            return self._models[model_id]
        except KeyError as exc:
            raise LLMContractError(f"Unknown model: {model_id}") from exc

    def has(self, model_id: str) -> bool:
        return model_id in self._models

    def ids(self) -> tuple[str, ...]:
        return tuple(self._models)
