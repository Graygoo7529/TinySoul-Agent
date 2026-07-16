from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.infra import StagingDirectoryManager, StagingError


def test_staging_prepare_removes_previous_process_children(local_tmp: Path) -> None:
    stale_root = local_tmp / "runtime" / ".staging"
    stale_file = stale_root / "stale.txt"
    stale_directory = stale_root / "web-old"
    stale_directory.mkdir(parents=True)
    stale_file.write_text("stale", encoding="utf-8")
    (stale_directory / "source.html").write_text("stale", encoding="utf-8")
    manager = StagingDirectoryManager(local_tmp.resolve())

    manager.prepare()

    assert manager.root == stale_root.resolve()
    assert manager.root.is_dir()
    assert tuple(manager.root.iterdir()) == ()


def test_staging_allocate_uses_unique_children_and_cleans_scope(
    local_tmp: Path,
) -> None:
    manager = StagingDirectoryManager(local_tmp.resolve())
    manager.prepare()

    with manager.allocate("web") as first:
        assert first.parent == manager.root
        (first / "document.md").write_text("content", encoding="utf-8")
        with manager.allocate("web") as second:
            assert second.parent == manager.root
            assert second != first
        assert not second.exists()
        assert first.is_dir()

    assert not first.exists()
    assert tuple(manager.root.iterdir()) == ()


def test_staging_rejects_unstable_prefix(local_tmp: Path) -> None:
    manager = StagingDirectoryManager(local_tmp.resolve())
    manager.prepare()

    with pytest.raises(StagingError, match="prefix"):
        with manager.allocate("../escape"):
            pass
