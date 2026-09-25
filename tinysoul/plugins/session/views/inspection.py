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
from tinysoul.kernel.context.disclosure import (
    DisclosureHint,
    DisclosurePage,
    query_hint,
    DisclosureSearchEntry,
    DisclosureReference,
)

from .background import (
    SessionBackgroundItem,
    SessionBackgroundSnapshot,
)
from .interaction import project_interactions, interaction_header
from ..annotations.models import (
    SessionMap,
    SemanticNode,
    AnnotationKind,
    AnnotationStatus,
    SemanticRelation,
    OrganizeRequestError,
    OrganizeFailureReason,
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
    SessionEvidence,
    annotation_content,
    annotation_relations,
    annotation_navigation,
    action_leaf_ref,
    parse_action_ref,
    project_action,
    project_relations,
    project_occurrence,
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
    annotations: SessionMap = field(default_factory=SessionMap)
    evidence: SessionEvidence | None = field(default=None, repr=False)
    _records: dict[str, SessionTurnRecord] = field(
        default_factory=dict, repr=False, compare=False
    )
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
            SessionBackgroundItem(
                ref,
                {
                    **interaction_header(record),
                    "interactions": [
                        item.to_json() for item in project_interactions(record)
                    ],
                },
            )
            for ref in self.manifest.refs
            for record in (self._record(ref),)
        )
        active = tuple(
            item
            for item in self.annotations.nodes
            if item.status is AnnotationStatus.ACTIVE
        )
        positions = {ref: index for index, ref in enumerate(self.manifest.refs)}
        active = tuple(
            sorted(
                active,
                key=lambda item: max(
                    (
                        positions.get(ref.partition("#")[0], -1)
                        for ref in item.source_refs
                    ),
                    default=-1,
                ),
                reverse=True,
            )
        )
        navigation = tuple(
            annotation_navigation(self.annotations, item) for item in active
        )
        # Fact-to-fact interpretations have no owning topic; keep them discoverable too.
        navigation += tuple(
            annotation_content(edge)
            for edge in self.annotations.edges
            if edge.status is AnnotationStatus.ACTIVE
            and edge.source.startswith("session:turn/")
            and edge.target.startswith("session:turn/")
        )
        referenced = {
            ref.partition("#")[0] for item in active for ref in item.source_refs
        }
        referenced.update(
            edge.target.partition("#")[0]
            for edge in self.annotations.edges
            if edge.status is AnnotationStatus.ACTIVE
        )
        recent = tuple(reversed(self.manifest.refs[-3:]))
        priority = tuple(
            dict.fromkeys(
                (
                    *recent,
                    *(ref for ref in reversed(self.manifest.refs) if ref in referenced),
                    *reversed(self._unclassified()),
                    *reversed(self.manifest.refs),
                )
            )
        )
        return SessionBackgroundSnapshot(
            revision=self.manifest.revision,
            refs=self.manifest.refs,
            max_chars=self.settings.background_max_chars,
            day=self.manifest.day,
            navigation=navigation,
            candidates=projected,
            priority=priority,
        ).fit(self.settings.background_max_chars)

    def fact_ref(self, ref: str, allow_current: bool) -> str:
        if allow_current and self.evidence is not None:
            resolved = self.evidence.resolve(ref)
            if resolved is not None:
                return resolved[0]
        root, _, suffix = ref.partition("#")
        if root in self.manifest.refs:
            if not suffix:
                return root
            # Collections and derived timeline nodes are navigation, not evidence.
            if suffix not in {"actions", "timeline"}:
                try:
                    self._detail(self._record(root), ref)
                    return ref
                except SessionInspectRequestError:
                    pass
        raise OrganizeRequestError(
            OrganizeFailureReason.INVALID_SOURCE,
            "Reference must identify an available history fact or accepted current evidence",
        )

    def search_entries(
        self, seed_refs: tuple[str, ...] = ()
    ) -> tuple[DisclosureSearchEntry, ...]:
        values = tuple(
            {
                ref: (title, content)
                for seed in (seed_refs or ("session:map",))
                for ref, title, content in self._search_scope(seed, action=None)
            }.items()
        )
        result = []
        for ref, (title, content) in values:
            annotation = self.annotations.get(ref)
            refs = []
            if annotation is not None:
                refs.extend(
                    DisclosureReference(source, "source_evidence", self.day.value)
                    for source in annotation.source_refs
                )
            elif ref.partition("#")[0] in self.manifest.refs:
                record = self._record(ref.partition("#")[0])
                action_ref = parse_action_ref(ref)
                if action_ref is not None and action_ref.occurrence is not None:
                    refs.extend(
                        DisclosureReference(target, source_day=self.day.value)
                        for target in record.actions[action_ref.occurrence].references
                    )
                elif ref.endswith("#output") and record.output is not None:
                    refs.extend(
                        DisclosureReference(target, source_day=self.day.value)
                        for target in record.output.references
                    )
                elif "#resource/" in ref and isinstance(content.get("link"), str):
                    refs.append(
                        DisclosureReference(
                            str(content["link"]), source_day=self.day.value
                        )
                    )
            result.append(
                DisclosureSearchEntry(
                    ref,
                    title,
                    content,
                    "session",
                    "interpretation" if annotation else "fact",
                    tuple(refs),
                    self.day.value,
                )
            )
        return tuple(result)

    def inspect(
        self,
        ref: str | None = None,
        *,
        action: str | None = None,
        query: str | None = None,
        continuation: str | None = None,
        expected_revision: int | None = None,
    ) -> JsonObject:
        if (
            expected_revision is not None
            and expected_revision != self.manifest.revision
        ):
            raise SessionContractError("Session view source changed during its Turn")
        ref = ref or "session:map"
        if query is not None and (not isinstance(query, str) or not query.strip()):
            raise _request_error(
                SessionInspectFailureReason.INVALID_QUERY,
                "Query must be non-empty text",
                ref=ref,
            )
        if action is not None and not ref.endswith("#actions"):
            raise _request_error(
                SessionInspectFailureReason.WRONG_RECORD_KIND,
                "Action filter requires an Action collection",
                ref=ref,
            )
        page = self._disclose(ref, action=action)
        if query is not None:
            hints = tuple(
                hint
                for target, title, content in self._search_scope(ref, action=action)
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
        if ref in {"session:map", "session:history"}:
            return self.manifest.refs
        if ref == "session:unclassified":
            return self._unclassified()
        prefix = "session:history/"
        if ref.startswith(prefix):
            index = ref[len(prefix) :]
            if index.isascii() and index.isdigit():
                start = int(index)
                if start % 16 == 0 and start < len(self.manifest.refs):
                    return self.manifest.refs[start : start + 16]
        raise _request_error(
            SessionInspectFailureReason.UNKNOWN_REF,
            "Unknown Session group",
            ref=ref,
        )

    def _disclose(self, ref: str, *, action: str | None) -> DisclosurePage:
        if ref == "session:map":
            return DisclosurePage(
                ref,
                "session_map",
                children=(
                    DisclosureHint(
                        "session:topics",
                        "Topics",
                        "Semantic branches and their history references",
                    ),
                    DisclosureHint(
                        "session:annotations",
                        "All annotations",
                        "Including retracted explanations and relations",
                    ),
                    DisclosureHint("session:unclassified", "Unclassified Turns"),
                    DisclosureHint(
                        "session:history", "All history", str(len(self.manifest.refs))
                    ),
                ),
            )
        if ref in {"session:topics", "session:annotations"} or ref.startswith(
            ("session:node/", "session:edge/")
        ):
            return self._annotation_page(ref)
        if ref.startswith("session:history") or ref == "session:unclassified":
            refs = self._map_refs(ref)
            if ref == "session:history" and len(refs) > 16:
                children = tuple(
                    DisclosureHint(
                        f"session:history/{index}",
                        "Turn group",
                        f"Turns {index + 1}–{min(index + 16, len(refs))}",
                    )
                    for index in range(0, len(refs), 16)
                )
            else:
                children = tuple(self._turn_hint(self._record(item)) for item in refs)
            successors = refs[1:]
            if ref.startswith("session:history/") and refs:
                following = self.manifest.refs.index(refs[-1]) + 1
                successors += self.manifest.refs[following : following + 1]
            related: tuple[JsonObject, ...] = (
                tuple(
                    {
                        "kind": "relation",
                        "source": left,
                        "target": right,
                        "relation": "precedes",
                        "basis": "fact",
                    }
                    for left, right in zip(refs, successors)
                )
                if len(refs) <= 16
                else ()
            )
            return DisclosurePage(
                ref, "session_map", children=children, related=related
            )
        if self.evidence is not None:
            resolved = self.evidence.resolve(ref)
            if resolved is not None and ref in self._source_refs():
                return DisclosurePage(ref, "session_evidence", content=(resolved[1],))
        turn_ref, _, suffix = ref.partition("#")
        if turn_ref not in self.manifest.refs and ref in self._source_refs():
            return DisclosurePage(
                ref,
                "session_evidence",
                content=(
                    {
                        "ref": ref,
                        "source_state": "unavailable",
                        "message": "This source has no available completed record in this view",
                    },
                ),
            )
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
                children.append(
                    DisclosureHint(
                        f"{turn_ref}#actions",
                        "Actions",
                        str(len(record.actions)),
                    )
                )
            if record.timeline:
                children.append(
                    DisclosureHint(
                        f"{turn_ref}#timeline",
                        "Observed order",
                        "Input visibility, actions and events",
                    )
                )
            children.extend(
                DisclosureHint(
                    f"{turn_ref}#note/{index}",
                    "Event or decision",
                    dumps_json(note)[:240],
                )
                for index, note in enumerate(record.notes)
            )
            if record.output is not None:
                children.append(
                    DisclosureHint(
                        f"{turn_ref}#output",
                        "Answer",
                        record.output.text[:240],
                    )
                )
            if record.working:
                children.append(
                    DisclosureHint(f"{turn_ref}#working", "Final working state")
                )
            children.extend(
                DisclosureHint(f"{turn_ref}#resource/{index}", link)
                for index, link in enumerate(resource_links(record))
            )
            relations = project_relations(record)
            return DisclosurePage(
                ref,
                "session_turn",
                content=(
                    interaction_header(record),
                    *(item.to_json() for item in project_interactions(record)),
                ),
                children=tuple(children),
                related=relations,
            )
        if suffix == "timeline":
            return DisclosurePage(
                ref,
                "session_timeline",
                content=tuple(
                    {"kind": item.kind.value, "ref": item.ref}
                    for item in record.timeline
                ),
            )
        parsed = parse_action_ref(ref)
        if parsed is not None and parsed.is_collection:
            return DisclosurePage(
                ref,
                "session_actions",
                children=tuple(
                    DisclosureHint(
                        action_leaf_ref(turn_ref, index),
                        item.action,
                        item.outcome.value,
                    )
                    for index, item in enumerate(record.actions)
                    if action is None or item.action == action
                ),
            )
        return DisclosurePage(
            ref, "session_detail", content=(self._detail(record, ref),)
        )

    def _detail(self, record: SessionTurnRecord, ref: str) -> JsonObject:
        parsed = parse_action_ref(ref)
        if parsed is not None and parsed.occurrence is not None:
            if parsed.occurrence < len(record.actions):
                return project_action(
                    record.ref,
                    parsed.occurrence,
                    record.actions[parsed.occurrence],
                )
        else:
            try:
                return project_occurrence(record, ref.partition("#")[2])
            except SessionContractError:
                pass
        raise _request_error(
            SessionInspectFailureReason.UNKNOWN_REF,
            "Unknown Session fact",
            ref=ref,
        )

    def _turn_hint(self, record: SessionTurnRecord) -> DisclosureHint:
        return DisclosureHint(
            record.ref,
            f"{record.day} · {record.status.value}",
            " / ".join(item.text[:120] for item in record.inputs[:2]),
        )

    def _search_scope(
        self,
        ref: str,
        *,
        action: str | None,
    ) -> tuple[tuple[str, str, JsonObject], ...]:
        if (
            ref in self._source_refs()
            and ref.partition("#")[0] not in self.manifest.refs
        ):
            return self._source_fact_scope(ref)
        if ref in {"session:topics", "session:annotations"} or ref.startswith(
            ("session:node/", "session:edge/")
        ):
            page = self._annotation_page(ref)
            values = [(ref, "Session interpretation", item) for item in page.content]
            if ref in {"session:topics", "session:annotations"}:
                for hint in page.children:
                    item = self.annotations.get(hint.ref)
                    if item is not None:
                        values.append(
                            (
                                item.ref,
                                "Session interpretation",
                                annotation_content(item),
                            )
                        )
            for source in page.sources:
                values.extend(self._source_fact_scope(source))
            # A Turn and one of its leaves may both be declared as sources.
            return tuple({item[0]: item for item in values}.values())
        if ref.startswith("session:history") or ref in {
            "session:map",
            "session:unclassified",
        }:
            records = tuple(self._record(item) for item in self._map_refs(ref))
        else:
            records = (self._requested_record(ref.partition("#")[0]),)
        values: list[tuple[str, str, JsonObject]] = []
        suffix = ref.partition("#")[2]
        for record in records:
            values.extend(self._record_fact_scope(record, suffix=suffix, action=action))
        if ref == "session:map":
            for item in (*self.annotations.nodes, *self.annotations.edges):
                values.append(
                    (item.ref, "Session interpretation", annotation_content(item))
                )
        return tuple(values)

    def _source_fact_scope(
        self,
        ref: str,
    ) -> tuple[tuple[str, str, JsonObject], ...]:
        """Search a declared source without widening its factual boundary."""
        root, _, suffix = ref.partition("#")
        if root in self.manifest.refs:
            return self._record_fact_scope(
                self._record(root), suffix=suffix, action=None
            )
        detail = self._disclose(ref, action=None)
        return tuple((ref, "Session evidence", item) for item in detail.content)

    def _record_fact_scope(
        self,
        record: SessionTurnRecord,
        *,
        suffix: str,
        action: str | None,
    ) -> tuple[tuple[str, str, JsonObject], ...]:
        """Return the deterministic factual scope for one Turn or leaf ref."""
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
            *((f"{record.ref}#working",) if record.working else ()),
        ]
        if record.output is not None:
            targets.append(f"{record.ref}#output")
        if suffix == "actions":
            targets = [item for item in targets if "#action/" in item]
        elif suffix == "timeline":
            timeline_refs = {item.ref for item in record.timeline}
            targets = [item for item in targets if item in timeline_refs]
        elif suffix:
            targets = [f"{record.ref}#{suffix}"]
        ordered = dict.fromkeys(item.ref for item in record.timeline)
        targets = [
            *(target for target in ordered if target in targets),
            *(target for target in targets if target not in ordered),
        ]
        return tuple(
            (target, "Session fact", self._detail(record, target)) for target in targets
        )

    def _unclassified(self) -> tuple[str, ...]:
        covered = {
            edge.target.partition("#")[0]
            for edge in self.annotations.edges
            if edge.status is AnnotationStatus.ACTIVE
            and edge.relation is SemanticRelation.COVERS
        }
        return tuple(ref for ref in self.manifest.refs if ref not in covered)

    def _source_refs(self) -> set[str]:
        return {
            ref
            for item in (*self.annotations.nodes, *self.annotations.edges)
            for ref in item.source_refs
        }

    def _annotation_page(self, ref: str) -> DisclosurePage:
        if ref in {"session:topics", "session:annotations"}:
            objects = (*self.annotations.nodes, *self.annotations.edges)
            children = tuple(
                DisclosureHint(
                    item.ref,
                    item.title
                    if isinstance(item, SemanticNode)
                    else item.relation.value,
                    f"{item.status.value}: {item.body[:240]}",
                )
                for item in objects
                if ref == "session:annotations"
                or (
                    isinstance(item, SemanticNode)
                    and item.kind is AnnotationKind.THREAD
                    and item.status is AnnotationStatus.ACTIVE
                )
            )
            return DisclosurePage(ref, "session_annotations", children=children)
        item = self.annotations.get(ref)
        if item is None:
            raise _request_error(
                SessionInspectFailureReason.UNKNOWN_REF,
                "Unknown Session annotation",
                ref=ref,
            )
        relations = annotation_relations(self.annotations, ref)
        targets = dict.fromkeys(
            endpoint
            for edge in (relations if isinstance(item, SemanticNode) else (item,))
            for endpoint in (edge.source, edge.target)
            if endpoint != ref
        )
        children = tuple(
            DisclosureHint(
                target,
                "Related interpretation"
                if target.startswith("session:node/")
                else "History fact",
            )
            for target in targets
        )
        return DisclosurePage(
            ref,
            "session_annotation",
            content=(annotation_content(item),),
            children=children,
            related=tuple(annotation_content(edge) for edge in relations),
            sources=item.source_refs,
        )

    def _record(self, ref: str) -> SessionTurnRecord:
        if ref in self._records:
            return self._records[ref]
        try:
            record = validate_turn_record(self._store.load_record(ref))
            if record.day != self.manifest.day:
                raise SessionInvariantError(
                    "Session view contains another day's record"
                )
            self._records[ref] = record
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
