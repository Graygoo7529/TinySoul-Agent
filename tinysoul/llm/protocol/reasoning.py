"""Provider-neutral reasoning and native replay state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tinysoul.infra.json import JsonObject, JsonTypeError, to_json_object

from .adapter_types import AdapterKind, ApiMode
from ..errors import LLMContractError


class ReasoningKeep(StrEnum):
    NONE = "none"
    CONTENT = "content"
    ENCRYPTED = "encrypted"


@dataclass(frozen=True)
class NativeReplay:
    """Ordered opaque provider blocks replayable only on the same route."""

    api_mode: ApiMode
    adapter: AdapterKind
    provider_id: str
    provider_model: str
    ordered_parts: tuple[JsonObject, ...]
    variant: str | None = None
    message_fingerprint: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.api_mode, ApiMode) or not isinstance(
            self.adapter, AdapterKind
        ):
            raise LLMContractError("NativeReplay requires API mode and adapter values")
        if not self.provider_id or not self.provider_model:
            raise LLMContractError("NativeReplay route identity must be non-empty")
        try:
            parts = tuple(to_json_object(item) for item in self.ordered_parts)
        except JsonTypeError as exc:
            raise LLMContractError("NativeReplay parts must be JSON objects") from exc
        if not parts:
            raise LLMContractError("NativeReplay.ordered_parts must be non-empty")
        object.__setattr__(self, "ordered_parts", parts)


@dataclass(frozen=True)
class Reasoning:
    content: str | None = None
    summary: str | None = None
    native_replay: NativeReplay | None = None

    def __post_init__(self) -> None:
        if any(
            value is not None and not isinstance(value, str)
            for value in (self.content, self.summary)
        ):
            raise LLMContractError("Reasoning content and summary must be text or None")
        if self.native_replay is not None and not isinstance(
            self.native_replay, NativeReplay
        ):
            raise LLMContractError(
                "Reasoning.native_replay must be NativeReplay or None"
            )

    @property
    def native_parts(self) -> tuple[JsonObject, ...]:
        """Opaque parts for bounded sizing and digest-only projection."""
        if self.native_replay is None:
            return ()
        return self.native_replay.ordered_parts

    @classmethod
    def text(cls, content: str) -> "Reasoning":
        return cls(content=content)
