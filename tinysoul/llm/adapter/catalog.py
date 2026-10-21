"""API-mode rules composed with model adapter and variant rules.

The configuration boundary and frontend share these effective option definitions.
No SDK clients are created while loading rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from tinysoul.infra.config import ConfigError, reject_unknown_keys
from tinysoul.infra.json import JsonObject, to_json_object

from ..protocol.adapter_types import AdapterKind, ApiMode


@dataclass(frozen=True)
class AdapterOptionSpec:
    id: str
    value_kind: str
    choices: tuple[str, ...] = ()
    minimum: int | None = None
    source: str = "api-mode"
    requires: tuple[tuple[str, tuple[str, ...]], ...] = ()
    excludes: tuple[str, ...] = ()

    def to_json(self) -> JsonObject:
        return {
            "id": self.id,
            "value_kind": self.value_kind,
            "choices": list(self.choices),
            "minimum": self.minimum,
            "source": self.source,
            "requires": {name: list(values) for name, values in self.requires},
            "excludes": list(self.excludes),
        }


@dataclass(frozen=True)
class ApiModeSpec:
    id: ApiMode
    options: tuple[AdapterOptionSpec, ...]


@dataclass(frozen=True)
class AdapterVariantSpec:
    id: str
    option_specs: tuple[AdapterOptionSpec, ...]
    disabled_options: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdapterSpec:
    kind: AdapterKind
    mode: ApiModeSpec
    overrides: tuple[AdapterOptionSpec, ...] = ()
    variants: tuple[AdapterVariantSpec, ...] = ()
    disabled_options: tuple[str, ...] = ()

    @property
    def api_mode(self) -> ApiMode:
        return self.mode.id

    @property
    def common_options(self) -> tuple[AdapterOptionSpec, ...]:
        result = {
            item.id: item
            for item in self.mode.options
            if item.id not in self.disabled_options
        }
        result.update(
            {item.id: replace(item, source="adapter") for item in self.overrides}
        )
        return tuple(result.values())

    def effective_options(
        self, variant: str | None = None
    ) -> tuple[AdapterOptionSpec, ...]:
        result = {item.id: item for item in self.common_options}
        branch = next((item for item in self.variants if item.id == variant), None)
        if branch:
            for key in branch.disabled_options:
                result.pop(key, None)
            result.update(
                {
                    item.id: replace(item, source="variant")
                    for item in branch.option_specs
                }
            )
        return tuple(result.values())

    def validate_options(self, options: Mapping[str, object], *, key: str) -> None:
        variant = options.get("variant")
        if self.variants:
            if not isinstance(variant, str) or variant not in {
                item.id for item in self.variants
            }:
                raise ConfigError(
                    "Adapter variant is required and must be supported",
                    key=f"{key}.variant",
                    value=variant,
                )
        elif variant is not None:
            raise ConfigError(
                "Adapter does not support variants", key=f"{key}.variant", value=variant
            )
        specs = {
            item.id: item
            for item in self.effective_options(
                variant if isinstance(variant, str) else None
            )
        }
        reject_unknown_keys(
            options, {*specs, *(("variant",) if self.variants else ())}, key=key
        )
        for name, value in options.items():
            if name != "variant":
                _validate_option(specs[name], value, key=f"{key}.{name}")
                spec = specs[name]
                if any(
                    options.get(other) not in choices
                    for other, choices in spec.requires
                ):
                    raise ConfigError(
                        "Adapter option requires a different mode", key=f"{key}.{name}"
                    )
                if any(other in options for other in spec.excludes):
                    raise ConfigError(
                        "Choose one option, not both", key=f"{key}.{name}"
                    )
        if "extra_body" in options:
            _validate_extra_body(
                options["extra_body"], key=f"{key}.extra_body", occupied=set(specs)
            )
        if self.api_mode is ApiMode.ANTHROPIC_MESSAGES:
            thinking = options.get("thinking")
            budget = options.get("thinking_budget_tokens")
            if "thinking_display" in options and thinking not in {
                "adaptive",
                "enabled",
            }:
                raise ConfigError(
                    "Thinking display requires adaptive or enabled mode", key=key
                )
            if thinking == "enabled" and budget is None:
                raise ConfigError("Manual thinking requires a token budget", key=key)
            if budget is not None and thinking != "enabled":
                raise ConfigError(
                    "Thinking budget requires manual enabled mode", key=key
                )

    def to_json(self) -> JsonObject:
        from .factory import runtime_adapter_kinds

        available = self.kind in runtime_adapter_kinds()
        return {
            "id": self.kind.value,
            "api_mode": self.api_mode.value,
            "runtime_available": available,
            "runtime_reason": ""
            if available
            else "SDK invocation is not connected yet",
            "common_options": [item.to_json() for item in self.common_options],
            "variants": [
                {
                    "id": branch.id,
                    "options": [
                        item.to_json() for item in self.effective_options(branch.id)
                    ],
                }
                for branch in self.variants
            ],
        }


def option(
    name: str, kind: str = "string", *choices: str, minimum: int | None = None
) -> AdapterOptionSpec:
    return AdapterOptionSpec(name, kind, tuple(choices), minimum)


_BASE = (
    option("sampling", "enum", "pass-through", "omit"),
    option("extra_body", "object"),
)
_EFFORT = (option("reasoning_efforts", "string_list"),)
_CACHE = (
    option("prompt_cache_mode", "enum", "implicit", "explicit"),
    replace(
        option("prompt_cache_ttl", "enum", "30m"),
        requires=(("prompt_cache_mode", ("implicit", "explicit")),),
    ),
)
_CHAT = ApiModeSpec(
    ApiMode.OPENAI_CHAT,
    (
        *_BASE,
        *_EFFORT,
        *_CACHE,
        option("native_replay", "enum", "none", "content"),
        option("output_token_field", "enum", "max_completion_tokens", "max_tokens"),
    ),
)
_RESPONSES = ApiModeSpec(
    ApiMode.OPENAI_RESPONSES,
    (
        *_BASE,
        *_EFFORT,
        *_CACHE,
        option("native_replay", "enum", "none", "encrypted"),
        option("reasoning_summary", "enum", "auto", "concise", "detailed"),
        option("reasoning_mode", "enum", "standard", "pro"),
        option("reasoning_context", "enum", "auto", "current_turn", "all_turns"),
        option("verbosity", "enum", "low", "medium", "high"),
        option("store", "boolean"),
    ),
)
_ANTHROPIC = ApiModeSpec(
    ApiMode.ANTHROPIC_MESSAGES,
    (
        *_BASE,
        *_EFFORT,
        option("native_replay", "enum", "none", "signed"),
        option("thinking", "enum", "adaptive", "enabled", "disabled", "between_tools"),
        replace(
            option("thinking_budget_tokens", "integer", minimum=1024),
            requires=(("thinking", ("enabled",)),),
        ),
        replace(
            option("thinking_display", "enum", "summarized", "omitted"),
            requires=(("thinking", ("adaptive", "enabled")),),
        ),
        option("prompt_cache_mode", "enum", "automatic", "explicit", "disabled"),
        replace(
            option("prompt_cache_ttl", "enum", "5m", "1h"),
            requires=(("prompt_cache_mode", ("automatic", "explicit")),),
        ),
    ),
)
_GOOGLE = ApiModeSpec(
    ApiMode.GOOGLE_GENERATE_CONTENT,
    (
        *_BASE,
        replace(_EFFORT[0], excludes=("thinking_budget_tokens",)),
        replace(
            option("thinking_budget_tokens", "integer", minimum=-1),
            excludes=("reasoning_efforts",),
        ),
        option("native_replay", "enum", "none", "signed"),
        option("include_thoughts", "boolean"),
        option("prompt_cache_mode", "enum", "implicit", "explicit"),
        replace(
            option("prompt_cache_ttl", "integer", minimum=1),
            requires=(("prompt_cache_mode", ("explicit",)),),
        ),
    ),
)

_SPECS = (
    AdapterSpec(AdapterKind.OPENAI_CHAT, _CHAT),
    AdapterSpec(AdapterKind.OPENAI_RESPONSES, _RESPONSES),
    AdapterSpec(AdapterKind.GPT, _RESPONSES),
    AdapterSpec(
        AdapterKind.KIMI,
        _CHAT,
        variants=(
            AdapterVariantSpec(
                "k2",
                (option("thinking", "enum", "enabled", "disabled"),),
                ("reasoning_efforts",),
            ),
            AdapterVariantSpec("k3", (), ("native_replay",)),
        ),
        disabled_options=("prompt_cache_mode", "prompt_cache_ttl"),
    ),
    AdapterSpec(
        AdapterKind.DEEPSEEK,
        _CHAT,
        (option("thinking", "enum", "enabled", "disabled"),),
        disabled_options=("prompt_cache_mode", "prompt_cache_ttl"),
    ),
    AdapterSpec(
        AdapterKind.GLM,
        _CHAT,
        (
            option("thinking", "enum", "enabled", "disabled"),
            option("do_sample", "boolean"),
            option("request_id"),
            option("user_id"),
        ),
        disabled_options=("prompt_cache_mode", "prompt_cache_ttl"),
    ),
    AdapterSpec(
        AdapterKind.MINIMAX,
        _CHAT,
        (
            option("thinking", "enum", "enabled", "disabled", "adaptive"),
            option("reasoning_split", "boolean"),
        ),
        disabled_options=("prompt_cache_mode", "prompt_cache_ttl"),
    ),
    AdapterSpec(AdapterKind.ANTHROPIC_MESSAGES, _ANTHROPIC),
    AdapterSpec(AdapterKind.GOOGLE_GENERATE_CONTENT, _GOOGLE),
)
_BY_KIND = {item.kind: item for item in _SPECS}


def adapter_spec(kind: AdapterKind) -> AdapterSpec:
    return _BY_KIND[kind]


def adapter_specs_json() -> list[JsonObject]:
    return [item.to_json() for item in _SPECS]


def api_modes_json() -> list[JsonObject]:
    from .factory import runtime_adapter_kinds

    modes = {adapter_spec(kind).api_mode for kind in runtime_adapter_kinds()}
    return [
        {"id": mode.id.value, "runtime_available": mode.id in modes}
        for mode in (_CHAT, _RESPONSES, _ANTHROPIC, _GOOGLE)
    ]


def _validate_option(spec: AdapterOptionSpec, value: object, *, key: str) -> None:
    valid = True
    if spec.value_kind in {"string", "enum"}:
        valid = (
            isinstance(value, str)
            and bool(value.strip())
            and (not spec.choices or value in spec.choices)
        )
    elif spec.value_kind == "string_list":
        valid = (
            isinstance(value, (list, tuple))
            and bool(value)
            and all(
                isinstance(item, str) and item == item.strip() and item
                for item in value
            )
        )
        if valid:
            valid = len(set(value)) == len(value)
    elif spec.value_kind == "boolean":
        valid = type(value) is bool
    elif spec.value_kind == "integer":
        valid = type(value) is int and (spec.minimum is None or value >= spec.minimum)
    elif spec.value_kind == "object":
        valid = isinstance(value, Mapping)
    if not valid:
        raise ConfigError(
            "Invalid adapter option",
            key=key,
            value=value,
            expected=" | ".join(spec.choices) or spec.value_kind,
        )


def _validate_extra_body(value: object, *, key: str, occupied: set[str]) -> None:
    try:
        body = to_json_object(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError("extra_body must be a JSON object", key=key) from exc
    reserved = {
        "model",
        "messages",
        "input",
        "contents",
        "system",
        "system_instruction",
        "systemInstruction",
        "tools",
        "tool_choice",
        "tool_config",
        "toolConfig",
        "response_format",
        "text",
        "reasoning",
        "reasoning_effort",
        "thinking",
        "generation_config",
        "generationConfig",
        "output_config",
        "include",
        "max_output_tokens",
        "max_completion_tokens",
        "max_tokens",
        "temperature",
        "top_p",
        "stream",
        "prompt_cache_key",
        "prompt_cache_options",
        "prompt_cache_retention",
        "cache_control",
        "cachedContent",
        "cached_content",
        "thinkingConfig",
        "thinking_config",
        "api_key",
        "authorization",
        "headers",
        "previous_response_id",
        "conversation",
        "instructions",
        "store",
    }
    overlap = (reserved | occupied).intersection(body)
    if overlap:
        raise ConfigError(
            "extra_body cannot override framework-owned fields",
            key=key,
            value=sorted(overlap),
        )
