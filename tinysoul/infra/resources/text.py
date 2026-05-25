"""Generic text and markdown resource loading.

This module deliberately has no prompt-specific semantics. It loads text from
filesystem roots, package resources, or inline content and returns a uniform
resource object for higher layers to interpret.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Literal


TextSourceType = Literal["filesystem", "package", "inline"]


@dataclass(frozen=True)
class LoadedTextResource:
    """A loaded text resource with basic source metadata."""

    name: str
    content: str
    source_type: TextSourceType
    root: Path | None = None
    relative_path: str | None = None
    resolved_path: Path | None = None


def _ensure_within_root(root: Path, target: Path) -> None:
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Resource path escapes root: {target}") from exc


def load_text_from_filesystem(
    name: str,
    root: str | Path,
    relative_path: str,
    *,
    required: bool = True,
    encoding: str = "utf-8",
) -> LoadedTextResource | None:
    """Load a text resource from ``root / relative_path``.

    The resolved path must remain inside ``root``. Missing optional resources
    return ``None``.
    """

    root_path = Path(root).resolve()
    target = (root_path / relative_path).resolve()
    _ensure_within_root(root_path, target)

    if not target.exists():
        if required:
            raise FileNotFoundError(f"Required text resource not found: {target}")
        return None
    if not target.is_file():
        raise IsADirectoryError(f"Text resource is not a file: {target}")

    return LoadedTextResource(
        name=name,
        content=target.read_text(encoding=encoding),
        source_type="filesystem",
        root=root_path,
        relative_path=relative_path,
        resolved_path=target,
    )


def load_text_from_package(
    name: str,
    package: str,
    resource: str,
    *,
    required: bool = True,
    encoding: str = "utf-8",
) -> LoadedTextResource | None:
    """Load a package data text resource with ``importlib.resources``."""

    try:
        path = resources.files(package)
        for part in Path(resource).parts:
            if part in ("", "."):
                continue
            if part == "..":
                raise ValueError(f"Package resource path escapes package: {resource}")
            path = path.joinpath(part)
        if not path.is_file():
            if required:
                raise FileNotFoundError(
                    f"Required package text resource not found: {package}:{resource}"
                )
            return None
        return LoadedTextResource(
            name=name,
            content=path.read_text(encoding=encoding),
            source_type="package",
            relative_path=resource,
        )
    except ModuleNotFoundError:
        if required:
            raise
        return None


def loaded_text_from_inline(name: str, content: str) -> LoadedTextResource:
    """Wrap inline text as a loaded resource."""

    return LoadedTextResource(
        name=name,
        content=content,
        source_type="inline",
    )
