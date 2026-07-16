from __future__ import annotations

from pathlib import Path
import tomllib

import pytest

from tinysoul.app import AppContractError, ProjectInitializer
from tinysoul.app import cli


def test_cli_init_copies_editable_project_without_provider_selection(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agent"

    result = cli.main(["init", str(root)])

    assert result == 0
    assert (root / "tinysoul.toml").is_file()
    assert (root / "configs" / "home.toml").is_file()
    assert not (root / "configs" / "action.toml").exists()
    assert not (root / "tinysoul" / "action" / "catalog").exists()
    assert (root / ".env.example").is_file()
    assert (root / "memory").is_dir()
    skill = root / "home" / "how" / "tinysoul-docs" / "SKILL.md"
    assert skill.read_text(encoding="utf-8").startswith("---\ntitle:")
    assert (root / "home" / "agent" / "user" / "user.md").is_file()
    assert (root / "home" / "what" / "entity" / "tiny-soul.md").is_file()
    assert (
        root
        / "home"
        / "how"
        / "tinysoul-docs"
        / "references"
        / "use-tinysoul-context-and-link.md"
    ).is_file()

    providers = tomllib.loads(
        (root / "configs" / "llm.providers.toml").read_text(encoding="utf-8")
    )["llm"]["providers"]
    assert providers
    assert all(spec["enabled"] is False for spec in providers.values())
    assert providers["kimi"]["api_key_envs"] == ["MOONSHOT_API_KEY"]
    assert providers["kimi_coding"] == {
        "enabled": False,
        "adapter": "kimi",
        "api_style": "openai_chat",
        "base_url": "https://api.kimi.com/coding/v1",
        "api_key_envs": ["KIMI_CODING_API_KEY"],
    }
    models = tomllib.loads(
        (root / "configs" / "llm.models" / "kimi.toml").read_text(
            encoding="utf-8"
        )
    )["llm"]["models"]
    assert models["kimi_k2_7"]["provider_model"] == "kimi-for-coding-highspeed"
    assert models["kimi_k3"]["provider_model"] == "k3"


def test_project_initializer_accepts_empty_directory_and_rejects_nonempty(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    outcome = ProjectInitializer().initialize(empty)

    assert outcome.root == empty.resolve()
    assert outcome.file_count > 10
    marker = tmp_path / "existing" / "marker.txt"
    marker.parent.mkdir()
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(AppContractError, match="must be empty"):
        ProjectInitializer().initialize(marker.parent)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_initialized_project_reports_clear_unconfigured_provider_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "agent"
    assert cli.main(["init", str(root)]) == 0

    result = cli.main(["--root", str(root), "--once", "hello"])

    captured = capsys.readouterr()
    assert result == 1
    assert "Task has no models from enabled providers" in captured.err
