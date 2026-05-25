"""Unit tests for scan_workspace action."""

from tinysoul.action.handlers.workspace.scan_workspace import ScanWorkspaceAction
from tinysoul.context.workspace import Workspace
from tests.helpers.factories import run_config
from tests.helpers.fakes import FakeContextProvider


class TestScanWorkspaceAction:
    def test_scans_and_counts_resources(self, tmp_path):
        (tmp_path / "file.md").write_text("# Test", encoding="utf-8")
        ws = Workspace(workspace_location=str(tmp_path))
        ctx = FakeContextProvider(_workspace=ws)
        handler = ScanWorkspaceAction()
        result = handler.execute({}, ctx, run_config("scan_workspace"))
        assert result["resource_count"] == 1

    def test_requires_workspace(self):
        import pytest
        from tinysoul.trap import ActionExecutionError

        handler = ScanWorkspaceAction()
        with pytest.raises(ActionExecutionError, match="workspace"):
            handler.execute({}, None, run_config("scan_workspace"))
