"""Maintenance-owned package resources."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import as_file, files
from pathlib import Path

from .errors import MaintenanceInvariantError


@contextmanager
def maintenance_action_catalog_root() -> Iterator[Path]:
    """Materialize the Maintenance Action Catalog for one assembly operation."""

    catalog = files("tinysoul.maintenance").joinpath("catalog")
    if not catalog.is_dir():
        raise MaintenanceInvariantError(
            "Maintenance Action Catalog package resource is missing"
        )
    with as_file(catalog) as root:
        yield root
