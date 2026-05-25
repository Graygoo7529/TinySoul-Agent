"""Tests for the ask_user action."""

from __future__ import annotations

import pytest

from tinysoul.action.handlers.basic.ask_user import (
    ACTION_JSON_ASK_USER,
    AskUserAction,
    AskUserExecutor,
)
from tinysoul.trap import ActionInputError
from tinysoul.trap.signal import Signal, SignalType
from tinysoul.loop.query import QueryEventRole
from tests.helpers.factories import run_config
from tests.helpers.fakes import FakeContextProvider


class TestAskUserActionMeta:
    def test_meta_parses_correctly(self):
        action = AskUserAction()
        meta = action.get_meta()
        assert meta.name == "ask_user"
        assert meta.profile.action_intention.value == "EXTERNAL_PROBING"
        assert meta.profile.llm_dependency.value == "NONE"


class TestAskUserExecutor:
    def test_appends_agent_ask_and_emits_suspend(self):
        from tinysoul.loop.query import QueryEvents

        history = QueryEvents()
        signals = []

        class Ctx:
            current_turn = 1
            _history = history

            @property
            def query_events(self):
                return self._history

            @property
            def loop_target(self):
                return ""

            @property
            def current_state(self):
                return None

            @property
            def workspace(self):
                return None

            @property
            def query_action(self):
                return None

            @property
            def client(self):
                return None

            def get_framework_system(self):
                return []

            def append_inquiry(self, content):
                return self._history.append_inquiry(content)

            def append_response(self, content, ask_context):
                return self._history.append_response(content, ask_context)

            def get_current_state(self):
                return {}

            def get_workspace(self):
                return {}

            def emit_signal(self, signal):
                signals.append(signal)

        ctx = Ctx()
        executor = AskUserExecutor()
        result = executor.execute(
            {
                "question": "What is your name?",
                "context": "Need to know",
                "options": ["Alice", "Bob"],
                "urgency": "blocking",
            },
            context_provider=ctx,
            run_config=run_config("ask_user"),
        )

        assert result["question"] == "What is your name?"
        assert len(history.items) == 1
        assert history.items[0].role == QueryEventRole.INQUIRY
        assert len(signals) == 1
        assert signals[0].type == SignalType.LOOP_SUSPEND

    def test_raises_when_question_missing(self):
        executor = AskUserExecutor()
        with pytest.raises(ActionInputError):
            executor.execute(
                {"context": "Need to know"},
                context_provider=None,
                run_config=run_config("ask_user"),
            )
