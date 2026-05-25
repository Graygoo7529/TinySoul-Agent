"""Generic text resource loading utilities."""

from .text import (
    LoadedTextResource,
    loaded_text_from_inline,
    load_text_from_filesystem,
    load_text_from_package,
)

__all__ = [
    "LoadedTextResource",
    "loaded_text_from_inline",
    "load_text_from_filesystem",
    "load_text_from_package",
]
