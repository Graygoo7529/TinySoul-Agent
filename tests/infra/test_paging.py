from __future__ import annotations

from tinysoul.infra import JsonPageCursor, JsonValue, dumps_json, page_json_sequence


def test_json_sequence_page_never_exceeds_budget_and_reports_coverage() -> None:
    values: tuple[JsonValue, ...] = tuple(
        {"index": index, "text": "value" * 8} for index in range(4)
    )

    page = page_json_sequence(
        values,
        base={"owner": "test"},
        item_field="entries",
        cursor_unit="trace_entry",
        cursor=JsonPageCursor(),
        max_chars=600,
        requested_max_chars=900,
    )

    assert len(dumps_json(page)) <= 600
    assert page["requested_max_chars"] == 900
    assert page["effective_max_chars"] == 600
    coverage = page["entry_coverage"]
    assert isinstance(coverage, list)
    assert len(coverage) == 2
    start, stop = coverage
    assert isinstance(start, int) and isinstance(stop, int)
    assert page["returned_entry_indexes"] == list(range(start, stop))
    assert page["remaining_entry_count"] == 4 - stop
    assert page["page_complete"] is (page["next_cursor"] is None)


def test_oversized_unicode_entry_uses_digest_bound_server_cursor() -> None:
    values: tuple[JsonValue, ...] = ({"text": "事实" * 400}, {"text": "tail"})
    cursor = JsonPageCursor()
    chunks: list[str] = []

    while cursor.entry_index == 0:
        page = page_json_sequence(
            values,
            base={"owner": "test"},
            item_field="entries",
            cursor_unit="trace_entry",
            cursor=cursor,
            max_chars=900,
        )
        assert len(dumps_json(page)) <= 900
        oversized = page["oversized_entry"]
        assert isinstance(oversized, dict)
        text = oversized["text"]
        assert isinstance(text, str)
        chunks.append(text)
        next_cursor = page["next_cursor"]
        assert isinstance(next_cursor, dict)
        cursor = JsonPageCursor.from_json(next_cursor)

    assert "".join(chunks) == dumps_json(values[0])
    assert cursor == JsonPageCursor(entry_index=1)
