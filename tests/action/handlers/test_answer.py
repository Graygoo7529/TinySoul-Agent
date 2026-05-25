"""Tests for the answer action."""

from __future__ import annotations

import json

import pytest

from tinysoul.action.handlers.basic.answer import (
    ACTION_JSON_ANSWER,
    AnswerAction,
    _apply_answer_result,
    _build_answer_prompt,
)
from tinysoul.trap.signal import Signal, SignalType
from tinysoul.llm.tasks import InputSpec, OutputConstraint
from tinysoul.context.workspace import Workspace
from tests.helpers.fakes import FakeContextProvider


class TestAnswerActionMeta:
    def test_meta_parses_correctly(self):
        action = AnswerAction()
        meta = action.get_meta()
        assert meta.name == "answer"
        assert meta.profile.action_intention.value == "INTERNAL_REASONING"
        assert meta.profile.llm_dependency.value == "REQUIRED"

    def test_detail_has_parameter_schema(self):
        action = AnswerAction()
        detail = action.get_detail()
        props = detail.parameter_schema["properties"]
        assert "instruction" in props
        assert "reference_accesses" in props


class TestBuildAnswerPrompt:
    def test_includes_instruction_and_refs(self, tmp_path):
        from tinysoul.llm.tasks.prompt import PromptBuilder

        ws = Workspace(workspace_location=str(tmp_path))
        ctx = FakeContextProvider(_workspace=ws)
        builder = PromptBuilder(ctx)

        params = {
            "instruction": "Summarize findings",
            "reference_accesses": [],
        }
        prompt = _build_answer_prompt(builder, params, ws)
        assert "Summarize findings" in prompt.serialize()


class TestApplyAnswerResult:
    def test_emits_loop_terminate(self, tmp_path):
        ws = Workspace(workspace_location=str(tmp_path))
        signals = []

        class Ctx(FakeContextProvider):
            def emit_signal(self, signal):
                signals.append(signal)

        ctx = Ctx(_workspace=ws)
        generated = {
            "answer_text": "The answer is 42",
            "confidence": "high",
            "references": ["calc"],
        }
        result = _apply_answer_result(
            {"instruction": "Answer"}, generated, ws, ctx
        )

        assert result == {"answer": "The answer is 42", "confidence": "high", "references": ["calc"]}
        assert len(signals) == 1
        assert signals[0].type == SignalType.LOOP_COMPLETE
        # Control flow signals carry NO data; action data travels via ACTION_COMPLETED
        assert signals[0].payload == {}
