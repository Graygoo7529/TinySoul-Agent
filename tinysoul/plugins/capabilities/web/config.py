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
DEFAULT_KIMI_SEARCH_MODEL = "kimi-k2.6"
_KIMI_SEARCH_NO_THINKING_MODELS = frozenset({"kimi-k2.5", "kimi-k2.6"})


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
    model: str = DEFAULT_KIMI_SEARCH_MODEL
    max_query_chars: int = 4_000
    max_result_chars: int = 100_000
    max_inline_chars: int = 12_000
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
        if self.model not in _KIMI_SEARCH_NO_THINKING_MODELS:
            raise ConfigError(
                "Kimi Search model does not support the required no-thinking protocol",
                key="capabilities.web.search_by_kimi.model",
                value=self.model,
                expected="kimi-k2.5 or kimi-k2.6",
            )
        for name in (
            "max_query_chars",
            "max_result_chars",
            "max_inline_chars",
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
class WebDiscoverySettings:
    enabled: bool = False
    max_visit_depth: int = 1
    max_pages: int = 20
    max_candidates: int = 100
    max_links_per_page: int = 200
    max_result_chars: int = 100_000
    max_inline_chars: int = 12_000
    max_concurrency: int = 2
    max_tasks_per_minute: int = 30
    max_request_retries: int = 1
    max_crawl_seconds: int = 90
    allow_query_links: bool = False

    def __post_init__(self) -> None:
        key = "capabilities.web.discover_pages"
        _bool(self.enabled, key=f"{key}.enabled")
        _bool(self.allow_query_links, key=f"{key}.allow_query_links")
        _non_negative(self.max_visit_depth, key=f"{key}.max_visit_depth")
        _non_negative(self.max_request_retries, key=f"{key}.max_request_retries")
        for name in (
            "max_pages",
            "max_candidates",
            "max_links_per_page",
            "max_result_chars",
            "max_inline_chars",
            "max_concurrency",
            "max_tasks_per_minute",
            "max_crawl_seconds",
        ):
            _positive(getattr(self, name), key=f"{key}.{name}")
        if self.max_inline_chars > self.max_result_chars:
            raise ConfigError(
                "Discovery inline result limit cannot exceed the full result limit",
                key=f"{key}.max_inline_chars",
                value=self.max_inline_chars,
                expected=f"<= {self.max_result_chars}",
            )
        if self.max_inline_chars < 1_000:
            raise ConfigError(
                "Discovery inline result limit is too small for a stable result shape",
                key=f"{key}.max_inline_chars",
                value=self.max_inline_chars,
                expected=">= 1000",
            )
        if self.max_concurrency > self.max_pages:
            raise ConfigError(
                "Discovery concurrency cannot exceed the page budget",
                key=f"{key}.max_concurrency",
                value=self.max_concurrency,
                expected=f"<= {self.max_pages}",
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
    discover_pages: WebDiscoverySettings = field(default_factory=WebDiscoverySettings)
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
        if not isinstance(self.discover_pages, WebDiscoverySettings):
            raise ConfigError(
                "Web discovery settings are invalid",
                key="capabilities.web.discover_pages",
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
            "discover_pages",
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
        discover_pages=_parse_discovery(tree.get("discover_pages")),
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


def _parse_discovery(value: object) -> WebDiscoverySettings:
    key = "capabilities.web.discover_pages"
    tree = _table(value, key=key)
    reject_unknown_keys(
        tree,
        {
            "enabled",
            "max_visit_depth",
            "max_pages",
            "max_candidates",
            "max_links_per_page",
            "max_result_chars",
            "max_inline_chars",
            "max_concurrency",
            "max_tasks_per_minute",
            "max_request_retries",
            "max_crawl_seconds",
            "allow_query_links",
        },
        key=key,
    )
    defaults = WebDiscoverySettings()
    return WebDiscoverySettings(
        enabled=_bool_value(tree, "enabled", defaults.enabled, key=f"{key}.enabled"),
        max_visit_depth=_int(
            tree, "max_visit_depth", defaults.max_visit_depth, key=key
        ),
        max_pages=_int(tree, "max_pages", defaults.max_pages, key=key),
        max_candidates=_int(
            tree, "max_candidates", defaults.max_candidates, key=key
        ),
        max_links_per_page=_int(
            tree, "max_links_per_page", defaults.max_links_per_page, key=key
        ),
        max_result_chars=_int(
            tree, "max_result_chars", defaults.max_result_chars, key=key
        ),
        max_inline_chars=_int(
            tree, "max_inline_chars", defaults.max_inline_chars, key=key
        ),
        max_concurrency=_int(
            tree, "max_concurrency", defaults.max_concurrency, key=key
        ),
        max_tasks_per_minute=_int(
            tree,
            "max_tasks_per_minute",
            defaults.max_tasks_per_minute,
            key=key,
        ),
        max_request_retries=_int(
            tree,
            "max_request_retries",
            defaults.max_request_retries,
            key=key,
        ),
        max_crawl_seconds=_int(
            tree, "max_crawl_seconds", defaults.max_crawl_seconds, key=key
        ),
        allow_query_links=_bool_value(
            tree,
            "allow_query_links",
            defaults.allow_query_links,
            key=f"{key}.allow_query_links",
        ),
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


def _non_negative(value: object, *, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(
            "Web capability setting must be non-negative",
            key=key,
            value=value,
            expected="non-negative int",
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
