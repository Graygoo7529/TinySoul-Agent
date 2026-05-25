"""Unit tests for delete_file action."""

from tinysoul.action.handlers.workspace.delete_file import DeleteFileAction
from tinysoul.context.workspace import Workspace
from tests.helpers.factories import run_config
from tests.helpers.fakes import FakeContextProvider


class TestDeleteFileAction:
    def test_deletes_existing_file(self, tmp_path):
        (tmp_path / "remove.md").write_text("# Remove", encoding="utf-8")
        ws = Workspace(workspace_location=str(tmp_path))
        ws.scan()
        ctx = FakeContextProvider(_workspace=ws)
        handler = DeleteFileAction()
        result = handler.execute(
            {"target_access": "remove.md"},
            ctx,
            run_config("delete_file"),
        )
        assert result["file_existed"] is True
        assert not (tmp_path / "remove.md").exists()
        assert ws.find_resource("remove.md") is None

    def test_missing_file_returns_success(self, tmp_path):
        ws = Workspace(workspace_location=str(tmp_path))
        ctx = FakeContextProvider(_workspace=ws)
        handler = DeleteFileAction()
        result = handler.execute(
            {"target_access": "missing.md"},
            ctx,
            run_config("delete_file"),
        )
        assert result["file_existed"] is False
