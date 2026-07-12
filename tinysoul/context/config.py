"""Context module configuration parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from tinysoul.infra.config import ConfigError, reject_unknown_keys


@dataclass(frozen=True)
class ContextSettings:
    """Context composition and compression settings."""

    system_text: str = "You are TinySoul."
    journal: str = ""
    budget_max_chars: int | None = None
    budget_max_image_bytes: int | None = None
    compression_target_ratio: float = 0.80
    trace_chunk_max_chars: int = 12000
    trace_branch_factor: int = 4
    trace_min_hot_entries: int = 2
    trace_recall_max_chars: int = 8000

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
        if not 0 < self.compression_target_ratio < 1:
            raise ConfigError(
                "Context compression_target_ratio must be between 0 and 1",
                key="context.compression_target_ratio",
                value=self.compression_target_ratio,
                expected="float between 0 and 1",
            )
        _require_positive(self.trace_chunk_max_chars, "trace_chunk_max_chars")
        if self.trace_branch_factor < 2:
            raise ConfigError(
                "Context trace_branch_factor must be at least 2",
                key="context.trace_branch_factor",
                value=self.trace_branch_factor,
                expected="int >= 2",
            )
        if self.trace_min_hot_entries < 0:
            raise ConfigError(
                "Context trace_min_hot_entries cannot be negative",
                key="context.trace_min_hot_entries",
                value=self.trace_min_hot_entries,
                expected="non-negative int",
            )
        _require_positive(self.trace_recall_max_chars, "trace_recall_max_chars")


def parse_context_settings(tree: Mapping[str, object]) -> ContextSettings:
    reject_unknown_keys(
        tree,
        {
            "system_text",
            "journal",
            "budget_max_chars",
            "budget_max_image_bytes",
            "compression_target_ratio",
            "trace_chunk_max_chars",
            "trace_branch_factor",
            "trace_min_hot_entries",
            "trace_recall_max_chars",
        },
        key="context",
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
        compression_target_ratio=_optional_float(
            tree,
            "compression_target_ratio",
            default=ContextSettings.compression_target_ratio,
        ),
        trace_chunk_max_chars=_required_optional_int(
            tree,
            "trace_chunk_max_chars",
            default=ContextSettings.trace_chunk_max_chars,
        ),
        trace_branch_factor=_required_optional_int(
            tree,
            "trace_branch_factor",
            default=ContextSettings.trace_branch_factor,
        ),
        trace_min_hot_entries=_required_optional_int(
            tree,
            "trace_min_hot_entries",
            default=ContextSettings.trace_min_hot_entries,
        ),
        trace_recall_max_chars=_required_optional_int(
            tree,
            "trace_recall_max_chars",
            default=ContextSettings.trace_recall_max_chars,
        ),
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


def _required_optional_int(
    tree: Mapping[str, object],
    name: str,
    *,
    default: int,
) -> int:
    value = _optional_int(tree, name, default=default)
    if value is None:
        raise ConfigError(
            "Context configuration value cannot be null",
            key=f"context.{name}",
            value=None,
            expected="int",
        )
    return value


def _optional_float(
    tree: Mapping[str, object],
    name: str,
    *,
    default: float,
) -> float:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            "Context configuration value must be numeric",
            key=f"context.{name}",
            value=value,
            expected="float",
        )
    return float(value)


def _require_positive(value: int, name: str) -> None:
    if value <= 0:
        raise ConfigError(
            "Context configuration value must be positive",
            key=f"context.{name}",
            value=value,
            expected="positive int",
        )
