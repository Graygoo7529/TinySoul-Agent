from __future__ import annotations

import asyncio
import tomllib
from pathlib import Path

import pytest

from tinysoul.gateway.presentation import (
    InterfaceSettingsPatch,
    PresentationError,
    PresentationFailure,
    PresentationService,
    ThemeMode,
)
from tinysoul.infra.config import ConfigFileToml


async def test_read_is_pure_and_save_creates_then_merges_current_file(
    tmp_path: Path,
) -> None:
    service = PresentationService(tmp_path)
    initial = await service.configuration("interface")
    assert not initial.exists
    assert not (tmp_path / "presentation").exists()
    await service.save_configuration(
        "interface", InterfaceSettingsPatch(theme=ThemeMode.DARK)
    )
    path = tmp_path / "presentation/configs/interface.toml"
    document = ConfigFileToml(path)
    document.set_value("font_size", 17)
    document.save()
    saved = await service.save_configuration(
        "interface", InterfaceSettingsPatch(reduced_motion=True)
    )
    assert saved.exists
    assert saved.values.theme is ThemeMode.DARK
    assert saved.values.font_size == 17
    assert saved.values.reduced_motion
    assert tomllib.loads(path.read_text(encoding="utf-8")) == saved.values.to_json()
    assert (await PresentationService(tmp_path).configuration("interface")) == saved


async def test_concurrent_field_updates_preserve_each_other(tmp_path: Path) -> None:
    service = PresentationService(tmp_path)
    await asyncio.gather(
        service.save_configuration(
            "interface", InterfaceSettingsPatch(theme=ThemeMode.DARK)
        ),
        service.save_configuration("interface", InterfaceSettingsPatch(font_size=16)),
    )
    result = await service.configuration("interface")
    assert result.values.theme is ThemeMode.DARK
    assert result.values.font_size == 16


@pytest.mark.parametrize(
    "text", ['theme = "unknown"', "font_size = true", "font_size = 30", "broken ["]
)
async def test_invalid_file_is_reported_and_never_overwritten(
    tmp_path: Path, text: str
) -> None:
    path = tmp_path / "presentation/configs/interface.toml"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    service = PresentationService(tmp_path)
    for operation in (
        lambda: service.configuration("interface"),
        lambda: service.save_configuration(
            "interface", InterfaceSettingsPatch(theme=ThemeMode.DARK)
        ),
    ):
        with pytest.raises(PresentationError) as caught:
            await operation()
        assert caught.value.kind is PresentationFailure.INVALID_CONFIG
    assert path.read_text(encoding="utf-8") == text


async def test_save_io_failure_is_local_and_leaves_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = PresentationService(tmp_path)
    original = await service.save_configuration(
        "interface", InterfaceSettingsPatch(font_size=16)
    )

    def fail_save(self: ConfigFileToml) -> None:
        raise PermissionError("private disk path")

    monkeypatch.setattr(ConfigFileToml, "save", fail_save)
    with pytest.raises(PresentationError) as caught:
        await service.save_configuration(
            "interface", InterfaceSettingsPatch(theme=ThemeMode.DARK)
        )
    assert caught.value.kind is PresentationFailure.IO_FAILED
    assert "private" not in str(caught.value)
    assert await service.configuration("interface") == original


async def test_assets_list_read_bound_and_resolve_within_project(
    tmp_path: Path,
) -> None:
    service = PresentationService(tmp_path)
    assert await service.assets() == ()
    path = tmp_path / "presentation/assets/images/sample.png"
    path.parent.mkdir(parents=True)
    data = b"\x89PNG\r\n\x1a\n"
    path.write_bytes(data)
    assets = await service.assets()
    assert [(item.path, item.size) for item in assets] == [
        ("images/sample.png", len(data))
    ]
    content = await service.content(assets[0].path, max_bytes=100)
    assert content.data == data
    assert content.media_type == "image/png"
    with pytest.raises(PresentationError) as caught:
        await service.content(assets[0].path, max_bytes=2)
    assert caught.value.kind is PresentationFailure.TOO_LARGE
    for invalid in (
        "../configs/interface.toml",
        str(path.resolve()),
        "C:secret",
        "images/../../secret",
    ):
        with pytest.raises(PresentationError) as caught:
            await service.content(invalid, max_bytes=100)
        assert caught.value.kind is PresentationFailure.INVALID_PATH


async def test_cancelled_save_joins_before_releasing_write_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    started, release = threading.Event(), threading.Event()
    original_save = ConfigFileToml.save

    def blocked_save(self: ConfigFileToml) -> None:
        started.set()
        assert release.wait(timeout=5)
        original_save(self)

    monkeypatch.setattr(ConfigFileToml, "save", blocked_save)
    service = PresentationService(tmp_path)
    task = asyncio.create_task(
        service.save_configuration(
            "interface", InterfaceSettingsPatch(theme=ThemeMode.DARK)
        )
    )
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await service.configuration("interface")).values.theme is ThemeMode.DARK
