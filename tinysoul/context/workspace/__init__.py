"""
Workspace module for TinySoul.

Provides external file-system context for the query loop, independent from State.
"""

from .workspace import (
    BINARY_TYPES,
    TEXT_READABLE_TYPES,
    ChangeLogItem,
    ChangeOperation,
    ResourceDesc,
    ResourceItem,
    ResourceType,
    Workspace,
)

__all__ = [
    "Workspace",
    "ResourceItem",
    "ResourceDesc",
    "ResourceType",
    "ChangeLogItem",
    "ChangeOperation",
    "TEXT_READABLE_TYPES",
    "BINARY_TYPES",
]
