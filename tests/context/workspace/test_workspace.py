"""Unit tests for Workspace — scanning, resolution, boundary checks."""

from pathlib import Path

import pytest

from tinysoul.trap import PathTraversalError, ResourceConflictError
from tinysoul.context.workspace import (
    ResourceItem,
    ResourceType,
    Workspace,
)


class TestWorkspaceInit:
    def test_init_with_desc(self):
        ws = Workspace(workspace_location="/tmp/test_ws", workspace_desc="test")
        assert str(ws.workspace_location) == str(Path("/tmp/test_ws").resolve())
        assert ws.workspace_desc == "test"
        assert ws.resources == []

    def test_init_without_resources(self):
        ws = Workspace(workspace_location="/tmp/test_ws")
        assert ws.resources == []


class TestWorkspaceResourceOps:
    def test_add_and_find(self):
        ws = Workspace(workspace_location="/tmp/test_ws")
        resource = ResourceItem(
            resource_name="notes.md",
            resource_type=ResourceType.MARKDOWN,
            resource_access="notes.md",
        )
        ws.add_resource(resource)
        found = ws.find_resource("notes.md")
        assert found is not None
        assert found.resource_name == "notes.md"

    def test_add_duplicate_raises(self):
        ws = Workspace(workspace_location="/tmp/test_ws")
        resource = ResourceItem(
            resource_name="notes.md",
            resource_type=ResourceType.MARKDOWN,
            resource_access="notes.md",
        )
        ws.add_resource(resource)
        with pytest.raises(ResourceConflictError):
            ws.add_resource(resource)

    def test_remove_resource(self):
        ws = Workspace(workspace_location="/tmp/test_ws")
        resource = ResourceItem(
            resource_name="notes.md",
            resource_type=ResourceType.MARKDOWN,
            resource_access="notes.md",
        )
        ws.add_resource(resource)
        removed = ws.remove_resource("notes.md")
        assert removed is not None
        assert ws.find_resource("notes.md") is None


class TestWorkspaceResolveAccess:
    def test_valid_relative_path(self):
        ws = Workspace(workspace_location="/tmp/test_ws")
        resolved = ws.resolve_access("docs/file.md")
        assert resolved == Path("/tmp/test_ws/docs/file.md").resolve()

    def test_rejects_absolute_path(self):
        ws = Workspace(workspace_location="/tmp/test_ws")
        with pytest.raises(PathTraversalError):
            ws.resolve_access("/etc/passwd")

    def test_rejects_traversal(self):
        ws = Workspace(workspace_location="/tmp/test_ws")
        with pytest.raises(PathTraversalError):
            ws.resolve_access("../secret.txt")


class TestWorkspaceScan:
    def test_scan_empty_directory(self, tmp_path):
        ws = Workspace(workspace_location=str(tmp_path))
        ws.scan()
        assert ws.resources == []

    def test_scan_discovers_markdown(self, tmp_path):
        (tmp_path / "readme.md").write_text("# Hello", encoding="utf-8")
        ws = Workspace(workspace_location=str(tmp_path))
        ws.scan()
        assert len(ws.resources) == 1
        assert ws.resources[0].resource_type == ResourceType.MARKDOWN
        assert ws.resources[0].resource_access == "readme.md"

    def test_scan_preserves_existing_metadata(self, tmp_path):
        from tinysoul.context.workspace import ChangeLogItem, ChangeOperation, ResourceDesc

        (tmp_path / "readme.md").write_text("# Hello", encoding="utf-8")
        ws = Workspace(workspace_location=str(tmp_path))
        ws.add_resource(
            ResourceItem(
                resource_name="readme.md",
                resource_type=ResourceType.MARKDOWN,
                resource_access="readme.md",
                resource_desc=ResourceDesc(summary="Old summary"),
                change_log=[ChangeLogItem(turn=1, operation=ChangeOperation.READ, summary="Read")],
            )
        )
        ws.scan()
        assert len(ws.resources) == 1
        assert ws.resources[0].resource_desc.summary == "Old summary"
        assert len(ws.resources[0].change_log) == 1

    def test_scan_removes_stale_resources(self, tmp_path):
        (tmp_path / "keep.md").write_text("# Keep", encoding="utf-8")
        ws = Workspace(workspace_location=str(tmp_path))
        ws.add_resource(ResourceItem(resource_name="keep.md", resource_type=ResourceType.MARKDOWN, resource_access="keep.md"))
        ws.add_resource(ResourceItem(resource_name="gone.md", resource_type=ResourceType.MARKDOWN, resource_access="gone.md"))
        ws.scan()
        accesses = [r.resource_access for r in ws.resources]
        assert "keep.md" in accesses
        assert "gone.md" not in accesses

    def test_scan_identifies_temp_py_files(self, tmp_path):
        (tmp_path / "temp_250415_script.py").write_text("print('hello')", encoding="utf-8")
        ws = Workspace(workspace_location=str(tmp_path))
        ws.scan()
        assert len(ws.resources) == 1
        assert ws.resources[0].resource_type == ResourceType.PY


class TestWorkspaceReadReferenceFiles:
    def test_reads_referenced_files(self, tmp_path):
        (tmp_path / "ref.md").write_text("# Reference", encoding="utf-8")
        ws = Workspace(workspace_location=str(tmp_path))
        refs = ws.read_reference_files(["ref.md"])
        assert len(refs) == 1
        assert refs[0]["target_access"] == "ref.md"
        assert refs[0]["content"] == "# Reference"

    def test_raises_for_missing_reference(self, tmp_path):
        ws = Workspace(workspace_location=str(tmp_path))
        from tinysoul.trap import ResourceNotFoundError
        with pytest.raises(ResourceNotFoundError):
            ws.read_reference_files(["missing.md"])

    def test_raises_for_non_utf8_reference(self, tmp_path):
        ws = Workspace(workspace_location=str(tmp_path))
        from tinysoul.trap import ResourceNotFoundError
        # Write binary content (PNG magic bytes) to simulate a non-text file
        (tmp_path / "image.bin").write_bytes(b"\x89PNG\r\n\x1a\n")
        with pytest.raises(ResourceNotFoundError) as exc_info:
            ws.read_reference_files(["image.bin"])
        assert "not a valid UTF-8 text file" in str(exc_info.value)
