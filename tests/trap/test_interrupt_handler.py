"""Tests for InterruptHandler — state mutations triggered by ErrorTrap routing."""

from __future__ import annotations

import pytest

from tinysoul.context.state import QueryState
from tinysoul.loop.context import QueryContext
from tinysoul.loop.query import QueryEventRole
from tinysoul.trap.interrupt_handler import InterruptHandler
from tinysoul.trap.signal import Signal, SignalContext, SignalType
from tinysoul.trap.trap import Disposition, ErrorTrap, TrapResult


class TestInterruptHandlerUserAppend:
    """APPEND signal should append a user message to QueryEvents."""

    def test_user_append_adds_item_to_dialogue(self):
        state = QueryState()
        ctx = QueryContext(
            query_events="initial query",
            loop_target="test target",
            query_state=state,
            query_action=None,
        )
        ctx.current_turn = 3

        handler = InterruptHandler(query_state=state, query_context=ctx)

        signal_context = SignalContext(
            turn=3,
            step="execute_action",
            signal_type=SignalType.USER_APPEND,
            payload={"content": "Additional context from user"},
        )
        trap_result = TrapResult(
            disposition=Disposition.NEXT_STEP,
            loop_error=None,
            action_result=None,
            status="success",
        )

        handler.handle(trap_result, signal_context)

        items = ctx.query_events.items
        assert len(items) == 2  # INITIAL + APPEND
        assert items[0].role == QueryEventRole.INITIAL
        assert items[0].content == "initial query"
        assert items[1].role == QueryEventRole.APPEND
        assert items[1].content == "Additional context from user"
        assert items[1].turn == 3

    def test_user_append_empty_content_ignored(self):
        state = QueryState()
        ctx = QueryContext(
            query_events="initial query",
            loop_target="test target",
            query_state=state,
            query_action=None,
        )

        handler = InterruptHandler(query_state=state, query_context=ctx)

        signal_context = SignalContext(
            turn=1,
            step="execute_action",
            signal_type=SignalType.USER_APPEND,
            payload={"content": ""},
        )
        trap_result = TrapResult(
            disposition=Disposition.NEXT_STEP,
            loop_error=None,
            action_result=None,
            status="success",
        )

        handler.handle(trap_result, signal_context)

        # Empty content should not add an item
        assert len(ctx.query_events.items) == 1


    def test_user_append_no_context_does_not_crash(self):
        state = QueryState()
        handler = InterruptHandler(query_state=state, query_context=None)

        signal_context = SignalContext(
            turn=1,
            step="execute_action",
            signal_type=SignalType.USER_APPEND,
            payload={"content": "orphan message"},
        )
        trap_result = TrapResult(
            disposition=Disposition.NEXT_STEP,
            loop_error=None,
            action_result=None,
            status="success",
        )

        # Should not raise even when query_context is None
        handler.handle(trap_result, signal_context)

    def test_user_append_no_payload_does_not_crash(self):
        state = QueryState()
        ctx = QueryContext(
            query_events="initial query",
            loop_target="test target",
            query_state=state,
            query_action=None,
        )

        handler = InterruptHandler(query_state=state, query_context=ctx)

        signal_context = SignalContext(
            turn=1,
            step="execute_action",
            signal_type=SignalType.USER_APPEND,
            payload={},
        )
        trap_result = TrapResult(
            disposition=Disposition.NEXT_STEP,
            loop_error=None,
            action_result=None,
            status="success",
        )

        handler.handle(trap_result, signal_context)

        assert len(ctx.query_events.items) == 1


class TestInterruptHandlerActionRecord:
    """Action records should preserve signal metadata without mutating results."""

    def test_success_signal_records_action_target_from_payload(self):
        state = QueryState()
        trap = ErrorTrap(query_state=state)

        signal = Signal(
            type=SignalType.ACTION_COMPLETED,
            turn=1,
            step="execute_action",
            action_name="calculate",
            action_input={"expression": "1 + 1"},
            execution_id="exec-1",
            payload={
                "target": "Compute a simple expression",
                "result": {"value": 2},
            },
        )

        trap.route(signal)

        records = state.get_action_record_list()
        assert len(records) == 1
        assert records[0].action_target == "Compute a simple expression"
        assert records[0].action_result == {"value": 2}
