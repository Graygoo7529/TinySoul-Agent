"""Bounded navigation shared by Trace and Session, without owning their facts."""

from dataclasses import dataclass
from datetime import date
from hashlib import sha256

from tinysoul.infra.continuation import OpaqueContinuationCodec, continue_json_sequence
from tinysoul.infra.json import JsonObject, dumps_json, to_json_object

from .errors import ContextContractError


@dataclass(frozen=True)
class DisclosureReference:
    target: str
    relation: str = "references"
    source_day: date | None = None


@dataclass(frozen=True)
class DisclosureSearchEntry:
    ref: str
    title: str
    content: JsonObject
    source: str
    basis: str = "fact"
    references: tuple[DisclosureReference, ...] = ()
    day: date | None = None

    def __post_init__(self) -> None:
        if (
            not self.ref
            or self.source not in {"trace", "session"}
            or self.basis not in {"fact", "interpretation"}
        ):
            raise ContextContractError(
                "Search entry requires an owned source identity and basis"
            )


@dataclass(frozen=True)
class DisclosureHint:
    ref: str
    title: str
    clue: str = ""

    def __post_init__(self) -> None:
        if not self.ref or not self.title:
            raise ContextContractError("Disclosure hint requires reference and title")

    def to_json(self) -> JsonObject:
        return {"ref": self.ref, "title": self.title, "clue": self.clue}


@dataclass(frozen=True)
class DisclosurePage:
    """Owner-selected direct content; pagination never expands child bodies."""

    ref: str
    kind: str
    content: tuple[JsonObject, ...] = ()
    children: tuple[DisclosureHint, ...] = ()
    related: tuple[JsonObject, ...] = ()
    sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.ref or not self.kind:
            raise ContextContractError("Disclosure page requires reference and kind")

    def render(
        self,
        *,
        codec: OpaqueContinuationCodec,
        max_chars: int,
        continuation: str | None = None,
        binding: JsonObject | None = None,
    ) -> JsonObject:
        items = (
            *self.content,
            *(
                to_json_object({"kind": "child", **item.to_json()})
                for item in self.children
            ),
            *self.related,
            *({"kind": "source", "ref": ref} for ref in self.sources),
        )
        return continue_json_sequence(
            tuple(to_json_object(item) for item in items),
            base={"kind": self.kind, "ref": self.ref},
            item_field="items",
            codec=codec,
            ref=self.ref,
            continuation=continuation,
            binding={
                **(binding or {}),
                "view": sha256(
                    dumps_json(to_json_object({"items": items})).encode("utf-8")
                ).hexdigest(),
            },
            max_chars=max_chars,
        )


def query_hint(
    ref: str,
    title: str,
    content: JsonObject,
    query: str,
) -> DisclosureHint | None:
    """Deterministic local lookup over owner-supplied semantic content."""
    text = " ".join(
        dumps_json(
            {
                key: value
                for key, value in content.items()
                if key not in {"ref", "kind", "turn_ref"}
            }
        ).split()
    )
    query = " ".join(query.split())
    position = text.casefold().find(query.casefold())
    if position < 0:
        return None
    start = max(0, position - 80)
    return DisclosureHint(ref, title, text[start : position + len(query) + 160])
