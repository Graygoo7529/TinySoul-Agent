"""Fixed views over the Session owner's immutable completed records."""

from __future__ import annotations

from dataclasses import dataclass, field

from tinysoul.infra.continuation import (
    ContinuationError,
    ContinuationFailureReason,
    OpaqueContinuationCodec,
    continue_json_sequence,
)
from tinysoul.infra.json import JsonObject, dumps_json
from tinysoul.infra.time import CalendarDay

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
    action_collection_ref,
    action_leaf_ref,
    parse_action_ref,
    project_action,
    project_action_header,
    project_map,
    project_turn,
    project_occurrence,
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
        )

    def inspect(
        self,
        ref: str | None = None,
        *,
        action: str | None = None,
        continuation: str | None = None,
        expected_revision: int | None = None,
    ) -> JsonObject:
        """Inspect the factual Map, one Turn, or its Action occurrences."""

        manifest = self.manifest
        if expected_revision is not None and expected_revision != manifest.revision:
            raise SessionContractError("Session view source changed during its Turn")
        if action is not None and (not isinstance(action, str) or not action):
            raise SessionInspectRequestError(
                SessionInspectFailureReason.INVALID_REF,
                "Session Action filter must be non-empty text",
                scope="session.inspect",
            )
        try:
            action_ref = parse_action_ref(ref) if ref is not None else None
        except SessionContractError as exc:
            raise _request_error(
                SessionInspectFailureReason.INVALID_REF,
                str(exc),
                ref=ref,
            ) from exc
        if action_ref is not None:
            record = self._load_turn(action_ref.turn_ref)
            if action_ref.is_collection:
                collection_ref = action_collection_ref(record.ref)
                actions = tuple(
                    project_action_header(record.ref, index, item)
                    for index, item in enumerate(record.actions)
                    if action is None or item.action == action
                )
                return self._page(
                    actions,
                    base={"kind": "session_actions", "ref": collection_ref},
                    item_field="actions",
                    continuation=continuation,
                    ref=collection_ref,
                    binding=({"action": action} if action is not None else None),
                )
            if action is not None:
                raise _request_error(
                    SessionInspectFailureReason.WRONG_RECORD_KIND,
                    "Session Action filter only applies to an Action collection",
                    ref=ref,
                )
            assert action_ref.occurrence is not None
            if action_ref.occurrence >= len(record.actions):
                raise _request_error(
                    SessionInspectFailureReason.UNKNOWN_REF,
                    "Unknown Session Action ref",
                    ref=ref,
                )
            detail = project_action(
                record.ref,
                action_ref.occurrence,
                record.actions[action_ref.occurrence],
            )
            leaf_ref = action_leaf_ref(record.ref, action_ref.occurrence)
            return self._page(
                (detail,),
                base={"kind": "session_action", "ref": leaf_ref},
                item_field="content",
                continuation=continuation,
                ref=leaf_ref,
            )
        if action is not None:
            raise _request_error(
                SessionInspectFailureReason.WRONG_RECORD_KIND,
                "Session Action filter requires an Action collection ref",
                ref=ref,
            )
        if ref is None or ref == "session:map":
            nodes = project_map(tuple(self._record(item) for item in manifest.refs))
            return self._page(
                nodes,
                base={
                    "kind": "session_map",
                    "ref": "session:map",
                    "total_turns": len(manifest.refs),
                },
                item_field="nodes",
                continuation=continuation,
                ref="session:map",
                binding={"revision": manifest.revision},
            )
        if "#" in ref:
            turn_ref, suffix = ref.split("#", 1)
            record = self._requested_record(turn_ref)
            try:
                detail = project_occurrence(record, suffix)
            except SessionContractError as exc:
                raise _request_error(
                    SessionInspectFailureReason.UNKNOWN_REF,
                    "Unknown Session occurrence",
                    ref=ref,
                ) from exc
            return self._page(
                (detail,),
                base={"kind": detail["kind"], "ref": ref},
                item_field="content",
                continuation=continuation,
                ref=ref,
            )
        record = self._requested_record(ref)
        detail = project_turn(record)
        return self._page(
            (detail,),
            base={"kind": "session_turn", "ref": ref},
            item_field="content",
            continuation=continuation,
            ref=ref,
        )

    def _page(
        self,
        values: tuple[JsonObject, ...],
        *,
        base: JsonObject,
        item_field: str,
        continuation: str | None,
        ref: str,
        binding: JsonObject | None = None,
    ) -> JsonObject:
        try:
            return continue_json_sequence(
                values,
                base={**base, "day": self.manifest.day},
                item_field=item_field,
                continuation=continuation,
                codec=self._continuations,
                ref=ref,
                binding={
                    **(binding or {}),
                    "day": self.manifest.day,
                    "revision": self.manifest.revision,
                },
                max_chars=self.settings.inspect_max_chars,
            )
        except ContinuationError as exc:
            reason = (
                SessionInspectFailureReason.PAGE_BUDGET_TOO_SMALL
                if exc.reason is ContinuationFailureReason.BUDGET_TOO_SMALL
                else SessionInspectFailureReason.INVALID_CONTINUATION
            )
            raise _request_error(reason, str(exc), ref=ref) from exc

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

    def _load_turn(self, ref: str) -> SessionTurnRecord:
        return self._requested_record(ref)


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
