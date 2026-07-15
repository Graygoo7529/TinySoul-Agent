"""Package-owned Action catalog resources."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import as_file, files
from pathlib import Path

from .core.errors import ActionInvariantError


@contextmanager
def builtin_action_catalog_root() -> Iterator[Path]:
    """Materialize the versioned built-in catalog for one assembly operation."""

    catalog = files("tinysoul.action").joinpath("catalog")
    if not catalog.is_dir():
        raise ActionInvariantError("Built-in Action catalog package resource is missing")
    with as_file(catalog) as root:
        yield root
