from __future__ import annotations

import pytest

from tinysoul.infra.json import JsonObject
from tinysoul.infra.references import ReferenceError, append_locator_fragment


def test_dynamic_locator_fragment_preserves_owner_binding() -> None:
    locator: JsonObject = {
        "ref": "memory:current",
        "day": "2026-09-29",
        "turn_id": "turn-1",
    }
    assert append_locator_fragment(locator, "notes") == {
        "ref": "memory:current#notes",
        "day": "2026-09-29",
        "turn_id": "turn-1",
    }
    assert locator["ref"] == "memory:current"


def test_locator_fragment_requires_an_identity() -> None:
    with pytest.raises(ReferenceError):
        append_locator_fragment({"day": "2026-09-29"}, "notes")
