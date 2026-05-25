"""Unit tests for Workspace data model — ResourceItem, ChangeLogItem, ResourceDesc."""

from tinysoul.context.workspace import (
    ChangeLogItem,
    ChangeOperation,
    ResourceDesc,
    ResourceItem,
    ResourceType,
)


class TestResourceDesc:
    def test_to_dict_round_trip(self):
        desc = ResourceDesc(summary="A note")
        d = desc.to_dict()
        assert d == {"summary": "A note"}
        restored = ResourceDesc.from_dict(d)
        assert restored.summary == "A note"


class TestChangeLogItem:
    def test_to_dict(self):
        from datetime import datetime

        item = ChangeLogItem(turn=1, operation=ChangeOperation.CREATED, summary="Created")
        d = item.to_dict()
        assert d["turn"] == 1
        assert d["operation"] == "CREATED"
        assert d["summary"] == "Created"
        assert "timestamp" in d


class TestResourceItem:
    def test_to_dict(self):
        resource = ResourceItem(
            resource_name="notes.md",
            resource_type=ResourceType.MARKDOWN,
            resource_access="notes.md",
            resource_desc=ResourceDesc(summary="A note"),
            change_log=[
                ChangeLogItem(turn=1, operation=ChangeOperation.CREATED, summary="Created")
            ],
        )
        d = resource.to_dict()
        assert d["resource_name"] == "notes.md"
        assert d["resource_type"] == "MARKDOWN"
        assert d["resource_desc"]["summary"] == "A note"
        assert d["change_log"][0]["operation"] == "CREATED"
