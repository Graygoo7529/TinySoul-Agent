from __future__ import annotations

import pytest

from tinysoul.infra import (
    ContinuationError,
    ContinuationFailureReason,
    JsonValue,
    OpaqueContinuationCodec,
    continue_json_sequence,
)


def test_continuation_pages_items_without_exposing_position() -> None:
    codec = OpaqueContinuationCodec(owner="test", operation="inspect")
    values: tuple[JsonValue, ...] = tuple(
        {"value": "x" * 250} for _ in range(8)
    )

    first = continue_json_sequence(
        values,
        base={"kind": "test_node", "ref": "test:node"},
        item_field="items",
        continuation=None,
        codec=codec,
        ref="test:node",
        max_chars=1024,
        binding={"generation": 1},
    )

    token = first["next_continuation"]
    assert isinstance(token, str) and token.startswith("v1.")
    assert "cursor" not in first
    second = continue_json_sequence(
        values,
        base={"kind": "test_node", "ref": "test:node"},
        item_field="items",
        continuation=token,
        codec=codec,
        ref="test:node",
        max_chars=1024,
        binding={"generation": 1},
    )
    assert second["items"]


def test_continuation_fragments_one_oversized_canonical_item() -> None:
    codec = OpaqueContinuationCodec(owner="test", operation="inspect")
    first = continue_json_sequence(
        ({"value": "x" * 5000},),
        base={"kind": "large", "ref": "test:large"},
        item_field="content",
        continuation=None,
        codec=codec,
        ref="test:large",
        max_chars=1024,
    )
    assert first["content"] == []
    fragment = first["content_fragment"]
    assert isinstance(fragment, dict)
    assert fragment["encoding"] == "canonical_json"
    assert len(str(first)) <= 1400


def test_continuation_is_bound_to_owner_ref_and_generation() -> None:
    codec = OpaqueContinuationCodec(owner="test", operation="inspect")
    first = continue_json_sequence(
        tuple({"value": index} for index in range(100)),
        base={"kind": "node"},
        item_field="items",
        continuation=None,
        codec=codec,
        ref="test:a",
        max_chars=1024,
        binding={"generation": 1},
    )
    token = first["next_continuation"]
    assert isinstance(token, str)

    with pytest.raises(ContinuationError) as mismatch:
        codec.decode(token, ref="test:b", binding={"generation": 1})
    assert mismatch.value.reason is ContinuationFailureReason.MISMATCH

    with pytest.raises(ContinuationError) as changed:
        codec.decode(token, ref="test:a", binding={"generation": 2})
    assert changed.value.reason is ContinuationFailureReason.MISMATCH


def test_continuation_rejects_tampering() -> None:
    codec = OpaqueContinuationCodec(owner="test", operation="inspect")
    with pytest.raises(ContinuationError) as failure:
        codec.decode("v1.invalid.digest", ref="test:a")
    assert failure.value.reason is ContinuationFailureReason.INVALID


@pytest.mark.parametrize(
    "token",
    (
        "v2.invalid.digest",
        "v1.e30." + "0" * 64,
    ),
)
def test_continuation_decode_wraps_local_parse_failures(token: str) -> None:
    codec = OpaqueContinuationCodec(owner="test", operation="inspect")

    with pytest.raises(ContinuationError) as failure:
        codec.decode(token, ref="test:a")

    assert failure.value.reason is ContinuationFailureReason.INVALID
