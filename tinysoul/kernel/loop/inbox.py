"""Kernel-owned bounded admission, fixed batches and non-consuming waits."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
from math import isfinite
from uuid import uuid4

from tinysoul.infra.json import JsonObject, to_json_object


class InboxKind(StrEnum):
    INPUT = "input"
    REPLY = "reply"
    EVENT = "event"
    TIMER = "timer"
    JOB = "job"


class WaitReason(StrEnum):
    INPUT = "input"
    EVENT = "event"
    TIMER = "timer"
    BUDGET = "budget"


@dataclass(frozen=True)
class BudgetRequest:
    request_id: str
    next_cycle_index: int

    def __post_init__(self) -> None:
        if not self.request_id or type(self.next_cycle_index) is not int or self.next_cycle_index <= 0:
            raise InboxError("Budget request identity or Cycle index is invalid")


@dataclass(frozen=True)
class QuestionRequest:
    question_id: str
    text: str
    options: tuple[str, ...] = ()
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.question_id or not isinstance(self.text, str) or not self.text.strip():
            raise InboxError("Question identity and text are required")
        if any(not isinstance(item, str) or not item for item in self.options):
            raise InboxError("Question options must be non-empty text")
        if self.timeout_seconds is not None and (
            type(self.timeout_seconds) not in (int, float)
            or not isfinite(self.timeout_seconds) or self.timeout_seconds <= 0
        ):
            raise InboxError("Question timeout must be finite and positive")
        object.__setattr__(self, "options", tuple(self.options))


class InboxError(Exception):
    """The caller violated the Turn admission or batch contract."""


class InboxClosedError(InboxError):
    """The Turn no longer accepts ordinary records."""


class InboxCapacityError(InboxError):
    """Admission would exceed the bounded pending work."""


@dataclass(frozen=True)
class InboxRecord:
    kind: InboxKind
    payload: JsonObject
    record_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, InboxKind):
            raise InboxError("Inbox record kind is invalid")
        try:
            payload = to_json_object(self.payload)
        except (TypeError, ValueError) as exc:
            raise InboxError("Inbox record requires a JSON object") from exc
        if self.kind in {InboxKind.INPUT, InboxKind.REPLY}:
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip():
                raise InboxError("Input requires non-empty text")
        if not isinstance(self.record_id, str):
            raise InboxError("Record identity must be text")
        object.__setattr__(self, "record_id", self.record_id or f"record_{uuid4().hex}")
        object.__setattr__(self, "payload", payload)


@dataclass(frozen=True)
class InboxReceipt:
    sequence: int
    record_id: str
    accepted: bool


@dataclass(frozen=True)
class InboxBatch:
    records: tuple[tuple[int, InboxRecord], ...]

    @property
    def next_sequence(self) -> int:
        return self.records[-1][0] if self.records else 0


@dataclass(frozen=True)
class InboxLimits:
    """Ordinary backlog plus separately reserved reply and Job terminal slots."""

    capacity: int = 64
    max_bytes: int = 256_000
    max_record_bytes: int = 64_000
    retained_receipts: int = 128
    terminal_capacity: int = 16
    max_terminal_bytes: int = 8192

    def __post_init__(self) -> None:
        if any(type(value) is not int or value <= 0 for value in (
            self.capacity, self.max_bytes, self.max_record_bytes,
            self.retained_receipts, self.terminal_capacity, self.max_terminal_bytes,
        )):
            raise InboxError("Inbox limits must be positive integers")


class TurnInbox:
    """One consumer installs a captured batch before acknowledging it."""

    def __init__(self, limits: InboxLimits = InboxLimits()) -> None:
        if not isinstance(limits, InboxLimits):
            raise InboxError("Inbox requires typed limits")
        self._capacity = limits.capacity
        self._max_bytes = limits.max_bytes
        self._max_record_bytes = limits.max_record_bytes
        self._retained_receipts = limits.retained_receipts
        self._terminal_capacity = limits.terminal_capacity
        self._max_terminal_bytes = limits.max_terminal_bytes
        self._records: list[tuple[int, InboxRecord, int]] = []
        self._receipts: OrderedDict[str, tuple[int, str]] = OrderedDict()
        self._bytes = 0
        self._sequence = 0
        self._closed = False
        self._captured: InboxBatch | None = None
        self._condition = asyncio.Condition()
        self._budget_request: BudgetRequest | None = None
        self._grant: int | None = None
        self._decisions: OrderedDict[str, int] = OrderedDict()
        self._wait_reason: WaitReason | None = None
        self._question: QuestionRequest | None = None
        self._reply: tuple[int, InboxRecord, int] | None = None
        self._terminals: dict[str, tuple[int, InboxRecord, int] | None] = {}

    async def reserve_terminal(self, job_id: str, *, required_bytes: int = 1) -> None:
        async with self._condition:
            if type(required_bytes) is not int or required_bytes <= 0:
                raise InboxError("Terminal reservation requires a positive byte bound")
            if self._closed:
                raise InboxClosedError("Cannot start a Job in a closed Turn")
            if (required_bytes > self._max_terminal_bytes or job_id in self._terminals
                    or len(self._terminals) >= self._terminal_capacity):
                raise InboxCapacityError("Job terminal reservations are full")
            self._terminals[job_id] = None

    async def deliver_terminal(self, job_id: str, payload: JsonObject) -> None:
        record = InboxRecord(InboxKind.JOB, payload, f"job_terminal:{job_id}")
        size = len(_encode(record))
        async with self._condition:
            if job_id not in self._terminals:
                raise InboxError("Job terminal delivery requires its reserved identity")
            if size > self._max_terminal_bytes:
                raise InboxCapacityError("Job terminal summary exceeds its reservation")
            if self._terminals[job_id] is not None:
                return
            self._sequence += 1
            self._terminals[job_id] = (self._sequence, record, size)
            self._condition.notify_all()

    async def release_terminal(self, job_id: str) -> None:
        async with self._condition:
            # Accepted terminal facts remain until their captured batch is acked.
            if job_id in self._terminals and self._terminals[job_id] is None:
                del self._terminals[job_id]

    @property
    def question(self) -> QuestionRequest | None:
        return self._question

    async def open_question(self, question: QuestionRequest) -> None:
        async with self._condition:
            if self._closed or self._question is not None or self._reply is not None:
                raise InboxError("A Turn can wait for one question at a time")
            self._question = question
            self._condition.notify_all()

    async def reply(self, question_id: str, text: str) -> InboxReceipt:
        record = InboxRecord(InboxKind.REPLY, {"text": text, "reply_to": question_id},
                             f"reply_{question_id}")
        encoded = _encode(record)
        digest = sha256(encoded).hexdigest()
        async with self._condition:
            previous = self._receipts.get(record.record_id)
            if previous is not None:
                if previous[1] != digest:
                    raise InboxError("Question already received a different reply")
                return InboxReceipt(previous[0], record.record_id, False)
            if self._closed or self._question is None or self._question.question_id != question_id:
                raise InboxClosedError("Question is not awaiting a reply")
            if len(encoded) > self._max_record_bytes:
                raise InboxCapacityError("Reply exceeds the reserved record size")
            self._sequence += 1
            self._reply = (self._sequence, record, len(encoded))
            self._receipts[record.record_id] = (self._sequence, digest)
            self._condition.notify_all()
            return InboxReceipt(self._sequence, record.record_id, True)

    async def wait_for_reply(self, question: QuestionRequest) -> bool:
        async with self._condition:
            if self._question is not question:
                raise InboxError("Wait requires the active question")
            self._wait_reason = WaitReason.INPUT
            try:
                await asyncio.wait_for(self._condition.wait_for(
                    lambda: self._reply is not None or self._closed,
                ), question.timeout_seconds)
                return self._reply is not None
            except TimeoutError:
                return False
            finally:
                self._wait_reason = None
                self._question = None

    @property
    def budget_request(self) -> BudgetRequest | None:
        return self._budget_request

    @property
    def wait_reason(self) -> WaitReason | None:
        return self._wait_reason

    async def request_budget(self, next_cycle_index: int) -> BudgetRequest:
        async with self._condition:
            if self._closed or self._budget_request is not None:
                raise InboxError("Cannot issue a budget request in this state")
            request = BudgetRequest(f"budget_{uuid4().hex}", next_cycle_index)
            self._budget_request = request
            self._condition.notify_all()
            return request

    async def grant_cycles(self, request_id: str, count: int) -> bool:
        if type(count) is not int or count <= 0:
            raise InboxError("Budget grants require a positive integer")
        async with self._condition:
            existing = self._decisions.get(request_id)
            if existing is not None:
                if existing != count:
                    raise InboxError("Budget decision conflicts with its previous grant")
                return False
            if self._closed or self._budget_request is None or self._budget_request.request_id != request_id:
                raise InboxClosedError("Budget request is not active")
            self._decisions[request_id] = count
            while len(self._decisions) > self._retained_receipts:
                self._decisions.popitem(last=False)
            self._grant = count
            self._condition.notify_all()
            return True

    async def wait_for_budget(self, request: BudgetRequest) -> int:
        async with self._condition:
            if request is not self._budget_request:
                raise InboxError("Wait requires the current budget request")
            self._wait_reason = WaitReason.BUDGET
            try:
                await self._condition.wait_for(lambda: self._grant is not None or self._closed)
                if self._closed:
                    raise InboxClosedError("Turn ended while waiting for budget")
                count = self._grant
                if count is None:
                    raise InboxError("Budget wait resumed without a grant")
                self._budget_request = None
                self._grant = None
                return count
            finally:
                self._wait_reason = None

    async def accept(self, record: InboxRecord) -> InboxReceipt:
        if not isinstance(record, InboxRecord):
            raise InboxError("Inbox accepts typed records only")
        if record.kind in {InboxKind.REPLY, InboxKind.JOB}:
            raise InboxError("Replies and Job terminals require a registered identity")
        record = InboxRecord(record.kind, record.payload, record.record_id)
        encoded = _encode(record)
        digest = sha256(encoded).hexdigest()
        size = len(encoded)
        async with self._condition:
            existing = self._receipts.get(record.record_id)
            if existing is not None:
                if existing[1] != digest:
                    raise InboxError("Record identity was reused with different content")
                return InboxReceipt(existing[0], record.record_id, False)
            if self._closed:
                raise InboxClosedError("Turn inbox is closed")
            if (len(self._records) >= self._capacity or self._bytes + size > self._max_bytes
                    or size > self._max_record_bytes):
                raise InboxCapacityError("Turn inbox capacity is full")
            self._sequence += 1
            self._records.append((self._sequence, record, size))
            self._receipts[record.record_id] = (self._sequence, digest)
            self._bytes += size
            self._condition.notify_all()
            return InboxReceipt(self._sequence, record.record_id, True)

    async def capture(self) -> InboxBatch:
        async with self._condition:
            if self._captured is None:
                pending = [*self._records, *([self._reply] if self._reply is not None else []),
                           *(item for item in self._terminals.values() if item is not None)]
                self._captured = InboxBatch(tuple(
                    (seq, InboxRecord(record.kind, record.payload, record.record_id))
                    for seq, record, _ in sorted(pending, key=lambda item: item[0])
                ))
            return self._captured

    async def ack(self, batch: InboxBatch) -> None:
        async with self._condition:
            if batch is not self._captured:
                raise InboxError("Only the captured batch can be acknowledged")
            self._records = [item for item in self._records if item[0] > batch.next_sequence]
            if self._reply is not None and self._reply[0] <= batch.next_sequence:
                self._reply = None
            self._terminals = {key: item for key, item in self._terminals.items()
                               if item is None or item[0] > batch.next_sequence}
            self._bytes = sum(size for _, _, size in self._records)
            self._captured = None
            pending = {record.record_id for _, record, _ in self._records}
            if self._reply is not None:
                pending.add(self._reply[1].record_id)
            for record_id in tuple(self._receipts):
                if len(self._receipts) <= self._retained_receipts + len(pending):
                    break
                if record_id not in pending:
                    del self._receipts[record_id]

    async def wait(self, *, after_sequence: int = 0, timeout: float | None = None) -> bool:
        """Observe readiness without taking or acknowledging consumer records."""
        if type(after_sequence) is not int or after_sequence < 0:
            raise InboxError("Wait cursor must be a non-negative integer")
        if timeout is not None and (
            type(timeout) not in (int, float) or not isfinite(timeout) or timeout < 0
        ):
            raise InboxError("Wait timeout must be finite and non-negative")
        async with self._condition:
            def ready() -> bool:
                return (any(seq > after_sequence for seq, _, _ in self._records)
                        or any(item is not None and item[0] > after_sequence
                               for item in self._terminals.values()))
            if ready():
                return True
            if self._closed:
                return False
            try:
                self._wait_reason = WaitReason.EVENT if timeout is None else WaitReason.TIMER
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: ready() or self._closed), timeout,
                )
            except TimeoutError:
                return False
            finally:
                self._wait_reason = None
            return ready()

    async def close_if_empty(self) -> bool:
        async with self._condition:
            if self._records or self._reply is not None or self._terminals:
                return False
            self._closed = True
            self._condition.notify_all()
            return True

    async def close(self) -> None:
        async with self._condition:
            self._closed = True
            self._condition.notify_all()


def _encode(record: InboxRecord) -> bytes:
    try:
        return json.dumps(
            {"id": record.record_id, "kind": record.kind.value, "payload": record.payload},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise InboxError("Inbox record must have a finite UTF-8 JSON representation") from exc
