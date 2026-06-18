"""GLM provider adapter."""

from __future__ import annotations

from collections.abc import Mapping

from tinysoul.llm.config import ProviderApiStyle, ProviderSpec

from .base import ProviderError, ProviderErrorKind
from .openai_sdk import (
    OpenAIAdapterBehavior,
    OpenAIChatCompletionsClient,
    OpenAICompatibleChatAdapter,
)


class GlmProviderBehavior(OpenAIAdapterBehavior):
    """GLM-specific option mapping."""

    def apply_options(
        self,
        kwargs: dict[str, object],
        options: Mapping[str, object] | None,
    ) -> None:
        _rename_max_tokens(kwargs)
        if not options:
            return

        extra_body: dict[str, object] = {}
        for key, value in options.items():
            if key == "thinking":
                extra_body["thinking"] = _thinking_option(value)
                continue
            if key == "reasoning_effort":
                kwargs[key] = _string_option(value, key=key)
                continue
            if key == "do_sample":
                kwargs[key] = _bool_option(value, key=key)
                continue
            if key == "top_p":
                kwargs[key] = _number_option(value, key=key)
                continue
            if key in {"request_id", "user_id"}:
                kwargs[key] = _string_option(value, key=key)
                continue
            raise ProviderError(
                f"Unsupported GLM provider option: {key}",
                kind=ProviderErrorKind.CONFIG,
            )

        if extra_body:
            kwargs["extra_body"] = extra_body


class GlmProviderAdapter(OpenAICompatibleChatAdapter):
    """GLM OpenAI-compatible Chat Completions adapter."""

    def __init__(
        self,
        *,
        provider: ProviderSpec,
        api_key: str,
        completions: OpenAIChatCompletionsClient | None = None,
    ) -> None:
        if provider.api_style is not ProviderApiStyle.OPENAI_CHAT:
            raise ProviderError(
                "GLM provider requires openai_chat API style",
                kind=ProviderErrorKind.CONFIG,
            )
        super().__init__(
            provider=provider,
            api_key=api_key,
            completions=completions,
            behavior=GlmProviderBehavior(),
        )


def _rename_max_tokens(kwargs: dict[str, object]) -> None:
    value = kwargs.pop("max_completion_tokens", None)
    if value is not None:
        kwargs["max_tokens"] = value


def _thinking_option(value: object) -> dict[str, object]:
    if isinstance(value, str):
        if value not in {"enabled", "disabled"}:
            raise ProviderError(
                "GLM thinking must be 'enabled' or 'disabled'",
                kind=ProviderErrorKind.CONFIG,
            )
        return {"type": value}
    if isinstance(value, Mapping):
        raw_type = value.get("type")
        if raw_type not in {"enabled", "disabled"}:
            raise ProviderError(
                "GLM thinking.type must be 'enabled' or 'disabled'",
                kind=ProviderErrorKind.CONFIG,
            )
        result = {str(key): item for key, item in value.items()}
        clear_thinking = result.get("clear_thinking")
        if clear_thinking is not None and not isinstance(clear_thinking, bool):
            raise ProviderError(
                "GLM thinking.clear_thinking must be a boolean",
                kind=ProviderErrorKind.CONFIG,
            )
        return result
    raise ProviderError(
        "GLM thinking must be a string or table",
        kind=ProviderErrorKind.CONFIG,
    )


def _string_option(value: object, *, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProviderError(
            f"GLM {key} must be a non-empty string",
            kind=ProviderErrorKind.CONFIG,
        )
    return value


def _bool_option(value: object, *, key: str) -> bool:
    if not isinstance(value, bool):
        raise ProviderError(
            f"GLM {key} must be a boolean",
            kind=ProviderErrorKind.CONFIG,
        )
    return value


def _number_option(value: object, *, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderError(
            f"GLM {key} must be a number",
            kind=ProviderErrorKind.CONFIG,
        )
    return float(value)
