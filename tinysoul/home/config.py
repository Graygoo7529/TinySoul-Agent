"""Agent Home configuration parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys

DEFAULT_MAX_READ_CHARS = 4000
DEFAULT_MAX_WRITE_CHARS = 16000
DEFAULT_MEMORY_CHUNK_MAX_CHARS = 12000
DEFAULT_MEMORY_SOURCE_MAX_CHARS = 240000
DEFAULT_MEMORY_MAX_CALLS = 48
DEFAULT_MEMORY_VALIDATION_RETRIES = 2


@dataclass(frozen=True)
class MemoryMaintenanceSettings:
    """Bounded Memory consolidation settings owned by Agent Home."""

    chunk_max_chars: int = DEFAULT_MEMORY_CHUNK_MAX_CHARS
    source_max_chars: int = DEFAULT_MEMORY_SOURCE_MAX_CHARS
    max_calls: int = DEFAULT_MEMORY_MAX_CALLS
    validation_retries: int = DEFAULT_MEMORY_VALIDATION_RETRIES

    def __post_init__(self) -> None:
        for name in ("chunk_max_chars", "source_max_chars", "max_calls"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ConfigError(
                    "Agent Home Memory setting must be positive",
                    key=f"home.memory.{name}",
                    value=value,
                    expected="positive int",
                )
        if self.chunk_max_chars < 512:
            raise ConfigError(
                "Agent Home Memory chunk budget is too small",
                key="home.memory.chunk_max_chars",
                value=self.chunk_max_chars,
                expected="int >= 512",
            )
        if self.source_max_chars < self.chunk_max_chars:
            raise ConfigError(
                "Agent Home Memory source budget must cover one chunk",
                key="home.memory.source_max_chars",
                value=self.source_max_chars,
                expected="int >= chunk_max_chars",
            )
        if self.max_calls < 2:
            raise ConfigError(
                "Agent Home Memory call budget must allow reduce and final calls",
                key="home.memory.max_calls",
                value=self.max_calls,
                expected="int >= 2",
            )
        if (
            isinstance(self.validation_retries, bool)
            or not isinstance(self.validation_retries, int)
            or self.validation_retries < 0
        ):
            raise ConfigError(
                "Agent Home Memory validation retries cannot be negative",
                key="home.memory.validation_retries",
                value=self.validation_retries,
                expected="non-negative int",
            )


@dataclass(frozen=True)
class AgentHomeSettings:
    """Agent Home module settings."""

    original_root: Path
    runtime_root: Path
    max_read_chars: int = DEFAULT_MAX_READ_CHARS
    max_write_chars: int = DEFAULT_MAX_WRITE_CHARS
    memory: MemoryMaintenanceSettings = field(
        default_factory=MemoryMaintenanceSettings
    )

    def __post_init__(self) -> None:
        if not isinstance(self.original_root, Path):
            raise ConfigError(
                "Agent Home root must be a path",
                key="home.root",
                value=self.original_root,
                expected="path",
            )
        if not isinstance(self.runtime_root, Path):
            raise ConfigError(
                "Agent Home runtime_root must be a path",
                key="home.runtime_root",
                value=self.runtime_root,
                expected="path",
            )
        original_root = self.original_root.resolve()
        runtime_root = self.runtime_root.resolve()
        if (
            original_root == runtime_root
            or original_root in runtime_root.parents
            or runtime_root in original_root.parents
        ):
            raise ConfigError(
                "Agent Home original and runtime roots must not overlap",
                key="home.runtime_root",
                value=str(self.runtime_root),
                expected="non-overlapping path",
            )
        if (
            isinstance(self.max_read_chars, bool)
            or not isinstance(self.max_read_chars, int)
            or self.max_read_chars <= 0
        ):
            raise ConfigError(
                "Agent Home max_read_chars must be positive",
                key="home.max_read_chars",
                value=self.max_read_chars,
                expected="positive int",
            )
        if not isinstance(self.memory, MemoryMaintenanceSettings):
            raise ConfigError(
                "Agent Home memory settings are invalid",
                key="home.memory",
                value=type(self.memory).__name__,
                expected="MemoryMaintenanceSettings",
            )
        if (
            isinstance(self.max_write_chars, bool)
            or not isinstance(self.max_write_chars, int)
            or self.max_write_chars <= 0
        ):
            raise ConfigError(
                "Agent Home max_write_chars must be positive",
                key="home.max_write_chars",
                value=self.max_write_chars,
                expected="positive int",
            )


def parse_agent_home_settings(
    tree: Mapping[str, object],
    *,
    project_root: Path,
) -> AgentHomeSettings:
    reject_unknown_keys(
        tree,
        {"root", "runtime_root", "max_read_chars", "max_write_chars", "memory"},
        key="home",
    )
    original_root = _optional_path(
        tree,
        "root",
        default=project_root / "home",
        project_root=project_root,
    )
    return AgentHomeSettings(
        original_root=original_root,
        runtime_root=_optional_path(
            tree,
            "runtime_root",
            default=project_root / "runtime" / "home",
            project_root=project_root,
        ),
        max_read_chars=_optional_int(
            tree,
            "max_read_chars",
            default=DEFAULT_MAX_READ_CHARS,
        ),
        max_write_chars=_optional_int(
            tree,
            "max_write_chars",
            default=DEFAULT_MAX_WRITE_CHARS,
        ),
        memory=_parse_memory_settings(tree.get("memory")),
    )


def _parse_memory_settings(value: object) -> MemoryMaintenanceSettings:
    if value is None:
        return MemoryMaintenanceSettings()
    if not isinstance(value, Mapping):
        raise ConfigError(
            "Agent Home memory configuration must be a table",
            key="home.memory",
            value=value,
            expected="table",
        )
    tree = cast(Mapping[str, object], value)
    reject_unknown_keys(
        tree,
        {
            "chunk_max_chars",
            "source_max_chars",
            "max_calls",
            "validation_retries",
        },
        key="home.memory",
    )
    return MemoryMaintenanceSettings(
        chunk_max_chars=_memory_int(
            tree,
            "chunk_max_chars",
            DEFAULT_MEMORY_CHUNK_MAX_CHARS,
        ),
        source_max_chars=_memory_int(
            tree,
            "source_max_chars",
            DEFAULT_MEMORY_SOURCE_MAX_CHARS,
        ),
        max_calls=_memory_int(tree, "max_calls", DEFAULT_MEMORY_MAX_CALLS),
        validation_retries=_memory_int(
            tree,
            "validation_retries",
            DEFAULT_MEMORY_VALIDATION_RETRIES,
        ),
    )


def _optional_path(
    tree: Mapping[str, object],
    name: str,
    *,
    default: Path,
    project_root: Path,
) -> Path:
    value = tree.get(name)
    if value is None:
        return default
    if not isinstance(value, str) or not value:
        raise ConfigError(
            "Agent Home configuration value must be a non-empty path string",
            key=f"home.{name}",
            value=value,
            expected="str",
        )
    path = Path(value)
    if path.is_absolute():
        return path
    return project_root / path


def _optional_int(
    tree: Mapping[str, object],
    name: str,
    *,
    default: int,
) -> int:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Agent Home configuration value must be an integer",
            key=f"home.{name}",
            value=value,
            expected="int",
        )
    return value


def _memory_int(
    tree: Mapping[str, object],
    name: str,
    default: int,
) -> int:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Agent Home Memory configuration value must be an integer",
            key=f"home.memory.{name}",
            value=value,
            expected="int",
        )
    return value
