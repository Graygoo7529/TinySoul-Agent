"""Tests for QueryEvents and QueryEvent."""

from __future__ import annotations

from tinysoul.loop.query import QueryEvents, QueryEventRole, QueryEvent


class TestQueryEvents:
    def test_initializes_with_initial(self):
        h = QueryEvents("hello")
        assert len(h) == 1
        assert h.items[0].role == QueryEventRole.INITIAL
        assert h.items[0].content == "hello"

    def test_empty_when_no_initial(self):
        h = QueryEvents()
        assert len(h) == 0

    def test_append_inquiry(self):
        h = QueryEvents("hello")
        h.append_inquiry("What is your name?", turn=1)
        assert len(h) == 2
        assert h.items[1].role == QueryEventRole.INQUIRY
        assert h.items[1].content == "What is your name?"
        assert h.items[1].turn == 1

    def test_append_response(self):
        h = QueryEvents("hello")
        h.append_inquiry("What is your name?", turn=1)
        h.append_response("Alice", "What is your name?", turn=2)
        assert len(h) == 3
        assert h.items[2].role == QueryEventRole.RESPONSE
        assert h.items[2].ask_context == "What is your name?"

    def test_to_dict_list(self):
        h = QueryEvents("hello")
        h.append_inquiry("Q?", turn=1)
        d = h.to_dict_list()
        assert len(d) == 2
        assert d[0]["role"] == "initial"
        assert d[1]["role"] == "inquiry"


class TestQueryEventSerialization:
    def test_to_dict_includes_ask_context(self):
        item = QueryEvent(
            role=QueryEventRole.RESPONSE,
            content="Alice",
            turn=2,
            ask_context="What is your name?",
        )
        d = item.to_dict()
        assert d["role"] == "response"
        assert d["ask_context"] == "What is your name?"
        assert "turn" in d
