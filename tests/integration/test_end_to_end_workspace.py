"""End-to-end integration test: workspace actions with real LLM API."""

from __future__ import annotations

import os

import pytest

from tinysoul.loop.loop import QueryLoop
from tinysoul.context.workspace import Workspace

_RUN_REAL_API_TESTS = os.environ.get("RUN_REAL_API_TESTS", "").lower() in ("1", "true", "yes")


@pytest.mark.skipif(not _RUN_REAL_API_TESTS, reason="Set RUN_REAL_API_TESTS=1")
@pytest.mark.real_api
class TestWorkspaceEndToEnd:
    def test_create_and_read_markdown(self, tmp_path):
        ws = Workspace(
            workspace_location=str(tmp_path),
            workspace_desc="Test workspace for markdown operations",
        )
        ql = QueryLoop(
            initial_query="Create a file called hello.md with a greeting",
            loop_target="Create hello.md in workspace",
            available_action_names=["answer", "reasoning", "scan_workspace", "create_markdown_file", "read_file"],
            workspace=ws,
        )
        result = ql.query_loop(max_turns=5)
        assert result is not None
        assert result.final_state is not None
