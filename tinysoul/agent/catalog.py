"""Compose explicitly installed owners' editable Action catalog fragments."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from .errors import AgentInvariantError


def builtin_action_catalog_files() -> tuple[tuple[PurePosixPath, Traversable], ...]:
    """Merge owner fragments, refusing two owners for the same document."""
    packages = (
        "tinysoul.kernel.action", "tinysoul.plugins.home", "tinysoul.plugins.memory",
        "tinysoul.plugins.workspace", "tinysoul.plugins.capabilities",
    )
    documents: dict[PurePosixPath, Traversable] = {}

    def collect(directory: Traversable, prefix: PurePosixPath) -> None:
        for item in sorted(directory.iterdir(), key=lambda child: child.name):
            path = prefix / item.name
            if item.is_dir():
                collect(item, path)
            elif item.is_file():
                if path in documents:
                    raise AgentInvariantError("Action catalog fragments contain duplicate documents")
                documents[path] = item

    for package in packages:
        root = files(package).joinpath("catalog")
        if not root.is_dir():
            raise AgentInvariantError("An installed owner's Action catalog fragment is missing")
        collect(root, PurePosixPath())
    return tuple(documents.items())


@contextmanager
def builtin_action_catalog_root() -> Iterator[Path]:
    """Materialize the assembled catalog for standalone loading and validation."""
    with TemporaryDirectory(prefix="tinysoul-catalog-") as directory:
        root = Path(directory)
        for relative, resource in builtin_action_catalog_files():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(resource.read_bytes())
        yield root
