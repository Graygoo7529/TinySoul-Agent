"""
Workspace data model for TinySoul.

Defines Workspace, ResourceItem, and ChangeLogItem structures.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from tinysoul.trap import (
    PathTraversalError,
    ResourceConflictError,
    ResourceNotFoundError,
)


def _default_truncate() -> int:
    from tinysoul.infra.config import settings
    return settings.reference_truncate


def _read_file_utf8(path: str) -> str:
    """Read file content with UTF-8 encoding.

    Raises on permission denied, I/O errors, or other non-encoding issues
    so that callers can distinguish "read failed" from "file is empty".
    """
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class ResourceType(StrEnum):
    MARKDOWN = "MARKDOWN"
    PY = "PY"
    PDF = "PDF"
    DOCX = "DOCX"
    TXT = "TXT"
    JSON = "JSON"
    CSV = "CSV"
    UNKNOWN = "UNKNOWN"


# Text-based resource types that can be read as UTF-8.
TEXT_READABLE_TYPES: set[ResourceType] = {
    ResourceType.MARKDOWN,
    ResourceType.TXT,
    ResourceType.JSON,
    ResourceType.CSV,
    ResourceType.PY,
    ResourceType.UNKNOWN,
}

# Binary types that require external parsers and are not readable as plain text.
BINARY_TYPES: set[ResourceType] = {
    ResourceType.PDF,
    ResourceType.DOCX,
}


class ChangeOperation(StrEnum):
    READ = "READ"
    CREATED = "CREATED"
    EDITED = "EDITED"
    DELETED = "DELETED"


@dataclass
class ResourceDesc:
    summary: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> "ResourceDesc":
        return cls(summary=d.get("summary", ""))


@dataclass
class ChangeLogItem:
    turn: int
    operation: ChangeOperation
    summary: str
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "operation": self.operation.value,
            "summary": self.summary,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


@dataclass
class ResourceItem:
    resource_name: str
    resource_type: ResourceType
    resource_access: str
    resource_desc: ResourceDesc = field(default_factory=ResourceDesc)
    change_log: list[ChangeLogItem] = field(default_factory=list)

    def to_dict(self, compact: bool = False, max_logs: int = 1) -> dict[str, Any]:
        result: dict[str, Any] = {
            "resource_name": self.resource_name,
            "resource_type": self.resource_type.value,
            "resource_access": self.resource_access,
            "resource_desc": self.resource_desc.to_dict(),
        }
        if compact:
            result["change_log"] = [item.to_dict() for item in self.change_log[-max_logs:]]
        else:
            result["change_log"] = [item.to_dict() for item in self.change_log]
        return result


class Workspace:
    """
    External file-system context module for query-loop, independent from State.
    """

    def __init__(
        self,
        workspace_location: str,
        workspace_desc: str | None = None,
        resources: list[ResourceItem] | None = None,
    ):
        self.workspace_location = Path(workspace_location).resolve()
        self.workspace_desc = workspace_desc
        self.resources: list[ResourceItem] = list(resources or [])
        self.change_log: list[ChangeLogItem] = []

    def to_dict(self, compact: bool = False, max_logs: int = 1) -> dict[str, Any]:
        result: dict[str, Any] = {
            "workspace_location": str(self.workspace_location),
            "workspace_desc": self.workspace_desc,
            "resources": [r.to_dict(compact=compact, max_logs=max_logs) for r in self.resources],
        }
        if self.change_log:
            if compact:
                result["change_log"] = [item.to_dict() for item in self.change_log[-max_logs:]]
            else:
                result["change_log"] = [item.to_dict() for item in self.change_log]
        return result

    def find_resource(self, resource_access: str) -> ResourceItem | None:
        for resource in self.resources:
            if resource.resource_access == resource_access:
                return resource
        return None

    def add_resource(self, resource: ResourceItem) -> None:
        if self.find_resource(resource.resource_access) is not None:
            raise ResourceConflictError(
                f"Resource '{resource.resource_access}' already exists in workspace"
            )
        self.resources.append(resource)

    def remove_resource(self, resource_access: str) -> ResourceItem | None:
        for i, resource in enumerate(self.resources):
            if resource.resource_access == resource_access:
                return self.resources.pop(i)
        return None

    def resolve_access(self, resource_access: str) -> Path:
        """
        Resolve a resource_access to an absolute path within workspace boundary.
        Raises PathTraversalError if the resolved path is outside workspace_location.
        """
        if Path(resource_access).is_absolute():
            raise PathTraversalError(
                f"resource_access must be relative, got absolute path: {resource_access}"
            )

        resolved = (self.workspace_location / resource_access).resolve()
        try:
            resolved.relative_to(self.workspace_location)
        except ValueError:
            raise PathTraversalError(
                f"resource_access '{resource_access}' resolves outside workspace boundary"
            )
        return resolved

    def read_reference_files(
        self, reference_accesses: list[str]
    ) -> list[dict[str, str]]:
        """Read contents of referenced resources.

        Any failure (file not found, permission denied, encoding error) raises
        immediately so that the calling action can reject with error via the
        framework's normal exception path (ErrorTrap → FeedbackError).
        """
        refs: list[dict[str, str]] = []
        for access in reference_accesses:
            resolved = self.resolve_access(access)
            if not resolved.exists():
                raise ResourceNotFoundError(f"Reference resource '{access}' not found")
            try:
                content = _read_file_utf8(str(resolved))
            except UnicodeDecodeError as exc:
                raise ResourceNotFoundError(
                    f"Reference resource '{access}' is not a valid UTF-8 text file"
                ) from exc
            refs.append({"target_access": access, "content": content})
        return refs

    def load_reference_data(
        self, reference_accesses: list[str], truncate: int | None = None
    ) -> dict[str, str]:
        """Load referenced files as a truncated {access: content} mapping.

        Returns an empty dict when *reference_accesses* is empty.
        Content is truncated to *truncate* chars (default: settings.reference_truncate).
        """
        if not reference_accesses:
            return {}
        refs = self.read_reference_files(reference_accesses)
        limit = truncate if truncate is not None else _default_truncate()
        return {r["target_access"]: r["content"][:limit] for r in refs}

    def scan(self) -> None:
        """
        Synchronize workspace.resources with actual directory structure.
        Preserves resource_desc and change_log for existing resources.
        Removes stale resources. Adds new resources for newly discovered files.
        """
        existing_map = {r.resource_access: r for r in self.resources}
        new_resources: list[ResourceItem] = []

        if self.workspace_location.exists() and self.workspace_location.is_dir():
            for path in self.workspace_location.rglob("*"):
                if not path.is_file():
                    continue
                relative = path.relative_to(self.workspace_location).as_posix()
                resource_type = self._infer_resource_type(path)
                if relative in existing_map:
                    old = existing_map[relative]
                    new_resources.append(
                        ResourceItem(
                            resource_name=old.resource_name,
                            resource_type=old.resource_type,
                            resource_access=old.resource_access,
                            resource_desc=old.resource_desc,
                            change_log=old.change_log,
                        )
                    )
                else:
                    new_resources.append(
                        ResourceItem(
                            resource_name=path.name,
                            resource_type=resource_type,
                            resource_access=relative,
                        )
                    )

        self.resources = new_resources

    @staticmethod
    def _infer_resource_type(path: Path) -> ResourceType:
        suffix = path.suffix.lower()
        name = path.name
        if name.startswith("temp_") and len(name) > 10:
            if suffix == ".py":
                return ResourceType.PY
        mapping = {
            ".py": ResourceType.PY,
            ".md": ResourceType.MARKDOWN,
            ".pdf": ResourceType.PDF,
            ".docx": ResourceType.DOCX,
            ".txt": ResourceType.TXT,
            ".json": ResourceType.JSON,
            ".csv": ResourceType.CSV,
        }
        return mapping.get(suffix, ResourceType.UNKNOWN)
