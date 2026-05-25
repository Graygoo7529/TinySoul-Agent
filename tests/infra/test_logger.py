"""Unit tests for EventLogger level/category filtering and multi-sink dispatch."""

from __future__ import annotations

import pytest

from tinysoul.infra.logger import (
    CaptureSink,
    ConsoleSink,
    Event,
    EventCategory,
    EventLevel,
    EventLogger,
    NullSink,
)


class TestNullSink:
    def test_discards_all_events(self):
        sink = NullSink()
        sink.emit(Event(EventCategory.LOOP, EventLevel.NORMAL, "test", {}))


class TestCaptureSink:
    def test_records_all_events(self):
        sink = CaptureSink()
        event = Event(EventCategory.LOOP, EventLevel.NORMAL, "loop_ready", {"x": 1})
        sink.emit(event)
        assert len(sink.events) == 1
        assert sink.events[0] is event

    def test_clear_removes_events(self):
        sink = CaptureSink()
        sink.emit(Event(EventCategory.LOOP, EventLevel.NORMAL, "test", {}))
        sink.clear()
        assert len(sink.events) == 0


class TestEventLoggerLevelFiltering:
    def test_quiet_blocks_normal(self):
        sink = CaptureSink()
        logger = EventLogger(level=EventLevel.QUIET, sinks=[sink])
        logger.loop_ready(query="q", target="t", action_count=3)
        assert len(sink.events) == 0

    def test_normal_allows_normal_blocks_verbose(self):
        sink = CaptureSink()
        logger = EventLogger(level=EventLevel.NORMAL, sinks=[sink])
        logger.loop_ready(query="q", target="t", action_count=3)
        assert len(sink.events) == 1
        sink.clear()
        logger.debug_state(state_json="{}", step="s")
        assert len(sink.events) == 0

    def test_debug_allows_all(self):
        sink = CaptureSink()
        logger = EventLogger(level=EventLevel.DEBUG, sinks=[sink])
        logger.loop_ready(query="q", target="t", action_count=3)
        logger.debug_state(state_json="{}", step="s")
        assert len(sink.events) == 2


class TestEventLoggerCategoryFiltering:
    def test_only_matching_categories_are_emitted(self):
        sink = CaptureSink()
        logger = EventLogger(
            level=EventLevel.DEBUG,
            categories={EventCategory.LOOP, EventCategory.ACTION},
            sinks=[sink],
        )
        logger.loop_ready(query="q", target="t", action_count=3)      # LOOP
        logger.action_selected(name="calc", reason="r")                # ACTION
        logger.state_updated(todo="add", milestone="no-change")  # STATE
        assert len(sink.events) == 2
        assert sink.events[0].category == EventCategory.LOOP
        assert sink.events[1].category == EventCategory.ACTION

    def test_empty_categories_blocks_all(self):
        sink = CaptureSink()
        logger = EventLogger(
            level=EventLevel.DEBUG,
            categories=set(),
            sinks=[sink],
        )
        logger.loop_ready(query="q", target="t", action_count=3)
        assert len(sink.events) == 0


class TestEventLoggerMultiSink:
    def test_dispatches_to_all_sinks(self):
        sink_a = CaptureSink()
        sink_b = CaptureSink()
        logger = EventLogger(sinks=[sink_a, sink_b])
        logger.loop_ready(query="q", target="t", action_count=3)
        assert len(sink_a.events) == 1
        assert len(sink_b.events) == 1

    def test_add_sink_at_runtime(self):
        sink_a = CaptureSink()
        logger = EventLogger(sinks=[sink_a])
        logger.loop_ready(query="q", target="t", action_count=3)
        sink_b = CaptureSink()
        logger.add_sink(sink_b)
        logger.loop_ready(query="q", target="t", action_count=3)
        assert len(sink_a.events) == 2
        assert len(sink_b.events) == 1


class TestEventLoggerConvenienceMethods:
    def test_todo_added_emits_correct_event(self):
        sink = CaptureSink()
        logger = EventLogger(sinks=[sink])
        logger.todo_added(key="verify", desc="Verify result")
        assert len(sink.events) == 1
        assert sink.events[0].title == "todo_added"
        assert sink.events[0].data["key"] == "verify"
        assert sink.events[0].data["desc"] == "Verify result"

    def test_step_failed_emits_error_category(self):
        sink = CaptureSink()
        logger = EventLogger(sinks=[sink])
        logger.step_failed(turn=2, step="choose_action", error="bad", disposition="CONTINUE")
        assert sink.events[0].category == EventCategory.ERROR
        assert sink.events[0].level == EventLevel.NORMAL

    def test_debug_prompt_emits_prompt_category_debug_level(self):
        sink = CaptureSink()
        logger = EventLogger(level=EventLevel.DEBUG, sinks=[sink])
        logger.debug_prompt(system=[], user="hello", source="loop_step")
        assert sink.events[0].category == EventCategory.PROMPT
        assert sink.events[0].level == EventLevel.DEBUG

    def test_llm_retry_emits_verbose_level(self):
        sink = CaptureSink()
        logger = EventLogger(level=EventLevel.VERBOSE, sinks=[sink])
        logger.llm_retry(step="chat", model="glm", attempt=1, max_attempts=3)
        assert sink.events[0].category == EventCategory.LLM
        assert sink.events[0].level == EventLevel.VERBOSE

    def test_action_result_prefers_stdout_summary_for_actions(self):
        sink = CaptureSink()
        logger = EventLogger(sinks=[sink])
        logger.action_result(
            {
                "output": {"average": 30.0, "max": 50.0, "min": 10.0},
                "stdout": "column_a avg=30.0\ncolumn_b avg=28.0",
            },
            action_name="analyze_numbers_csv",
        )

        assert sink.events[0].data["summary"] == "column_a avg=30.0\ncolumn_b avg=28.0"
