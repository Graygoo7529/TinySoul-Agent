"""Unit tests for ActionRecordManager — peek/ack/read and ongoing tracking."""

from tinysoul.context.state import QueryState


class TestActionRecordManager:
    def test_record_creates_unread_record(self):
        state = QueryState()
        record = state.record_action(
            action_name="calculate",
            action_target="Compute sum",
            action_input={"expr": "1+1"},
            action_result={"value": "2", "expression": "1+1"},
            turn=1,
        )
        assert record.action_name == "calculate"
        assert record.read is False
        assert record.turn == 1

    def test_record_stores_dict_directly(self):
        state = QueryState()
        record = state.record_action(
            action_name="test",
            action_target="Test",
            action_input={"key": "value"},
            action_result={"status": "ok"},
            turn=1,
        )
        assert isinstance(record.action_input, dict)
        assert record.action_input["key"] == "value"

    def test_get_all_returns_copy(self):
        state = QueryState()
        state.record_action("calc", "Compute", {}, {"value": "2", "expression": "1+1"}, turn=1)
        records = state.get_action_record_list()
        records.clear()
        assert len(state.action_record_list) == 1


class TestPeekUnread:
    def test_returns_unread_without_marking(self):
        state = QueryState()
        state.record_action("calc", "Compute", {}, {"value": "2", "expression": "1+1"}, turn=1)
        state.record_action("bash", "List", {}, {"output": "files"}, turn=1)
        unread = state.peek_new_action_records()
        assert len(unread) == 2
        assert all(not r.read for r in state.get_action_record_list())

    def test_returns_empty_when_all_read(self):
        state = QueryState()
        state.record_action("test", "Test", {}, {"status": "ok"}, turn=1)
        state.ack_action_records()
        second = state.peek_new_action_records()
        assert len(second) == 0


class TestAckActionRecords:
    def test_marks_all_unread_as_read(self):
        state = QueryState()
        state.record_action("calc", "Compute", {}, {"value": "2"}, turn=1)
        state.record_action("bash", "List", {}, {"output": "files"}, turn=1)
        state.ack_action_records()
        assert all(r.read for r in state.get_action_record_list())
        assert len(state.peek_new_action_records()) == 0

    def test_idempotent_when_already_read(self):
        state = QueryState()
        state.record_action("test", "Test", {}, {"status": "ok"}, turn=1)
        state.ack_action_records()
        state.ack_action_records()
        assert all(r.read for r in state.get_action_record_list())


class TestOngoingActions:
    def test_add_ongoing_tracks_execution_id(self):
        state = QueryState()
        state.add_ongoing_action("exec-1", "stream", turn=1)
        state.add_ongoing_action("exec-2", "stream", turn=1)
        assert len(state.ongoing_action_list) == 2
        assert state.ongoing_action_list[0]["execution_id"] == "exec-1"
        assert state.ongoing_action_list[1]["execution_id"] == "exec-2"

    def test_add_ongoing_replaces_same_execution_id(self):
        state = QueryState()
        state.add_ongoing_action("exec-1", "stream", turn=1)
        state.add_ongoing_action("exec-1", "stream", turn=2)
        assert len(state.ongoing_action_list) == 1
        assert state.ongoing_action_list[0]["turn"] == 2

    def test_remove_ongoing(self):
        state = QueryState()
        state.add_ongoing_action("exec-1", "stream", turn=1)
        result = state.remove_ongoing_action("exec-1")
        assert result is not None
        assert result.execution_id == "exec-1"
        assert state.ongoing_action_list == []

    def test_remove_nonexistent_returns_none(self):
        state = QueryState()
        assert state.remove_ongoing_action("missing-exec") is None
