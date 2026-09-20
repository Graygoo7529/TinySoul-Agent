"""Fixed views over the Session owner's immutable completed records."""

from __future__ import annotations

from dataclasses import dataclass, field

from tinysoul.infra.continuation import (
    ContinuationError,
    ContinuationFailureReason,
    OpaqueContinuationCodec,
)
from tinysoul.infra.json import JsonObject, dumps_json
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.context.disclosure import DisclosureHint, DisclosurePage, query_hint

from .background import (
    SessionBackgroundItem,
    SessionBackgroundSnapshot,
    project_map_entry,
    project_turn_background,
)
from ..config import SessionSettings
from ..errors import (
    SessionContractError,
    SessionInspectFailureReason,
    SessionInspectRequestError,
    SessionInvariantError,
)
from ..records.models import SessionManifest, SessionTurnRecord
from .navigation import (
    action_leaf_ref,
    parse_action_ref,
    project_action,
    project_relations,
    project_occurrence,
    project_navigation_header,
    resource_links,
)
from ..records.store import SessionStore
from ..records.validation import validate_turn_record


@dataclass(frozen=True)
class SessionView:
    """Hold a fixed source set; loading immutable records never refreshes it."""

    manifest: SessionManifest
    settings: SessionSettings = field(repr=False)
    _store: SessionStore = field(repr=False)
    _continuations: OpaqueContinuationCodec = field(
        default_factory=lambda: OpaqueContinuationCodec(
            owner="session", operation="inspect"
        ),
        repr=False,
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.manifest, SessionManifest)
            or not isinstance(self.settings, SessionSettings)
            or not isinstance(self._store, SessionStore)
        ):
            raise SessionContractError("Session view requires typed owner state")

    @property
    def day(self) -> CalendarDay:
        return CalendarDay.parse(self.manifest.day)

    def snapshot_view(self, day: CalendarDay) -> SessionView:
        if day != self.day:
            raise SessionContractError("Session view day does not match its source")
        return self

    def background_snapshot(self, day: CalendarDay) -> SessionBackgroundSnapshot:
        if day != self.day:
            raise SessionContractError("Session view day does not match its source")
        projected = tuple(
            SessionBackgroundItem(item_id=ref, content=self._background_for_ref(ref))
            for ref in self.manifest.refs
        )
        return SessionBackgroundSnapshot(
            revision=self.manifest.revision,
            items=self._fit_background(projected),
            refs=self.manifest.refs,
            max_chars=self.settings.background_max_chars,
        )

    def inspect(
        self,
        ref: str | None = None,
        *,
        action: str | None = None,
        query: str | None = None,
        continuation: str | None = None,
        expected_revision: int | None = None,
    ) -> JsonObject:
        if expected_revision is not None and expected_revision != self.manifest.revision:
            raise SessionContractError("Session view source changed during its Turn")
        ref = ref or "session:map"
        if query is not None and (not isinstance(query, str) or not query.strip()):
            raise _request_error(
                SessionInspectFailureReason.INVALID_QUERY,
                "Query must be non-empty text", ref=ref,
            )
        if action is not None and not ref.endswith("#actions"):
            raise _request_error(
                SessionInspectFailureReason.WRONG_RECORD_KIND,
                "Action filter requires an Action collection", ref=ref,
            )
        page = self._disclose(ref, action=action)
        if query is not None:
            hints = tuple(
                hint for target, title, content in self._search_scope(ref, action=action)
                if (hint := query_hint(target, title, content, query)) is not None
            )
            page = DisclosurePage(ref, "session_query", children=hints)
        try:
            return page.render(
                codec=self._continuations,
                max_chars=self.settings.inspect_max_chars,
                continuation=continuation,
                binding={
                    "day": self.manifest.day,
                    "revision": self.manifest.revision,
                    "query": query,
                    "action": action,
                },
            )
        except ContinuationError as exc:
            reason = (
                SessionInspectFailureReason.PAGE_BUDGET_TOO_SMALL
                if exc.reason is ContinuationFailureReason.BUDGET_TOO_SMALL
                else SessionInspectFailureReason.INVALID_CONTINUATION
            )
            raise _request_error(reason, str(exc), ref=ref) from exc

    def _map_refs(self, ref: str) -> tuple[str, ...]:
        if ref == "session:map":
            return self.manifest.refs
        prefix = "session:map/"
        if ref.startswith(prefix):
            index = ref[len(prefix):]
            if index.isascii() and index.isdigit():
                start = int(index)
                if start % 16 == 0 and start < len(self.manifest.refs):
                    return self.manifest.refs[start:start + 16]
        raise _request_error(
            SessionInspectFailureReason.UNKNOWN_REF,
            "Unknown Session group", ref=ref,
        )

    def _disclose(self, ref: str, *, action: str | None) -> DisclosurePage:
        if ref.startswith("session:map"):
            refs = self._map_refs(ref)
            if ref == "session:map" and len(refs) > 16:
                children = tuple(
                    DisclosureHint(
                        f"session:map/{index}", "Turn group",
                        f"Turns {index + 1}–{min(index + 16, len(refs))}",
                    )
                    for index in range(0, len(refs), 16)
                )
            else:
                children = tuple(self._turn_hint(self._record(item)) for item in refs)
            successors = refs[1:]
            if ref != "session:map" and refs:
                following = self.manifest.refs.index(refs[-1]) + 1
                successors += self.manifest.refs[following:following + 1]
            related: tuple[JsonObject, ...] = tuple(
                {
                    "kind": "relation", "source": left, "target": right,
                    "relation": "precedes", "basis": "fact",
                }
                for left, right in zip(refs, successors)
            ) if len(refs) <= 16 else ()
            return DisclosurePage(ref, "session_map", children=children, related=related)
        turn_ref, _, suffix = ref.partition("#")
        record = self._requested_record(turn_ref)
        if not suffix:
            children = [
                DisclosureHint(
                    f"{turn_ref}#input/{index}",
                    "User reply" if item.reply_to else "User input",
                    item.text[:240],
                )
                for index, item in enumerate(record.inputs)
            ]
            if record.actions:
                children.append(DisclosureHint(
                    f"{turn_ref}#actions", "Actions", str(len(record.actions)),
                ))
            if record.timeline:
                children.append(DisclosureHint(
                    f"{turn_ref}#timeline", "Observed order",
                    "Input visibility, actions and events",
                ))
            children.extend(
                DisclosureHint(
                    f"{turn_ref}#note/{index}", "Event or decision",
                    dumps_json(note)[:240],
                )
                for index, note in enumerate(record.notes)
            )
            if record.output is not None:
                children.append(DisclosureHint(
                    f"{turn_ref}#output", "Answer", record.output.text[:240],
                ))
            if record.working:
                children.append(DisclosureHint(f"{turn_ref}#working", "Final working state"))
            children.extend(
                DisclosureHint(f"{turn_ref}#resource/{index}", link)
                for index, link in enumerate(resource_links(record))
            )
            relations = project_relations(record)
            return DisclosurePage(
                ref, "session_turn",
                content=(project_navigation_header(record),),
                children=tuple(children), related=relations,
            )
        if suffix == "timeline":
            return DisclosurePage(ref, "session_timeline", content=tuple(
                {"kind": item.kind.value, "ref": item.ref} for item in record.timeline
            ))
        parsed = parse_action_ref(ref)
        if parsed is not None and parsed.is_collection:
            return DisclosurePage(ref, "session_actions", children=tuple(
                DisclosureHint(action_leaf_ref(turn_ref, index), item.action, item.outcome.value)
                for index, item in enumerate(record.actions)
                if action is None or item.action == action
            ))
        return DisclosurePage(ref, "session_detail", content=(self._detail(record, ref),))

    def _detail(self, record: SessionTurnRecord, ref: str) -> JsonObject:
        parsed = parse_action_ref(ref)
        if parsed is not None and parsed.occurrence is not None:
            if parsed.occurrence < len(record.actions):
                return project_action(
                    record.ref, parsed.occurrence, record.actions[parsed.occurrence],
                )
        else:
            try:
                return project_occurrence(record, ref.partition("#")[2])
            except SessionContractError:
                pass
        raise _request_error(
            SessionInspectFailureReason.UNKNOWN_REF,
            "Unknown Session fact", ref=ref,
        )

    def _turn_hint(self, record: SessionTurnRecord) -> DisclosureHint:
        return DisclosureHint(
            record.ref, f"{record.day} · {record.status.value}",
            " / ".join(item.text[:120] for item in record.inputs[:2]),
        )

    def _search_scope(
        self, ref: str, *, action: str | None,
    ) -> tuple[tuple[str, str, JsonObject], ...]:
        if ref.startswith("session:map"):
            records = tuple(self._record(item) for item in self._map_refs(ref))
        else:
            records = (self._requested_record(ref.partition("#")[0]),)
        values: list[tuple[str, str, JsonObject]] = []
        for record in records:
            targets = [
                *(f"{record.ref}#input/{i}" for i in range(len(record.inputs))),
                *(f"{record.ref}#note/{i}" for i in range(len(record.notes))),
                *(
                    f"{record.ref}#action/{i}"
                    for i, item in enumerate(record.actions)
                    if item.action != "core.context.inspect"
                    and (action is None or action == item.action)
                ),
                *(f"{record.ref}#resource/{i}" for i in range(len(resource_links(record)))),
                f"{record.ref}#working",
            ]
            if record.output is not None:
                targets.append(f"{record.ref}#output")
            suffix = ref.partition("#")[2]
            if suffix == "actions":
                targets = [item for item in targets if "#action/" in item]
            elif suffix == "timeline":
                timeline_refs = {item.ref for item in record.timeline}
                targets = [item for item in targets if item in timeline_refs]
            elif suffix:
                targets = [ref]
            ordered = dict.fromkeys(item.ref for item in record.timeline)
            targets = [
                *(target for target in ordered if target in targets),
                *(target for target in targets if target not in ordered),
            ]
            for target in targets:
                values.append((target, "Session fact", self._detail(record, target)))
        return tuple(values)

    def _background_for_ref(self, ref: str) -> JsonObject:
        return project_turn_background(self._record(ref))

    def _fit_background(
        self,
        items: tuple[SessionBackgroundItem, ...],
    ) -> tuple[SessionBackgroundItem, ...]:
        def entry(count: int) -> SessionBackgroundItem:
            return SessionBackgroundItem(
                item_id="session_map",
                content=project_map_entry(
                    day=self.manifest.day, total=len(items), projected=count
                ),
            )

        # Reserve enough for every possible count without exposing view revision.
        used = max(len(dumps_json(entry(count).content)) for count in (0, len(items)))
        if used > self.settings.background_max_chars:
            raise SessionInvariantError(
                "Session minimum Map exceeds its configured capacity"
            )
        selected: list[SessionBackgroundItem] = []
        for item in reversed(items):
            size = len(dumps_json(item.content))
            if used + size > self.settings.background_max_chars:
                break
            selected.append(item)
            used += size
        selected.reverse()
        return (entry(len(selected)), *selected)

    def _record(self, ref: str) -> SessionTurnRecord:
        try:
            record = validate_turn_record(self._store.load_record(ref))
            if record.day != self.manifest.day:
                raise SessionInvariantError(
                    "Session view contains another day's record"
                )
            return record
        except SessionContractError as exc:
            raise SessionInvariantError(
                f"Session graph references a missing record: {ref}"
            ) from exc

    def _requested_record(self, ref: str) -> SessionTurnRecord:
        if ref not in self.manifest.refs:
            raise _request_error(
                SessionInspectFailureReason.UNKNOWN_REF,
                "Unknown Session ref",
                ref=ref,
            )
        return self._record(ref)
def _request_error(
    reason: SessionInspectFailureReason,
    message: str,
    *,
    ref: str | None,
) -> SessionInspectRequestError:
    return SessionInspectRequestError(
        reason,
        message,
        constraint=({"ref": ref} if ref is not None else {}),
        scope="session.inspect",
    )
