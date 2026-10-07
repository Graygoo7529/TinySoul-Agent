"""Two bounded projections of the same Session, under one display budget."""

from __future__ import annotations

from dataclasses import dataclass, replace

from tinysoul.infra.json import JsonObject, JsonValue, dumps_json, to_json_object
from tinysoul.kernel.interaction import QuestionContent
from tinysoul.kernel.retrieval.disclosure import (
    compact_recollection,
    render_recollection,
)
from tinysoul.prompts.plugins import session as prompt_text

from ..errors import SessionContractError, SessionInvariantError


@dataclass(frozen=True)
class SessionBackgroundItem:
    item_id: str
    content: JsonObject

    def __post_init__(self) -> None:
        if not self.item_id:
            raise SessionContractError("Background item requires an identity")
        object.__setattr__(self, "content", to_json_object(self.content))

    def render(self) -> str:
        return render_background(self.content)


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
        if len(render_background(head)) > budget:
            raise SessionInvariantError("Session minimum Map exceeds its capacity")
        details: list[JsonObject] = []
        for item in self.navigation:
            candidate = to_json_object({**head, "navigation": [*details, item]})
            if len(render_background(candidate)) > budget // 3:
                item = {
                    key: value
                    for key, value in item.items()
                    if key
                    in {"ref", "kind", "title", "basis", "source", "target", "relation"}
                }
                item["folded"] = True
                candidate = to_json_object({**head, "navigation": [*details, item]})
                if len(render_background(candidate)) > budget // 3:
                    continue
            details.append(item)
        if details:
            head["navigation"] = [item for item in details]
        used = len(render_background(head))
        by_ref = {item.item_id: item for item in self.candidates}
        selected: dict[str, SessionBackgroundItem] = {}
        for ref in self.priority:
            item = by_ref[ref]
            size = len(item.render())
            if used + size > budget:
                compact = _compact_turn(item.content)
                size = len(render_background(compact))
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
            size = len(item.render())
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
        if not isinstance(item, dict):
            continue
        value = dict(item)
        text = value.get("text")
        if (
            isinstance(text, str)
            and len(text) > 240
            and value.get("role") not in {"agent.question", "user.reply"}
        ):
            value["text"] = text[:240]
            value["excerpted"] = True
        if value.get("role") in {"agent.action", "agent.reason"}:
            if _is_inspect(value):
                result = value["result"]
                assert isinstance(result, dict)
                value["result"] = compact_recollection(result, max_chars=400)
                request = value.get("request")
                if isinstance(request, dict):
                    value["request"] = {
                        key: body
                        for key, body in request.items()
                        if key != "continuation"
                    }
                values.append(value)
                continue
            for key in ("request", "result"):
                body = _action_fields(
                    value.get(key, {}),
                    omit_continuation=key == "request" and _is_inspect(value),
                )
                if len(body) > 400:
                    value.pop(key, None)
                    value[f"{key}_excerpt"] = body[:400]
                    value["excerpted"] = True
        values.append(value)
    return to_json_object({**content, "interactions": values, "folded": True})


def render_background(content: JsonObject) -> str:
    """Model narrative from owner facts; never a source for persistence."""
    if content.get("kind") == "session_map":
        count = content.get("total_turns", 0)
        lines = [
            prompt_text.map_header(
                day=str(content.get("day", "")),
                count=count if isinstance(count, int) else 0,
            )
        ]
        navigation = content.get("navigation", [])
        if isinstance(navigation, list):
            for item in navigation:
                if isinstance(item, dict):
                    lines.append(
                        " · ".join(
                            str(item[key])
                            for key in (
                                "title",
                                "body",
                                "basis",
                                "relation",
                                "source",
                                "target",
                                "ref",
                            )
                            if item.get(key)
                        )
                    )
                    sources = item.get("source_refs", [])
                    if isinstance(sources, list):
                        lines.append(
                            prompt_text.referenced_content(
                                text="",
                                refs=tuple(
                                    ref for ref in sources if isinstance(ref, str)
                                ),
                            )
                        )
                    relations = item.get("relations", [])
                    if isinstance(relations, list):
                        lines.extend(
                            " · ".join(
                                str(edge[key])
                                for key in (
                                    "relation",
                                    "basis",
                                    "source",
                                    "target",
                                    "ref",
                                )
                                if edge.get(key)
                            )
                            for edge in relations
                            if isinstance(edge, dict)
                        )
        return "\n".join(lines)
    lines = [
        prompt_text.turn_header(
            day=str(content.get("day", "")),
            status=str(content.get("status", "")),
            ref=str(content["ref"]),
        )
    ]
    failures = content.get("failures", [])
    if isinstance(failures, list):
        lines.extend(
            str(failure.get("message", ""))
            for failure in failures
            if isinstance(failure, dict)
        )
    interactions = content.get("interactions", [])
    if not isinstance(interactions, list) or not interactions:
        lines.extend((str(content.get("clue", "")), prompt_text.FOLDED_NOTICE))
    else:
        labels = dict(prompt_text.INTERACTION_LABELS)
        for item in interactions:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", ""))
            if role == "agent.question":
                body = QuestionContent.from_json(item).narrative()
            elif role in {"agent.action", "agent.reason"}:
                body = prompt_text.action_result(
                    action=str(item.get("action", "")),
                    outcome=str(item.get("outcome", "")),
                    request=str(item["request_excerpt"])
                    if "request_excerpt" in item
                    else _action_fields(
                        item.get("request", {}), omit_continuation=_is_inspect(item)
                    ),
                    result=str(item["result_excerpt"])
                    if "result_excerpt" in item
                    else _action_fields(item.get("result", {})),
                )
            else:
                body = str(item.get("narrative", item.get("text", "")))
            failure = item.get("failure")
            if isinstance(failure, dict):
                body += "\n" + str(failure.get("feedback", failure.get("reason", "")))
            refs = item.get("references", [])
            targets: list[str] = []
            if isinstance(refs, list):
                for ref in refs:
                    if isinstance(ref, str):
                        targets.append(ref)
                    elif isinstance(ref, dict):
                        target = ref.get("target_ref", ref.get("ref"))
                        if isinstance(target, str):
                            targets.append(target)
            body = prompt_text.referenced_content(text=body, refs=tuple(targets))
            if item.get("excerpted"):
                body += "\n" + prompt_text.EXCERPT_NOTICE
            lines.append(
                prompt_text.interaction(
                    label=labels.get(role, role),
                    ref=str(item.get("ref", "")),
                    body=body,
                )
            )
    return "\n\n".join(lines)


def _is_inspect(value: JsonObject) -> bool:
    result = value.get("result")
    return isinstance(result, dict) and result.get("inspected") is True


def _action_fields(value: JsonValue, *, omit_continuation: bool = False) -> str:
    """Expose natural-language values directly while retaining named result fields."""
    if not isinstance(value, dict):
        return dumps_json(value)
    if value.get("inspected") is True:
        return render_recollection(value)
    return "\n".join(
        f"{key}:\n{body}" if isinstance(body, str) else f"{key}: {dumps_json(body)}"
        for key, body in value.items()
        if not (omit_continuation and key == "continuation")
    )
