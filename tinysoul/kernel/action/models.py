"""Code-owned model uses and immutable, validated configuration bindings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from collections.abc import Mapping

from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject
from tinysoul.infra.model_services.config import ModelServicesSettings, ModelCapability
from tinysoul.kernel.retrieval.policy import SearchPolicy
from tinysoul.kernel.retrieval.contracts import (
    SearchContext,
    SearchSemantic,
    CandidateSource,
)


class ModelImplementation(StrEnum):
    LLM_TASK = "llm_task"
    STRUCTURED_DECISION = "structured_decision"
    EMBEDDING_SIMILARITY = "embedding_similarity"


class ModelOperation(StrEnum):
    GENERATE = "generate"
    RANK = "rank"
    SELECT = "select"


@dataclass(frozen=True)
class ModelUseDescriptor:
    consumer: str
    action_id: str
    operation: ModelOperation
    implementations: tuple[ModelImplementation, ...] = (ModelImplementation.LLM_TASK,)
    embedding_owner: str | None = None

    def __post_init__(self) -> None:
        if not self.consumer or not self.action_id or not self.implementations:
            raise ConfigError(
                "Model use requires identity and implementations", key="action.models"
            )
        if ModelImplementation.EMBEDDING_SIMILARITY in self.implementations and (
            self.operation is not ModelOperation.RANK or not self.embedding_owner
        ):
            raise ConfigError(
                "Similarity ranking requires its owner's embedding dependency",
                key=self.consumer,
            )


@dataclass(frozen=True)
class ModelUseBinding:
    consumer: str
    implementation: ModelImplementation
    task_profile: str | None = None
    use: str | None = None
    max_output_tokens: int | None = None
    relevance_threshold: int = 2

    def __post_init__(self) -> None:
        valid_target = (
            bool(self.task_profile) and self.use is None
            if self.implementation is ModelImplementation.LLM_TASK
            else bool(self.use) and self.task_profile is None
            if self.implementation is ModelImplementation.STRUCTURED_DECISION
            else self.task_profile is None and self.use is None
        )
        if not self.consumer or not valid_target:
            raise ConfigError(
                "Model binding target does not match its implementation",
                key=f"action.models.bindings.{self.consumer}",
            )
        if self.max_output_tokens is not None and (
            type(self.max_output_tokens) is not int
            or self.max_output_tokens <= 0
            or self.implementation is not ModelImplementation.LLM_TASK
        ):
            raise ConfigError(
                "Output tokens require an LLM binding and a positive integer",
                key=self.consumer,
            )
        if (
            type(self.relevance_threshold) is not int
            or not 0 <= self.relevance_threshold <= 3
        ):
            raise ConfigError(
                "Relevance threshold must be a score level from zero to three",
                key=self.consumer,
            )

    def to_json(self) -> JsonObject:
        target: JsonObject = {}
        if self.task_profile is not None:
            target["task_profile"] = self.task_profile
        if self.use is not None:
            target["use"] = self.use
        options: JsonObject = {}
        if self.max_output_tokens is not None:
            options["max_output_tokens"] = self.max_output_tokens
        if self.implementation is ModelImplementation.STRUCTURED_DECISION:
            options["relevance_threshold"] = self.relevance_threshold
        return {
            "consumer": self.consumer,
            "implementation": self.implementation.value,
            "target": target,
            "options": options,
        }


class ModelUseRegistry:
    """One generation's declarations, resolved independently of invocation history."""

    def __init__(
        self,
        descriptors: tuple[ModelUseDescriptor, ...],
        bindings: tuple[ModelUseBinding, ...],
    ) -> None:
        declared = {item.consumer: item for item in descriptors}
        bound = {item.consumer: item for item in bindings}
        if len(declared) != len(descriptors) or len(bound) != len(bindings):
            raise ConfigError(
                "Model consumers and bindings must be unique",
                key="action.models.bindings",
            )
        for consumer, binding in bound.items():
            descriptor = declared.get(consumer)
            if (
                descriptor is None
                or binding.implementation not in descriptor.implementations
            ):
                raise ConfigError(
                    "Unknown model use or unsupported implementation",
                    key=f"action.models.bindings.{consumer}",
                )
        self._descriptors: Mapping[str, ModelUseDescriptor] = MappingProxyType(declared)
        self._bindings: Mapping[str, ModelUseBinding] = MappingProxyType(bound)

    def descriptor(self, consumer: str) -> ModelUseDescriptor:
        try:
            return self._descriptors[consumer]
        except KeyError as exc:
            raise ConfigError("Unknown model consumer", key=consumer) from exc

    def binding(self, consumer: str) -> ModelUseBinding:
        self.descriptor(consumer)
        try:
            return self._bindings[consumer]
        except KeyError as exc:
            raise ConfigError(
                "Model consumer has no binding",
                key=f"action.models.bindings.{consumer}",
            ) from exc

    def validate_targets(
        self, profiles: tuple[str, ...], services: ModelServicesSettings
    ) -> None:
        decisions = {
            use.id
            for use in services.uses
            if use.kind is ModelCapability.STRUCTURED_DECISION
        }
        for binding in self._bindings.values():
            if (
                binding.task_profile is not None
                and binding.task_profile not in profiles
            ):
                raise ConfigError(
                    "Unknown model task profile",
                    key=binding.consumer,
                    value=binding.task_profile,
                )
            if (
                binding.implementation is ModelImplementation.STRUCTURED_DECISION
                and binding.use not in decisions
            ):
                raise ConfigError(
                    "Unknown or incompatible structured decision use",
                    key=binding.consumer,
                    value=binding.use,
                )

    def validate_selected(
        self,
        *,
        actions: frozenset[str],
        policies: tuple[SearchPolicy, ...],
        services: ModelServicesSettings,
        env: Mapping[str, str],
        embedding_uses: Mapping[str, str | None],
    ) -> None:
        configured = {policy.action_id for policy in policies}
        for item in self._descriptors.values():
            if (
                item.action_id in actions
                and item.operation is not ModelOperation.GENERATE
                and item.action_id not in configured
            ):
                raise ConfigError(
                    "Available search action requires a policy", key=item.action_id
                )
        selected = {
            item.consumer
            for item in self._descriptors.values()
            if item.action_id in actions and item.operation is ModelOperation.GENERATE
        }
        for policy in policies:
            if policy.action_id not in actions:
                continue
            for semantic in policy.allowed_semantic:
                if semantic is SearchSemantic.NONE:
                    continue
                consumer = f"{policy.action_id}.{semantic.value}"
                binding = self.binding(consumer)
                selected.add(consumer)
                if (
                    binding.implementation is ModelImplementation.EMBEDDING_SIMILARITY
                    and SearchContext.CURRENT in policy.allowed_context
                ):
                    raise ConfigError(
                        "Similarity ranking cannot accept current Context", key=consumer
                    )
            if CandidateSource.EMBEDDING in policy.candidate_sources:
                owner = policy.action_id.split(".")[0]
                use = embedding_uses.get(owner)
                if not use:
                    raise ConfigError(
                        "Embedding recall requires the source owner's shared use",
                        key=policy.action_id,
                    )
                services.resolve(use, ModelCapability.EMBEDDING, env)
        for consumer in selected:
            binding = self.binding(consumer)
            if binding.implementation is ModelImplementation.STRUCTURED_DECISION:
                assert binding.use is not None
                services.resolve(binding.use, ModelCapability.STRUCTURED_DECISION, env)
            elif binding.implementation is ModelImplementation.EMBEDDING_SIMILARITY:
                owner = self.descriptor(consumer).embedding_owner
                use = embedding_uses.get(owner or "")
                if not use:
                    raise ConfigError(
                        "Similarity ranking requires the owner's shared embedding use",
                        key=consumer,
                    )
                services.resolve(use, ModelCapability.EMBEDDING, env)

    def for_action(self, action_id: str) -> tuple[ModelUseDescriptor, ...]:
        return tuple(
            item for item in self._descriptors.values() if item.action_id == action_id
        )

    def projection(self, action_id: str) -> list[JsonObject]:
        return [
            {
                "consumer": item.consumer,
                "operation": item.operation.value,
                "implementations": [
                    implementation.value for implementation in item.implementations
                ],
                "options": {
                    implementation.value: (
                        {"max_output_tokens": {"type": "integer", "minimum": 1}}
                        if implementation is ModelImplementation.LLM_TASK
                        else {
                            "relevance_threshold": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 3,
                            }
                        }
                        if implementation is ModelImplementation.STRUCTURED_DECISION
                        else {}
                    )
                    for implementation in item.implementations
                },
                "embedding_owner": item.embedding_owner,
                "binding": self._bindings[item.consumer].to_json()
                if item.consumer in self._bindings
                else None,
            }
            for item in self.for_action(action_id)
        ]
