"""Provider-neutral reasoning and native replay state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tinysoul.infra.json import JsonObject, JsonTypeError, to_json_object

from ..errors import LLMContractError
from .adapter_types import AdapterKind, ApiMode


class NativeReplayMode(StrEnum):
    """One shared vocabulary for replay policy and captured native state."""

    NONE = "none"
    CONTENT = "content"
    ENCRYPTED = "encrypted"
    SIGNED = "signed"


@dataclass(frozen=True)
class NativeReplay:
    """Response data needed to replay an API-native assistant turn.

    ``mode`` is also the model option used to request retention. The object
    is the immutable route-bound state captured from one provider response;
    the adapter must match the route and fingerprint before using its opaque
    items. ``SIGNED`` covers Anthropic thinking blocks and Google thought
    signatures, while ``ENCRYPTED`` covers OpenAI Responses reasoning items.
    """

    mode: NativeReplayMode
    api_mode: ApiMode
    adapter: AdapterKind
    provider_id: str
    provider_model: str
    ordered_items: tuple[JsonObject, ...]
    message_fingerprint: str
    variant: str | None = None

    def __post_init__(self) -> None:
        if self.mode is NativeReplayMode.NONE or not isinstance(
            self.mode, NativeReplayMode
        ):
            raise LLMContractError(
                "NativeReplay.mode must describe retained native state"
            )
        if not isinstance(self.api_mode, ApiMode) or not isinstance(
            self.adapter, AdapterKind
        ):
            raise LLMContractError("NativeReplay requires API mode and adapter values")
        if not self.provider_id or not self.provider_model:
            raise LLMContractError("NativeReplay route identity must be non-empty")
        if (
            not isinstance(self.message_fingerprint, str)
            or not self.message_fingerprint
        ):
            raise LLMContractError("NativeReplay.message_fingerprint must be non-empty")
        try:
            parts = tuple(to_json_object(item) for item in self.ordered_items)
        except JsonTypeError as exc:
            raise LLMContractError("NativeReplay parts must be JSON objects") from exc
        if not parts:
            raise LLMContractError("NativeReplay.ordered_items must be non-empty")
        object.__setattr__(self, "ordered_items", parts)


@dataclass(frozen=True)
class Reasoning:
    summary: str | None = None
    native_replay: NativeReplay | None = None

    def __post_init__(self) -> None:
        if self.summary is not None and not isinstance(self.summary, str):
            raise LLMContractError("Reasoning summary must be text or None")
        if self.native_replay is not None and not isinstance(
            self.native_replay, NativeReplay
        ):
            raise LLMContractError(
                "Reasoning.native_replay must be NativeReplay or None"
            )

    @property
    def native_items(self) -> tuple[JsonObject, ...]:
        """Opaque parts for context capacity accounting."""
        if self.native_replay is None:
            return ()
        return self.native_replay.ordered_items
