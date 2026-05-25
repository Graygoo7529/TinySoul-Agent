"""Unit tests for OneStepAIExecutor — prompt building and result application."""

from __future__ import annotations

import pytest

from tinysoul.action.executors.llm.one_step import OneStepAIExecutor
from tinysoul.trap import ActionExecutionError
from tinysoul.llm.tasks import InputSpec, LLMPrompt, OutputConstraint
from tests.helpers.factories import run_config
from tests.helpers.fakes import FakeContextProvider, FakeLLMClient


def _stub_build_prompt(builder, params, workspace):
    """Type-compatible stub that never gets called in the guard-path tests below."""
    return LLMPrompt(
        task_guide="",
        context={},
        input_spec=InputSpec(description="", data={}),
        output_constraint=OutputConstraint(description=""),
    )


class TestOneStepAIExecutor:
    def test_template_method_pipeline(self, tmp_path):
        def build_prompt(builder, params, workspace):
            return builder.build(
                task_guide="Write a file",
                input_spec=InputSpec(description="Instruction", data={"instruction": params.get("instruction")}),
                output_constraint=OutputConstraint(description='JSON with {"content": "..."}'),
            )

        def apply_result(params, generated, workspace, context_provider):
            return {"message": f"Created {params.get('target_access')}"}

        executor = OneStepAIExecutor(
            build_prompt=build_prompt,
            apply_result=apply_result,
            client=FakeLLMClient(responses=['{"content": "hello"}']),
        )

        from tinysoul.context.workspace import Workspace
        ws = Workspace(workspace_location=str(tmp_path))
        ctx = FakeContextProvider(_workspace=ws)
        result = executor.execute(
            {"target_access": "test.md", "instruction": "Write hello"},
            context_provider=ctx,
            run_config=run_config("test_llm"),
        )
        assert result == {"message": "Created test.md"}

    def test_requires_workspace(self):
        executor = OneStepAIExecutor(
            build_prompt=_stub_build_prompt,
            apply_result=lambda p, g, w, c: "",
        )
        with pytest.raises(ActionExecutionError, match="workspace"):
            executor.execute({}, None, run_config("test_llm"))

    def test_requires_context_provider(self):
        executor = OneStepAIExecutor(
            build_prompt=_stub_build_prompt,
            apply_result=lambda p, g, w, c: "",
        )
        with pytest.raises(ActionExecutionError, match="workspace"):
            executor.execute({}, context_provider=None, run_config=run_config("test_llm"))

    def test_uses_run_config_llm_timeout(self, tmp_path):
        def build_prompt(builder, params, workspace):
            from tinysoul.llm.tasks import InputSpec, OutputConstraint
            return builder.build(
                task_guide="Write",
                input_spec=InputSpec(description="I", data={}),
                output_constraint=OutputConstraint(description="O"),
            )

        def apply_result(params, generated, workspace, context_provider):
            return {}

        client = FakeLLMClient(responses=['{}'])
        executor = OneStepAIExecutor(
            build_prompt=build_prompt,
            apply_result=apply_result,
            client=client,
        )

        from tinysoul.context.workspace import Workspace
        ws = Workspace(workspace_location=str(tmp_path))
        ctx = FakeContextProvider(_workspace=ws)
        cfg = run_config("test_llm", timeout=120.0, llm_timeout=45.0)
        executor.execute({"x": 1}, context_provider=ctx, run_config=cfg)

        assert client.calls[0]["config"].timeout == 45.0

    def test_llm_timeout_capped_by_action_timeout(self, tmp_path):
        def build_prompt(builder, params, workspace):
            from tinysoul.llm.tasks import InputSpec, OutputConstraint
            return builder.build(
                task_guide="Write",
                input_spec=InputSpec(description="I", data={}),
                output_constraint=OutputConstraint(description="O"),
            )

        def apply_result(params, generated, workspace, context_provider):
            return {}

        client = FakeLLMClient(responses=['{}'])
        executor = OneStepAIExecutor(
            build_prompt=build_prompt,
            apply_result=apply_result,
            client=client,
        )

        from tinysoul.context.workspace import Workspace
        ws = Workspace(workspace_location=str(tmp_path))
        ctx = FakeContextProvider(_workspace=ws)
        # action timeout is smaller than global llm_timeout
        cfg = run_config("test_llm", timeout=10.0, llm_timeout=999.0)
        executor.execute({"x": 1}, context_provider=ctx, run_config=cfg)

        assert 9.0 < client.calls[0]["config"].timeout <= 10.0

    def test_system_stack_includes_loop_context_and_action_context(self, tmp_path):
        def build_prompt(builder, params, workspace):
            from tinysoul.llm.tasks import InputSpec, OutputConstraint
            return builder.build(
                task_guide="Write",
                input_spec=InputSpec(description="I", data={}),
                output_constraint=OutputConstraint(description="O"),
            )

        def apply_result(params, generated, workspace, context_provider):
            return {}

        class ContextWithSystem(FakeContextProvider):
            def get_loop_level_system(self):
                return [
                    {"role": "system", "content": "BASIC SYSTEM"},
                    {"role": "system", "content": "QUERY LOOP SYSTEM"},
                ]

        client = FakeLLMClient(responses=['{}'])
        executor = OneStepAIExecutor(
            build_prompt=build_prompt,
            apply_result=apply_result,
            system_prompt=[{"role": "system", "content": "ACTION SYSTEM"}],
            client=client,
        )

        from tinysoul.context.workspace import Workspace
        ws = Workspace(workspace_location=str(tmp_path))
        ctx = ContextWithSystem(_workspace=ws)
        executor.execute({"x": 1}, context_provider=ctx, run_config=run_config("test_llm"))

        contents = [item["content"] for item in client.calls[0]["system"]]
        assert contents[0] == "BASIC SYSTEM"
        assert contents[1] == "QUERY LOOP SYSTEM"
        assert "ACTION EXECUTION CONTEXT" in contents[2]
        assert contents[3] == "ACTION SYSTEM"
