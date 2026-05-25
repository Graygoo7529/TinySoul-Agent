"""Tests for TemporaryScriptExecutor — workspace script loading and sandboxed execution."""

from __future__ import annotations

import pytest

from tinysoul.action.executors.script.temporary import TemporaryScriptExecutor
from tinysoul.trap import ActionExecutionError, ActionTimeoutError
from tests.helpers.factories import run_config
from tests.helpers.fakes import FakeContextProvider


class TestTemporaryScriptExecutor:
    def test_executes_script_from_file(self, tmp_path):
        script = tmp_path / "script.py"
        script.write_text(
            'def _tinysoul_script(action_input, context):\n'
            '    return {"greeting": f"Hello {action_input[\'name\']}!"}\n',
            encoding="utf-8",
        )
        ws = FakeContextProvider._workspace = None
        # Use real workspace via fixture pattern
        from tinysoul.context.workspace import Workspace
        ws = Workspace(workspace_location=str(tmp_path))
        ctx = FakeContextProvider(_workspace=ws)
        executor = TemporaryScriptExecutor("script.py", timeout=5.0)
        result = executor.execute(
            {"name": "World"},
            ctx,
            run_config("script", timeout=5.0),
        )
        assert result["greeting"] == "Hello World!"

    def test_file_not_found(self, tmp_path):
        from tinysoul.context.workspace import Workspace
        ws = Workspace(workspace_location=str(tmp_path))
        ctx = FakeContextProvider(_workspace=ws)
        executor = TemporaryScriptExecutor("missing.py")
        with pytest.raises(ActionExecutionError, match="not found"):
            executor.execute({}, ctx, run_config("script"))

    def test_wraps_non_dict_result(self, tmp_path):
        script = tmp_path / "script.py"
        script.write_text(
            "def _tinysoul_script(action_input, context):\n    return 1\n",
            encoding="utf-8",
        )
        from tinysoul.context.workspace import Workspace
        ws = Workspace(workspace_location=str(tmp_path))
        ctx = FakeContextProvider(_workspace=ws)
        executor = TemporaryScriptExecutor("script.py")
        result = executor.execute({}, ctx, run_config("script"))
        assert result["output"] == 1
        assert "workspace_changes" in result

    def test_wraps_string_result(self, tmp_path):
        script = tmp_path / "script.py"
        script.write_text(
            "def _tinysoul_script(action_input, context):\n    return 'plain text'\n",
            encoding="utf-8",
        )
        from tinysoul.context.workspace import Workspace
        ws = Workspace(workspace_location=str(tmp_path))
        ctx = FakeContextProvider(_workspace=ws)
        executor = TemporaryScriptExecutor("script.py")
        result = executor.execute({}, ctx, run_config("script"))
        assert result["output"] == "plain text"
        assert "workspace_changes" in result

    def test_timeout_stops_script_process(self, tmp_path):
        script = tmp_path / "script.py"
        marker = tmp_path / "marker.txt"
        script.write_text(
            "import time\n"
            "def _tinysoul_script(action_input, context):\n"
            "    time.sleep(1)\n"
            "    with open('marker.txt', 'w') as f:\n"
            "        f.write('late write')\n"
            "    return {'ok': True}\n",
            encoding="utf-8",
        )

        from tinysoul.context.workspace import Workspace

        ws = Workspace(workspace_location=str(tmp_path))
        ctx = FakeContextProvider(_workspace=ws)
        executor = TemporaryScriptExecutor("script.py")

        with pytest.raises(ActionTimeoutError):
            executor.execute({}, ctx, run_config("script", timeout=0.1))

        import time

        time.sleep(1.2)
        assert not marker.exists()
