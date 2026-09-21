"""Two bounded projections of the same Session, under one display budget."""

from __future__ import annotations

from dataclasses import dataclass, replace

from tinysoul.infra.json import JsonObject, dumps_json, to_json_object
from ..errors import SessionContractError, SessionInvariantError


@dataclass(frozen=True)
class SessionBackgroundItem:
    item_id: str
    content: JsonObject

    def __post_init__(self) -> None:
        if not self.item_id:
            raise SessionContractError("Background item requires an identity")
        object.__setattr__(self, "content", to_json_object(self.content))


@dataclass(frozen=True)
class SessionBackgroundSnapshot:
    revision: int
    items: tuple[SessionBackgroundItem, ...] = ()
    refs: tuple[str, ...] = ()
    max_chars: int = 24000
    day: str = ""
    navigation: tuple[JsonObject, ...] = ()
    candidates: tuple[SessionBackgroundItem, ...] = ()
    priority: tuple[str, ...] = ()
    budget_chars: int = 24000

    def __post_init__(self) -> None:
        if type(self.revision) is not int or self.revision < 0 or self.max_chars <= 0:
            raise SessionContractError("Invalid Session projection capacity or source")
        if len(set(self.refs)) != len(self.refs):
            raise SessionContractError("Session projection has repeated history")

    def fit(self, budget: int) -> SessionBackgroundSnapshot:
        """Pure display selection; directories retain all omitted objects."""
        budget = min(budget, self.max_chars)
        head: JsonObject = {
            "kind": "session_map",
            "ref": "session:map",
            "day": self.day,
            "total_turns": len(self.refs),
            "history": "session:history",
            "topics": "session:topics",
            "annotations": "session:annotations",
            "unclassified": "session:unclassified",
        }
        if len(dumps_json(head)) > budget:
            raise SessionInvariantError("Session minimum Map exceeds its capacity")
        details: list[JsonObject] = []
        for item in self.navigation:
            candidate = to_json_object({**head, "navigation": [*details, item]})
            if len(dumps_json(candidate)) > budget // 3:
                item = {
                    key: value
                    for key, value in item.items()
                    if key
                    in {"ref", "kind", "title", "basis", "source", "target", "relation"}
                }
                item["folded"] = True
                candidate = to_json_object({**head, "navigation": [*details, item]})
                if len(dumps_json(candidate)) > budget // 3:
                    continue
            details.append(item)
        if details:
            head["navigation"] = [item for item in details]
        used = len(dumps_json(head))
        by_ref = {item.item_id: item for item in self.candidates}
        selected: dict[str, SessionBackgroundItem] = {}
        for ref in self.priority:
            item = by_ref[ref]
            size = len(dumps_json(item.content))
            if used + size > budget:
                compact = _compact_turn(item.content)
                size = len(dumps_json(compact))
                if used + size > budget:
                    continue
                item = SessionBackgroundItem(ref, compact)
            selected[ref] = item
            used += size
        for ref in self.priority:
            if ref in selected:
                continue
            content: JsonObject = {"kind": "session_turn", "ref": ref, "folded": True}
            interactions = by_ref[ref].content.get("interactions", [])
            if isinstance(interactions, list) and interactions:
                first = interactions[0]
                if isinstance(first, dict) and isinstance(first.get("text"), str):
                    content["clue"] = str(first["text"])[:120]
            item = SessionBackgroundItem(ref, content)
            size = len(dumps_json(item.content))
            if used + size <= budget:
                selected[ref] = item
                used += size
        items = (
            SessionBackgroundItem("session_map", head),
            *(selected[ref] for ref in self.refs if ref in selected),
        )
        return replace(self, items=items, budget_chars=budget)


def _compact_turn(content: JsonObject) -> JsonObject:
    """Keep dialogue units together; never shorten a question's option list."""
    interactions = content.get("interactions")
    if not isinstance(interactions, list):
        return content
    values: list[JsonObject] = []
    for item in interactions:
        if not isinstance(item, dict) or item.get("role") == "agent.action":
            continue
        value = dict(item)
        text = value.get("text")
        if (
            isinstance(text, str)
            and len(text) > 240
            and value.get("role") != "agent.question"
        ):
            value["text"] = text[:240]
            value["excerpted"] = True
        values.append(value)
    return to_json_object({**content, "interactions": values, "folded": True})
