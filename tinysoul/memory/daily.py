"""Side-effect-free hierarchical daily Memory composition."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Protocol

from tinysoul.infra.time import BusinessDay
from tinysoul.llm import (
    AnswerFormat,
    CallSettings,
    JsonAnswer,
    MessageStack,
    ModelContextOverflowPolicy,
    SystemMessage,
    TaskCall,
    TaskProfile,
    TaskResult,
    TaskResultStatus,
    ToolUse,
    UserMessage,
)
from tinysoul.runtime import RunScope
from tinysoul.session import SessionMemoryFactsProjection

from .active import ActiveMemorySnapshot
from .config import MemoryDailyCompositionSettings
from .documents import StoredMemoryDocument
from .errors import MemoryContractError


@dataclass(frozen=True)
class DailyCompositionRequest:
    day: BusinessDay
    session: SessionMemoryFactsProjection
    active_memory: ActiveMemorySnapshot
    latest: StoredMemoryDocument | None
    existing: StoredMemoryDocument | None
    settings: MemoryDailyCompositionSettings
    max_document_chars: int

    def sources(self) -> tuple[str, ...]:
        values = [
            json.dumps(
                {
                    "kind": "session_facts",
                    "day": str(self.day),
                    "revision": self.session.revision,
                    "facts": [fact.to_json() for fact in self.session.facts],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            json.dumps(
                {
                    "kind": "archived_active_memory",
                    "day": self.active_memory.day.isoformat(),
                    "content": self.active_memory.content,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        ]
        if self.latest is not None:
            values.append(
                json.dumps(
                    {"kind": "latest_daily", "link": str(self.latest.link), "markdown": self.latest.text},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        if self.existing is not None:
            values.append(
                json.dumps(
                    {"kind": "existing_target_daily", "link": str(self.existing.link), "markdown": self.existing.text},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        return tuple(values)


@dataclass(frozen=True)
class DailyCompositionResult:
    content: str
    model_calls: int


class DailyCompositionModelRunner(Protocol):
    def run(self, call: TaskCall) -> TaskResult:
        ...


class LLMDailyMemoryComposer:
    def __init__(self, runner: DailyCompositionModelRunner) -> None:
        self._runner = runner

    def compose(
        self,
        request: DailyCompositionRequest,
        *,
        scope: RunScope,
    ) -> DailyCompositionResult:
        if not isinstance(request, DailyCompositionRequest):
            raise MemoryContractError("Daily composition request is invalid")
        sources = request.sources()
        if sum(len(item) for item in sources) > request.settings.source_max_chars:
            raise MemoryContractError("Daily composition sources exceed their limit")
        calls = 0
        chunks = _pack(_fragment(sources, request.settings.chunk_max_chars), request.settings.chunk_max_chars)
        if len(chunks) + 1 > request.settings.max_calls:
            raise MemoryContractError("Daily composition requires too many model calls")
        summaries: list[str] = []
        for chunk in chunks:
            calls += 1
            summaries.append(
                self._call(
                    MessageStack.of(
                        SystemMessage.from_text(
                            "Summarize only events, decisions, actions, results, context changes, and open items from the supplied target-day sources. Preserve chronology and canonical Memory links; do not invent facts.",
                            label="memory_daily_reduce_role",
                        ),
                        UserMessage.from_json(
                            {"day": str(request.day), "sources": list(chunk)},
                            label="memory_daily_reduce_input",
                        ),
                        UserMessage.from_text(
                            'Return exactly {"content":"bounded Markdown notes"}.',
                            label="memory_daily_reduce_output",
                        ),
                    ),
                    scope=scope,
                )
            )
        feedback: tuple[str, ...] = ()
        for _ in range(request.settings.validation_retries + 1):
            if calls >= request.settings.max_calls:
                break
            calls += 1
            messages = [
                SystemMessage.from_text(
                    "Compose the complete daily Memory body for one target Business Day. Record what happened that day, preserve evidence and useful canonical Memory links, deduplicate, and do not turn the daily into a current encyclopedia. Existing target daily is review input, not immutable text. Do not include an H1 because the framework renders it.",
                    label="memory_daily_role",
                ),
                UserMessage.from_json(
                    {"day": str(request.day), "summaries": summaries},
                    label="memory_daily_input",
                ),
            ]
            if feedback:
                messages.append(
                    UserMessage.from_json(
                        {"validation_errors": list(feedback)},
                        label="memory_daily_feedback",
                    )
                )
            messages.append(
                UserMessage.from_text(
                    'Return exactly {"content":"complete non-empty Markdown body"}.',
                    label="memory_daily_output",
                )
            )
            content = self._call(MessageStack(tuple(messages)), scope=scope)
            error = _validate(content, max_chars=request.max_document_chars)
            if error is None:
                return DailyCompositionResult(content=content, model_calls=calls)
            feedback = (error,)
        raise MemoryContractError("Daily composition did not produce valid Markdown")

    def _call(self, messages: MessageStack, *, scope: RunScope) -> str:
        result = self._runner.run(
            TaskCall(
                profile=TaskProfile.MEMORY_DAILY_COMPOSITION,
                messages=messages,
                settings=CallSettings(
                    answer_format=AnswerFormat.JSON_OBJECT,
                    tool_use=ToolUse.DISABLED,
                ),
                scope=scope,
                context_overflow_policy=ModelContextOverflowPolicy.END_TURN,
            )
        )
        if result.status is TaskResultStatus.FAILURE or not isinstance(result.answer, JsonAnswer):
            raise MemoryContractError("Daily composition model call failed")
        value = result.answer.value
        if set(value) != {"content"}:
            raise MemoryContractError("Daily composition output fields are invalid")
        content = value.get("content")
        if not isinstance(content, str) or not content.strip():
            raise MemoryContractError("Daily composition content is empty")
        return content.strip()


def _validate(content: str, *, max_chars: int) -> str | None:
    if len(content) + 256 > max_chars:
        return "Daily content exceeds its configured document limit."
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^ {0,3}#(?:[ \t]|$)", line):
            return "Daily content must not contain a level-1 heading."
        if (
            index > 0
            and lines[index - 1].strip()
            and re.fullmatch(r" {0,3}=+[ \t]*", line)
        ):
            return "Daily content must not contain a setext level-1 heading."
    return None


def _fragment(sources: tuple[str, ...], limit: int) -> tuple[str, ...]:
    size = max(1, limit - 96)
    result: list[str] = []
    for source_index, source in enumerate(sources, start=1):
        count = max(1, (len(source) + size - 1) // size)
        for index in range(count):
            result.append(
                f"[source {source_index} part {index + 1}/{count}]\n{source[index * size:(index + 1) * size]}"
            )
    return tuple(result)


def _pack(sources: tuple[str, ...], limit: int) -> tuple[tuple[str, ...], ...]:
    chunks: list[tuple[str, ...]] = []
    current: list[str] = []
    used = 0
    for source in sources:
        added = len(source) + (2 if current else 0)
        if current and used + added > limit:
            chunks.append(tuple(current))
            current = []
            used = 0
        current.append(source)
        used += len(source) + (2 if len(current) > 1 else 0)
    if current:
        chunks.append(tuple(current))
    return tuple(chunks)
