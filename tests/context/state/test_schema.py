"""Smoke tests for static query state schema definitions."""

from tinysoul.context.state.schema import get_query_state_schema


class TestGetQueryStateSchema:
    def test_returns_object_schema_with_required_fields(self):
        schema = get_query_state_schema()
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "action_record_list" in schema["properties"]
        assert "todo_list" in schema["properties"]
        assert "new_action_records" not in schema["properties"]
