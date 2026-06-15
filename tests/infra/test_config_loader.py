from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import pytest

from tinysoul.infra.config import ConfigError, ConfigLoader, ConfigSource


class LogLevel(Enum):
    NORMAL = "normal"
    DEBUG = "debug"


@dataclass(frozen=True)
class RuntimeSettings:
    max_turns: int = 20
    parallel_workers: int = 5
    timeout: float = 10.0
    enabled: bool = True
    workspace: Path = Path(".")
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LoggingSettings:
    level: LogLevel = LogLevel.NORMAL
    color: bool = True


def test_loader_uses_dataclass_defaults_when_no_source() -> None:
    loader = ConfigLoader([])

    settings = loader.load_section("infra.runtime", RuntimeSettings)

    assert settings.max_turns == 20
    assert settings.parallel_workers == 5


def test_loader_applies_sources_in_order() -> None:
    loader = ConfigLoader(
        [
            ConfigSource("project", {"infra.runtime.max_turns": 21}),
            ConfigSource("dotenv", {"infra.runtime.max_turns": "22"}),
            ConfigSource("environment", {"infra.runtime.max_turns": "23"}),
            ConfigSource("overrides", {"infra.runtime.max_turns": 24}),
        ]
    )

    settings = loader.load_section("infra.runtime", RuntimeSettings)

    assert settings.max_turns == 24


def test_loader_converts_supported_types() -> None:
    loader = ConfigLoader(
        [
            ConfigSource(
                "source",
                {
                    "infra.runtime.max_turns": "30",
                    "infra.runtime.parallel_workers": "6",
                    "infra.runtime.timeout": "2.5",
                    "infra.runtime.enabled": "false",
                    "infra.runtime.workspace": "work",
                    "infra.runtime.tags": "a, b,c",
                    "infra.logging.level": "debug",
                    "infra.logging.color": "yes",
                },
            )
        ]
    )

    runtime = loader.load_section("infra.runtime", RuntimeSettings)
    logging = loader.load_section("infra.logging", LoggingSettings)

    assert runtime.max_turns == 30
    assert runtime.parallel_workers == 6
    assert runtime.timeout == pytest.approx(2.5)
    assert runtime.enabled is False
    assert runtime.workspace == Path("work")
    assert runtime.tags == ["a", "b", "c"]
    assert logging.level is LogLevel.DEBUG
    assert logging.color is True


def test_loader_reports_unknown_project_key() -> None:
    loader = ConfigLoader([ConfigSource("project", {"infra.runtime.unknown": 1})])

    with pytest.raises(ConfigError) as exc_info:
        loader.load_section("infra.runtime", RuntimeSettings)

    message = str(exc_info.value)
    assert "Unknown configuration key" in message
    assert "infra.runtime.unknown" in message
    assert "project" in message


def test_loader_reports_type_errors_with_source_and_value() -> None:
    loader = ConfigLoader([ConfigSource("project", {"infra.runtime.max_turns": "bad"})])

    with pytest.raises(ConfigError) as exc_info:
        loader.load_section("infra.runtime", RuntimeSettings)

    message = str(exc_info.value)
    assert "infra.runtime.max_turns" in message
    assert "project" in message
    assert "bad" in message
    assert "int" in message


def test_from_project_root_precedence(local_tmp: Path, monkeypatch) -> None:
    (local_tmp / "tinysoul.toml").write_text(
        "[infra.runtime]\nmax_turns = 21\n", encoding="utf-8"
    )
    (local_tmp / ".env").write_text(
        "TINYSOUL_INFRA_RUNTIME_MAX_TURNS=22\n", encoding="utf-8"
    )
    monkeypatch.setenv("TINYSOUL_INFRA_RUNTIME_MAX_TURNS", "23")

    loader = ConfigLoader.from_project_root(
        local_tmp,
        overrides={"infra.runtime.max_turns": 24},
    )
    settings = loader.load_section("infra.runtime", RuntimeSettings)

    assert settings.max_turns == 24
