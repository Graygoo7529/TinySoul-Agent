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
from ..protocol.models import AdapterOptions


@dataclass(frozen=True)
class AdapterOptionSpec:
    id: str
    value_kind: str
    choices: tuple[str, ...] = ()
    minimum: int | None = None
    source: str = "api-mode"
    default: str | bool | None = None
    fixed: bool = False
    requires: tuple[tuple[str, tuple[str, ...]], ...] = ()
    excludes: tuple[str, ...] = ()

    def to_json(self) -> JsonObject:
        return {
            "id": self.id,
            "value_kind": self.value_kind,
            "choices": list(self.choices),
            "minimum": self.minimum,
            "source": self.source,
            "default": self.default,
            "fixed": self.fixed,
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

    def validate_options(
        self,
        options: Mapping[str, object],
        *,
        key: str,
        reasoning_effort: str | None = None,
    ) -> None:
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
        if reasoning_effort is not None and "reasoning_effort" not in specs:
            raise ConfigError("Adapter does not support reasoning effort", key=key)
        reject_unknown_keys(
            options,
            {
                *specs.keys() - {"reasoning_effort"},
                "choices",
                "choice_rules",
                *(("variant",) if self.variants else ()),
            },
            key=key,
        )
        for name, value in options.items():
            if name not in {"variant", "choices", "choice_rules"}:
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
        declaration = AdapterOptions(options)
        selected = {**options, "reasoning_effort": reasoning_effort}
        for name, candidates in declaration.choices.items():
            self._validate_candidates(specs, name, candidates, key=key)
        for rule in declaration.choice_rules:
            when = rule["when"]
            limits = rule["choices"]
            assert isinstance(when, Mapping) and isinstance(limits, Mapping)
            for name, value in when.items():
                self._validate_candidates(specs, name, [value], key=key)
            for name, candidates in limits.items():
                self._validate_candidates(specs, name, candidates, key=key)
        for name, spec in specs.items():
            value = selected.get(name)
            if spec.fixed and value is not None and value != spec.default:
                raise ConfigError(
                    "Adapter option has a fixed value", key=f"{key}.{name}"
                )
            candidates = declaration.available_choices(
                name, selected=selected, defaults=spec.choices or None
            )
            if value is not None and candidates is not None and value not in candidates:
                raise ConfigError(
                    "Selected value is not available for this model",
                    key=f"{key}.{name}",
                )
        if (
            self.api_mode is ApiMode.GOOGLE_GENERATE_CONTENT
            and reasoning_effort is not None
            and "thinking_budget_tokens" in options
        ):
            raise ConfigError("Choose reasoning effort or thinking budget", key=key)
        if self.api_mode is ApiMode.GOOGLE_GENERATE_CONTENT:
            boundaries = options.get("prompt_cache_boundaries", ())
            assert isinstance(boundaries, (tuple, list))
            if len(boundaries) > 1:
                raise ConfigError("Google explicit caching selects one prefix", key=key)
        if "prompt_cache_ttls" in options:
            ttls = options["prompt_cache_ttls"]
            assert isinstance(ttls, Mapping)
            ttl_spec = specs["prompt_cache_ttl"]
            for name, ttl in ttls.items():
                if not isinstance(name, str) or not name:
                    raise ConfigError(
                        "Cache TTL overrides require named boundaries", key=key
                    )
                _validate_option(ttl_spec, ttl, key=f"{key}.prompt_cache_ttls.{name}")
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

    @staticmethod
    def _validate_candidates(
        specs: Mapping[str, AdapterOptionSpec],
        name: object,
        candidates: object,
        *,
        key: str,
    ) -> None:
        if (
            not isinstance(name, str)
            or name not in specs
            or specs[name].value_kind not in {"enum", "string"}
        ):
            raise ConfigError("Choices require a supported string option", key=key)
        if not isinstance(candidates, (list, tuple)):
            raise ConfigError("Choices must be lists", key=key)
        for value in candidates:
            _validate_option(specs[name], value, key=f"{key}.choices.{name}")

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
_EFFORT = (option("reasoning_effort"),)
_CACHE_BOUNDARIES = (
    option("prompt_cache_boundaries", "string_list"),
    option("prompt_cache_ttls", "object"),
)
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
        option("prompt_cache_boundaries", "string_list"),
        option("native_replay", "enum", "none", "content"),
        option("thinking", "enum", "enabled", "disabled", "adaptive"),
        option("tool_choice_policy", "enum", "native", "auto", "omit"),
        option("json_output_with_tools", "enum", "native", "prompt"),
        option("output_token_field", "enum", "max_completion_tokens", "max_tokens"),
    ),
)
_RESPONSES = ApiModeSpec(
    ApiMode.OPENAI_RESPONSES,
    (
        *_BASE,
        *_EFFORT,
        option("prompt_cache_mode", "enum", "implicit", "explicit"),
        replace(
            option("prompt_cache_ttl", "enum", "30m", "12h"),
            requires=(("prompt_cache_mode", ("implicit", "explicit")),),
        ),
        *_CACHE_BOUNDARIES,
        option("native_replay", "enum", "none", "encrypted"),
        option("tool_choice_policy", "enum", "native", "auto"),
        option("json_output_with_tools", "enum", "native", "prompt"),
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
        option("replay_prefix_binding", "boolean"),
        replace(option("tool_choice_policy", "enum", "native", "auto"), default="auto"),
        replace(
            option("thinking_budget_tokens", "integer", minimum=1024),
            requires=(("thinking", ("enabled",)),),
        ),
        replace(
            option("thinking_display", "enum", "summarized", "omitted", "updates"),
            requires=(("thinking", ("adaptive", "enabled")),),
        ),
        *_CACHE_BOUNDARIES,
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
        *_EFFORT,
        option("prompt_cache_boundaries", "string_list"),
        option("tool_choice_policy", "enum", "native", "auto"),
        option("json_output_with_tools", "enum", "native", "prompt"),
        replace(
            option("thinking_budget_tokens", "integer", minimum=-1),
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
        overrides=(replace(option("sampling", "enum", "omit"), default="omit", fixed=True),),
        variants=(
            AdapterVariantSpec(
                "k2",
                (option("thinking", "enum", "enabled", "disabled"),),
                ("reasoning_effort",),
            ),
            AdapterVariantSpec(
                "k3",
                (
                    replace(
                        option("native_replay", "enum", "content"),
                        default="content",
                        fixed=True,
                    ),
                ),
                ("thinking",),
            ),
        ),
        disabled_options=(
            "prompt_cache_mode",
            "prompt_cache_ttl",
            "prompt_cache_boundaries",
            "prompt_cache_ttls",
        ),
    ),
    AdapterSpec(
        AdapterKind.DEEPSEEK,
        _CHAT,
        (option("thinking", "enum", "enabled", "disabled"),),
        disabled_options=(
            "prompt_cache_mode",
            "prompt_cache_ttl",
            "prompt_cache_boundaries",
            "prompt_cache_ttls",
        ),
    ),
    AdapterSpec(
        AdapterKind.GLM,
        _CHAT,
        (
            option("thinking", "enum", "enabled", "disabled"),
            option("do_sample", "boolean"),
            option("user_id"),
        ),
        disabled_options=(
            "prompt_cache_mode",
            "prompt_cache_ttl",
            "prompt_cache_boundaries",
            "prompt_cache_ttls",
        ),
    ),
    AdapterSpec(
        AdapterKind.MINIMAX,
        _CHAT,
        (
            option("thinking", "enum", "disabled", "adaptive"),
            replace(option("reasoning_split", "boolean"), default=True, fixed=True),
            replace(option("sampling", "enum", "omit"), default="omit", fixed=True),
            replace(option("tool_choice_policy", "enum", "omit"), default="omit", fixed=True),
        ),
        disabled_options=(
            "prompt_cache_mode",
            "prompt_cache_ttl",
            "prompt_cache_boundaries",
            "prompt_cache_ttls",
        ),
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
        valid = isinstance(value, (list, tuple)) and all(
            isinstance(item, str) and item == item.strip() and item for item in value
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
