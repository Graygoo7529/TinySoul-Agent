from __future__ import annotations

import pytest

from tinysoul.infra.resources import (
    loaded_text_from_inline,
    load_text_from_filesystem,
    load_text_from_package,
)


def test_load_text_from_filesystem(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "prompt.md").write_text("hello", encoding="utf-8")

    loaded = load_text_from_filesystem("prompt", root, "prompt.md")

    assert loaded is not None
    assert loaded.name == "prompt"
    assert loaded.content == "hello"
    assert loaded.source_type == "filesystem"
    assert loaded.resolved_path == root.resolve() / "prompt.md"


def test_load_text_from_filesystem_optional_missing(tmp_path):
    loaded = load_text_from_filesystem(
        "missing",
        tmp_path,
        "missing.md",
        required=False,
    )

    assert loaded is None


def test_load_text_from_filesystem_required_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_text_from_filesystem("missing", tmp_path, "missing.md")


def test_load_text_from_filesystem_rejects_path_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("nope", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes root"):
        load_text_from_filesystem("outside", root, "..\\outside.md")


def test_load_text_from_package():
    loaded = load_text_from_package(
        "query_loop",
        "tinysoul.prompt.loop",
        "markdown/query_loop.system.md",
    )

    assert loaded is not None
    assert loaded.source_type == "package"
    assert "structured query loop" in loaded.content


def test_load_text_from_package_rejects_path_escape():
    with pytest.raises(ValueError, match="escapes package"):
        load_text_from_package(
            "bad",
            "tinysoul.prompt.loop",
            "../query_loop.system.md",
        )


def test_loaded_text_from_inline():
    loaded = loaded_text_from_inline("inline", "content")

    assert loaded.name == "inline"
    assert loaded.content == "content"
    assert loaded.source_type == "inline"
