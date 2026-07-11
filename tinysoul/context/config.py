"""Context module configuration parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from tinysoul.infra.config import ConfigError


@dataclass(frozen=True)
class ContextSettings:
    """Context composition and compression settings."""

    system_text: str = "You are TinySoul."
    journal: str = ""
    budget_max_chars: int | None = None
    budget_max_image_bytes: int | None = None
    keep_recent: int = 12

    def __post_init__(self) -> None:
        if not self.system_text:
            raise ConfigError(
                "Context system_text must be non-empty",
                key="context.system_text",
                value=self.system_text,
                expected="non-empty str",
            )
        if self.budget_max_chars is not None and self.budget_max_chars <= 0:
            raise ConfigError(
                "Context budget_max_chars must be positive",
                key="context.budget_max_chars",
                value=self.budget_max_chars,
                expected="positive int",
            )
        if (
            self.budget_max_image_bytes is not None
            and self.budget_max_image_bytes <= 0
        ):
            raise ConfigError(
                "Context budget_max_image_bytes must be positive",
                key="context.budget_max_image_bytes",
                value=self.budget_max_image_bytes,
                expected="positive int",
            )
        if self.keep_recent < 0:
            raise ConfigError(
                "Context keep_recent cannot be negative",
                key="context.keep_recent",
                value=self.keep_recent,
                expected="non-negative int",
            )


def parse_context_settings(tree: Mapping[str, object]) -> ContextSettings:
    keep_recent = _optional_int(
        tree,
        "keep_recent",
        default=ContextSettings.keep_recent,
    )
    if keep_recent is None:
        raise ConfigError(
            "Context keep_recent cannot be null",
            key="context.keep_recent",
            value=None,
            expected="int",
        )
    return ContextSettings(
        system_text=_optional_str(
            tree,
            "system_text",
            default=ContextSettings.system_text,
        ),
        journal=_optional_str(tree, "journal", default="", allow_empty=True),
        budget_max_chars=_optional_int(
            tree,
            "budget_max_chars",
            default=None,
        ),
        budget_max_image_bytes=_optional_int(
            tree,
            "budget_max_image_bytes",
            default=None,
        ),
        keep_recent=keep_recent,
    )


def _optional_str(
    tree: Mapping[str, object],
    name: str,
    *,
    default: str,
    allow_empty: bool = False,
) -> str:
    value = tree.get(name, default)
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ConfigError(
            "Context configuration value must be a string",
            key=f"context.{name}",
            value=value,
            expected="str",
        )
    return value


def _optional_int(
    tree: Mapping[str, object],
    name: str,
    *,
    default: int | None,
) -> int | None:
    value = tree.get(name, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Context configuration value must be an integer",
            key=f"context.{name}",
            value=value,
            expected="int",
        )
    return value
