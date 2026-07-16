"""Web capability settings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys


DEFAULT_MAX_SOURCE_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_OUTPUT_CHARS = 1_000_000
DEFAULT_MAX_EXCERPT_CHARS = 600
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_USER_AGENT = "TinySoul-Agent/0.1"


@dataclass(frozen=True)
class WebFetchSettings:
    enabled: bool = True

    def __post_init__(self) -> None:
        _bool(self.enabled, key="capabilities.web.fetch.enabled")


@dataclass(frozen=True)
class KimiSearchSettings:
    enabled: bool = False
    base_url: str = "https://api.moonshot.cn/v1"
    api_key_env: str = "KIMI_SEARCH_API_KEY"
    model: str = "kimi-k3"
    max_query_chars: int = 4_000
    max_result_chars: int = 100_000
    max_inline_chars: int = 12_000
    max_results: int = 10
    max_snippet_chars: int = 800
    max_tool_rounds: int = 6
    max_search_tokens: int = 100_000
    max_output_tokens: int = 8_192

    def __post_init__(self) -> None:
        _bool(self.enabled, key="capabilities.web.search_by_kimi.enabled")
        for name in ("base_url", "api_key_env", "model"):
            _non_empty_string(
                getattr(self, name),
                key=f"capabilities.web.search_by_kimi.{name}",
            )
        for name in (
            "max_query_chars",
            "max_result_chars",
            "max_inline_chars",
            "max_results",
            "max_snippet_chars",
            "max_tool_rounds",
            "max_search_tokens",
            "max_output_tokens",
        ):
            _positive(
                getattr(self, name),
                key=f"capabilities.web.search_by_kimi.{name}",
            )
        if self.max_inline_chars > self.max_result_chars:
            raise ConfigError(
                "Kimi inline result limit cannot exceed the full result limit",
                key="capabilities.web.search_by_kimi.max_inline_chars",
                value=self.max_inline_chars,
                expected=f"<= {self.max_result_chars}",
            )
        if self.max_inline_chars < 1_000:
            raise ConfigError(
                "Kimi inline result limit is too small for a stable result shape",
                key="capabilities.web.search_by_kimi.max_inline_chars",
                value=self.max_inline_chars,
                expected=">= 1000",
            )


@dataclass(frozen=True)
class WebSettings:
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS
    max_excerpt_chars: int = DEFAULT_MAX_EXCERPT_CHARS
    request_timeout_seconds: int = DEFAULT_REQUEST_TIMEOUT_SECONDS
    max_redirects: int = DEFAULT_MAX_REDIRECTS
    user_agent: str = DEFAULT_USER_AGENT
    search_by_kimi: KimiSearchSettings = field(default_factory=KimiSearchSettings)
    fetch_with_defuddle: WebFetchSettings = field(
        default_factory=lambda: WebFetchSettings(enabled=False)
    )
    fetch_with_trafilatura: WebFetchSettings = field(default_factory=WebFetchSettings)

    def __post_init__(self) -> None:
        for name in (
            "max_source_bytes",
            "max_output_chars",
            "max_excerpt_chars",
            "request_timeout_seconds",
            "max_redirects",
        ):
            _positive(getattr(self, name), key=f"capabilities.web.{name}")
        _non_empty_string(self.user_agent, key="capabilities.web.user_agent")
        if not isinstance(self.search_by_kimi, KimiSearchSettings):
            raise ConfigError(
                "Kimi search settings are invalid",
                key="capabilities.web.search_by_kimi",
            )
        for name in ("fetch_with_defuddle", "fetch_with_trafilatura"):
            if not isinstance(getattr(self, name), WebFetchSettings):
                raise ConfigError(
                    "Web fetch settings are invalid",
                    key=f"capabilities.web.{name}",
                )


def parse_web_settings(tree: Mapping[str, object]) -> WebSettings:
    """Parse and validate the Web capability subtree."""

    reject_unknown_keys(
        tree,
        {
            "max_source_bytes",
            "max_output_chars",
            "max_excerpt_chars",
            "request_timeout_seconds",
            "max_redirects",
            "user_agent",
            "search_by_kimi",
            "fetch_with_defuddle",
            "fetch_with_trafilatura",
        },
        key="capabilities.web",
    )
    return WebSettings(
        max_source_bytes=_int(tree, "max_source_bytes", DEFAULT_MAX_SOURCE_BYTES),
        max_output_chars=_int(tree, "max_output_chars", DEFAULT_MAX_OUTPUT_CHARS),
        max_excerpt_chars=_int(
            tree,
            "max_excerpt_chars",
            DEFAULT_MAX_EXCERPT_CHARS,
        ),
        request_timeout_seconds=_int(
            tree,
            "request_timeout_seconds",
            DEFAULT_REQUEST_TIMEOUT_SECONDS,
        ),
        max_redirects=_int(tree, "max_redirects", DEFAULT_MAX_REDIRECTS),
        user_agent=_string(tree, "user_agent", DEFAULT_USER_AGENT),
        search_by_kimi=_parse_kimi_search(tree.get("search_by_kimi")),
        fetch_with_defuddle=_parse_fetch(
            tree.get("fetch_with_defuddle"),
            name="fetch_with_defuddle",
            default=False,
        ),
        fetch_with_trafilatura=_parse_fetch(
            tree.get("fetch_with_trafilatura"),
            name="fetch_with_trafilatura",
            default=True,
        ),
    )


def _parse_kimi_search(value: object) -> KimiSearchSettings:
    key = "capabilities.web.search_by_kimi"
    tree = _table(value, key=key)
    reject_unknown_keys(
        tree,
        {
            "enabled",
            "base_url",
            "api_key_env",
            "model",
            "max_query_chars",
            "max_result_chars",
            "max_inline_chars",
            "max_results",
            "max_snippet_chars",
            "max_tool_rounds",
            "max_search_tokens",
            "max_output_tokens",
        },
        key=key,
    )
    defaults = KimiSearchSettings()
    return KimiSearchSettings(
        enabled=_bool_value(tree, "enabled", defaults.enabled, key=f"{key}.enabled"),
        base_url=_string(tree, "base_url", defaults.base_url, key=key),
        api_key_env=_string(tree, "api_key_env", defaults.api_key_env, key=key),
        model=_string(tree, "model", defaults.model, key=key),
        max_query_chars=_int(tree, "max_query_chars", defaults.max_query_chars, key=key),
        max_result_chars=_int(
            tree,
            "max_result_chars",
            defaults.max_result_chars,
            key=key,
        ),
        max_inline_chars=_int(
            tree,
            "max_inline_chars",
            defaults.max_inline_chars,
            key=key,
        ),
        max_results=_int(tree, "max_results", defaults.max_results, key=key),
        max_snippet_chars=_int(
            tree,
            "max_snippet_chars",
            defaults.max_snippet_chars,
            key=key,
        ),
        max_tool_rounds=_int(
            tree,
            "max_tool_rounds",
            defaults.max_tool_rounds,
            key=key,
        ),
        max_search_tokens=_int(
            tree,
            "max_search_tokens",
            defaults.max_search_tokens,
            key=key,
        ),
        max_output_tokens=_int(
            tree,
            "max_output_tokens",
            defaults.max_output_tokens,
            key=key,
        ),
    )


def _parse_fetch(value: object, *, name: str, default: bool) -> WebFetchSettings:
    key = f"capabilities.web.{name}"
    tree = _table(value, key=key)
    reject_unknown_keys(tree, {"enabled"}, key=key)
    return WebFetchSettings(
        enabled=_bool_value(tree, "enabled", default, key=f"{key}.enabled")
    )


def _table(value: object, *, key: str) -> Mapping[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(
            "Web capability value must be a table",
            key=key,
            value=value,
            expected="table",
        )
    return cast(Mapping[str, object], value)


def _int(
    tree: Mapping[str, object],
    name: str,
    default: int,
    *,
    key: str = "capabilities.web",
) -> int:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Web capability value must be an integer",
            key=f"{key}.{name}",
            value=value,
            expected="int",
        )
    return value


def _string(
    tree: Mapping[str, object],
    name: str,
    default: str,
    *,
    key: str = "capabilities.web",
) -> str:
    value = tree.get(name, default)
    if not isinstance(value, str) or not value:
        raise ConfigError(
            "Web capability value must be a non-empty string",
            key=f"{key}.{name}",
            value=value,
            expected="str",
        )
    return value


def _bool_value(
    tree: Mapping[str, object],
    name: str,
    default: bool,
    *,
    key: str,
) -> bool:
    value = tree.get(name, default)
    _bool(value, key=key)
    return cast(bool, value)


def _positive(value: object, *, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(
            "Web capability setting must be positive",
            key=key,
            value=value,
            expected="positive int",
        )


def _bool(value: object, *, key: str) -> None:
    if not isinstance(value, bool):
        raise ConfigError(
            "Web capability setting must be a boolean",
            key=key,
            value=value,
            expected="bool",
        )


def _non_empty_string(value: object, *, key: str) -> None:
    if not isinstance(value, str) or not value:
        raise ConfigError(
            "Web capability setting must be a non-empty string",
            key=key,
            value=value,
            expected="str",
        )
