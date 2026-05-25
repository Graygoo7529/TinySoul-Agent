"""Smoke tests for static action schema definitions."""

from tinysoul.action.framework.schema import get_action_schema


class TestGetActionSchema:
    def test_returns_object_schema_with_required_name(self):
        schema = get_action_schema()
        assert schema["type"] == "object"
        assert "name" in schema["required"]
        assert "properties" in schema
