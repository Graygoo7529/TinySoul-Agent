"""Materialize common catalog assets for isolated owner tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory


def builtin_action_catalog_files() -> tuple[tuple[PurePosixPath, Traversable], ...]:
    """Return the single package-owned common catalog used by project init."""
    root = files("tinysoul.assets").joinpath("common", "configs", "action", "catalog")
    if not root.is_dir():
        raise AssertionError("The common Action catalog asset is missing")
    documents: list[tuple[PurePosixPath, Traversable]] = []

    def collect(directory: Traversable, prefix: PurePosixPath) -> None:
        for item in sorted(directory.iterdir(), key=lambda child: child.name):
            path = prefix / item.name
            if item.is_dir():
                collect(item, path)
            elif item.is_file():
                documents.append((path, item))

    collect(root, PurePosixPath())
    if not documents:
        raise AssertionError("The common Action catalog asset is empty")
    return tuple(documents)


@contextmanager
def builtin_action_catalog_root() -> Iterator[Path]:
    """Materialize a test-owned copy without modifying package assets."""
    with TemporaryDirectory(prefix="tinysoul-catalog-") as directory:
        root = Path(directory)
        for relative, resource in builtin_action_catalog_files():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(resource.read_bytes())
        yield root
