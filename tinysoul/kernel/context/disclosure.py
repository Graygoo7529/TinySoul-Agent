"""Bounded navigation shared by Trace and Session, without owning their facts."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from tinysoul.infra.json import JsonObject, JsonValue, dumps_json, to_json_object
from tinysoul.kernel.interaction import QuestionContent
from tinysoul.kernel.retrieval.disclosure import (
    DisclosureHint,
    DisclosureUnit,
    render_recollection,
)

from .errors import ContextContractError


def fact_unit(
    content: Mapping[str, JsonValue], ref: str, title: str = ""
) -> DisclosureUnit:
    """Project Context-owned input, Trace and Action facts before pagination."""
    title = title or str(
        content.get("role") or content.get("action") or content.get("kind") or "Context"
    )
    narrative = content.get("narrative")
    result = content.get("result", {})
    payload = result.get("payload", result) if isinstance(result, dict) else {}
    payload = payload if isinstance(payload, dict) else {}
    question = (
        QuestionContent.from_json(payload)
        if content.get("action") == "core.ask"
        and isinstance(payload, dict)
        and "question" in payload
        else None
    )
    sections: list[tuple[int, str]] = []
    if question is not None:
        title = question.title
        bodies = []
        offset = 0
        for heading, body in question.narrative_parts():
            sections.append((offset, heading))
            bodies.append(body)
            offset += len(body) + 1
        text = "\n".join(bodies)
    elif isinstance(narrative, str):
        header = "\n".join(
            f"{key}: {dumps_json(content[key])}"
            for key in ("action", "state", "outcome", "request")
            if key in content
        )
        text = f"{header}\n\n{narrative}" if header else narrative
    else:
        parts = []
        for key, value in content.items():
            if key in {
                "ref",
                "kind",
                "role",
                "turn_ref",
                "id",
                "reply_to",
                "answer",
                "source_state",
                "delivery",
            }:
                continue
            if (
                key == "result"
                and isinstance(value, dict)
                and value.get("inspected") is True
            ):
                body = render_recollection(value)
            elif (
                key == "request"
                and isinstance(value, dict)
                and payload.get("inspected") is True
            ):
                body = dumps_json(
                    {
                        name: item
                        for name, item in value.items()
                        if name != "continuation"
                    }
                )
            else:
                body = value if isinstance(value, str) else dumps_json(value)
            parts.append(body if key in {"text", "content"} else f"{key}: {body}")
        text = "\n\n".join(parts)
    return DisclosureUnit(
        str(content.get("ref") or ref),
        str(content.get("title") or title),
        text,
        to_json_object(content),
        sections=tuple(sections),
    )


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


def query_hint(
    ref: str,
    title: str,
    content: JsonObject,
    query: str,
) -> DisclosureHint | None:
    """Deterministic local lookup over owner-supplied semantic content."""
    text = " ".join(fact_unit(content, ref, title).text.split())
    query = " ".join(query.split())
    position = text.casefold().find(query.casefold())
    if position < 0:
        return None
    start = max(0, position - 80)
    return DisclosureHint(ref, title, text[start : position + len(query) + 160])
