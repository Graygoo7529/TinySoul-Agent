from __future__ import annotations

import tomllib
from pathlib import Path
from importlib.resources import files
from importlib.resources.abc import Traversable
from tinysoul.infra.config import ConfigEnvironment
from tinysoul.llm.config.loader import LLMConfigParser

import pytest

pytestmark = pytest.mark.packaging

from tests.support.project import copy_initialized_project
from tinysoul.gateway import cli
from tinysoul.gateway.errors import ProjectInitializationError
from tinysoul.gateway.presentation import InterfaceSettings
from tinysoul.gateway.project.initializer import (
    ProjectConfigProfile,
    ProjectInitializer,
    ProjectResetter,
)
from tinysoul.gateway.project.instance import ProjectInstanceLease
from tinysoul.infra.config import parse_dotenv


@pytest.mark.parametrize("profile", tuple(ProjectConfigProfile))
def test_cli_init_preserves_packaged_resources_and_valid_configuration(
    tmp_path: Path,
    profile: ProjectConfigProfile,
) -> None:
    root = tmp_path / "project"
    assert cli.main(["init", str(root), "--config-profile", profile.value]) == 0
    assets = files("tinysoul.assets")
    expected = {
        **_resource_snapshot(assets.joinpath("common")),
        **_resource_snapshot(assets.joinpath(profile.value)),
    }
    assert _tree_snapshot(root) == expected
    assert (root / "memory").is_dir()
    environment = ConfigEnvironment.from_project_root(root, env={})
    llm = LLMConfigParser().parse(environment.section_tree("llm"))
    assert llm.models.ids()
    example = parse_dotenv((root / ".env.example").read_text(encoding="utf-8"))
    assert _config_environment_references(root / "configs") <= set(example)
    InterfaceSettings.from_mapping(
        tomllib.loads(
            (root / "presentation/configs/interface.toml").read_text(encoding="utf-8")
        )
    )


def _resource_snapshot(root: Traversable) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for item in root.iterdir():
        if item.is_dir():
            result.update(
                {
                    f"{item.name}/{name}": data
                    for name, data in _resource_snapshot(item).items()
                }
            )
        else:
            result[item.name] = item.read_bytes()
    return result


def test_project_initializer_accepts_empty_directory_and_rejects_nonempty(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    outcome = ProjectInitializer().initialize(empty)

    assert outcome.root == empty.resolve()
    assert outcome.file_count == len(_tree_snapshot(empty))
    marker = tmp_path / "existing" / "marker.txt"
    marker.parent.mkdir()
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(ProjectInitializationError, match="must be empty"):
        ProjectInitializer().initialize(marker.parent)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_cli_reset_recreates_development_project_and_preserves_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "agent"
    monkeypatch.setenv("TINYSOUL_INSTANCE_DIR", str(tmp_path / "instances"))
    copy_initialized_project(root)
    expected_development = tmp_path / "expected-development"
    copy_initialized_project(
        expected_development,
        config_profile=ProjectConfigProfile.DEVELOPMENT,
    )
    original_home = (root / "home" / "agent" / "AGENT.md").read_bytes()
    env = b"SUBLYX_API_KEY=secret\r\nMOONSHOT_API_KEY=other\r\n"
    (root / ".env").write_bytes(env)
    (root / "home" / "agent" / "AGENT.md").write_text("custom home", encoding="utf-8")
    (root / "configs" / "llm" / "providers.toml").write_text(
        "custom config", encoding="utf-8"
    )
    action_domain = root / "configs" / "action" / "catalog" / "core" / "domain.toml"
    original_action_domain = action_domain.read_bytes()
    interface = root / "presentation/configs/interface.toml"
    interface.write_text('theme = "dark"', encoding="utf-8")
    action_domain.write_text("custom catalog", encoding="utf-8")
    for relative in (
        "runtime/session/turn.json",
        "archive/old/session.json",
        "memory/2026-07-26.md",
        "unknown-project-data.txt",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("old data", encoding="utf-8")

    result = cli.main(["reset", str(root)])

    captured = capsys.readouterr()
    assert result == 0
    assert "config profile: development" in captured.out
    assert ".env preserved" in captured.out
    assert (root / ".env").read_bytes() == env
    assert (root / "home" / "agent" / "AGENT.md").read_bytes() == original_home
    assert (root / "home" / "agent" / "user" / "user.md").read_bytes() == (
        expected_development / "home" / "agent" / "user" / "user.md"
    ).read_bytes()
    assert action_domain.read_bytes() == original_action_domain
    assert (
        InterfaceSettings.from_mapping(
            tomllib.loads(interface.read_text(encoding="utf-8"))
        )
        == InterfaceSettings()
    )
    assert not (root / "runtime").exists()
    assert not (root / "archive").exists()
    assert not (root / "memory" / "2026-07-26.md").exists()
    assert not (root / "unknown-project-data.txt").exists()
    assert list((root / "memory").iterdir()) == []
    providers = tomllib.loads(
        (root / "configs" / "llm" / "providers.toml").read_text(encoding="utf-8")
    )["llm"]["providers"]
    assert providers
    assert any(spec["enabled"] is True for spec in providers.values())


def test_project_resetter_rejects_nonproject_and_invalid_env(
    tmp_path: Path,
) -> None:
    nonproject = tmp_path / "nonproject"
    nonproject.mkdir()
    marker = nonproject / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(ProjectInitializationError, match="not a TinySoul project"):
        ProjectResetter().reset(nonproject)
    assert marker.read_text(encoding="utf-8") == "keep"

    root = tmp_path / "agent"
    copy_initialized_project(root)
    (root / ".env").mkdir()
    with pytest.raises(ProjectInitializationError, match="env path must be a file"):
        ProjectResetter().reset(root)
    assert (root / "tinysoul.toml").is_file()


def test_project_resetter_restores_previous_project_when_install_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "agent"
    copy_initialized_project(root)
    marker = root / "previous-data.txt"
    marker.write_text("keep", encoding="utf-8")
    original_replace = Path.replace

    def replace_with_install_failure(self: Path, target: Path) -> Path:
        if self.name.startswith(f".{root.name}.tinysoul-reset-new-"):
            raise OSError("injected install failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", replace_with_install_failure)

    with pytest.raises(ProjectInitializationError, match="Failed to install"):
        ProjectResetter().reset(root)
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not tuple(tmp_path.glob(".agent.tinysoul-reset-*"))


def test_project_resetter_retains_previous_project_when_rollback_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "agent"
    copy_initialized_project(root)
    marker = root / "previous-data.txt"
    marker.write_text("keep", encoding="utf-8")
    original_replace = Path.replace

    def replace_with_double_failure(self: Path, target: Path) -> Path:
        if self.name.startswith(f".{root.name}.tinysoul-reset-new-"):
            raise OSError("injected install failure")
        if self.name.startswith(f".{root.name}.tinysoul-reset-old-"):
            raise OSError("injected rollback failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", replace_with_double_failure)

    with pytest.raises(ProjectInitializationError, match="previous data remains at"):
        ProjectResetter().reset(root)
    backup = next(tmp_path.glob(".agent.tinysoul-reset-old-*"))
    assert (backup / "previous-data.txt").read_text(encoding="utf-8") == "keep"


def test_cli_reset_rejects_project_held_by_running_instance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "agent"
    copy_initialized_project(root)
    marker = root / "runtime" / "session" / "active.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("active", encoding="utf-8")
    instance_directory = tmp_path / "instances"
    monkeypatch.setenv("TINYSOUL_INSTANCE_DIR", str(instance_directory))

    with ProjectInstanceLease(root, directory=instance_directory):
        result = cli.main(["reset", str(root)])

    captured = capsys.readouterr()
    assert result == 1
    assert "already running for this project" in captured.err
    assert marker.read_text(encoding="utf-8") == "active"


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _config_environment_references(root: Path) -> set[str]:
    references: set[str] = set()
    for path in sorted(root.rglob("*.toml")):
        references.update(
            _environment_references(tomllib.loads(path.read_text(encoding="utf-8")))
        )
    return references


def _environment_references(value: object) -> set[str]:
    if isinstance(value, dict):
        references: set[str] = set()
        for key, child in value.items():
            if isinstance(key, str) and key.endswith("_env"):
                assert isinstance(child, str) and child
                references.add(child)
                continue
            if isinstance(key, str) and key.endswith("_envs"):
                assert isinstance(child, list)
                for item in child:
                    assert isinstance(item, str) and item
                    references.add(item)
                continue
            references.update(_environment_references(child))
        return references
    if isinstance(value, list):
        references: set[str] = set()
        for item in value:
            references.update(_environment_references(item))
        return references
    return set()
