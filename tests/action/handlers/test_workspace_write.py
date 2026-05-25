"""Unit tests for create_markdown_file and edit_markdown_file actions."""

import pytest

from tinysoul.action.handlers.workspace.create_markdown_file import CreateMarkdownFileAction
from tinysoul.action.handlers.workspace.edit_markdown_file import EditMarkdownFileAction
from tinysoul.trap import ActionExecutionError
from tests.helpers.factories import run_config
from tests.helpers.fakes import FakeContextProvider


class TestCreateMarkdownFileAction:
    def test_requires_workspace(self):
        handler = CreateMarkdownFileAction()
        with pytest.raises(ActionExecutionError, match="workspace"):
            handler.execute(
                {"target_access": "x.md"},
                FakeContextProvider(),
                run_config("create_markdown_file"),
            )


class TestEditMarkdownFileAction:
    def test_requires_workspace(self):
        handler = EditMarkdownFileAction()
        with pytest.raises(ActionExecutionError, match="workspace"):
            handler.execute(
                {"target_access": "x.md"},
                FakeContextProvider(),
                run_config("edit_markdown_file"),
            )
