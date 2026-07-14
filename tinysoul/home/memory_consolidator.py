"""LLM-backed hierarchical consolidation for date-scoped MEMORY."""

from __future__ import annotations

from typing import Protocol

from tinysoul.infra.json import JsonObject
from tinysoul.llm import (
    AnswerFormat,
    CallSettings,
    JsonAnswer,
    MessageStack,
    SystemMessage,
    TaskCall,
    TaskProfile,
    TaskResult,
    TaskResultStatus,
    ToolUse,
    UserMessage,
)
from tinysoul.runtime import RunScope

from .memory import (
    MemoryConsolidationError,
    MemoryConsolidationRequest,
    MemoryConsolidationResult,
    MemoryMaintenanceFailure,
    MemoryPeriod,
    MemoryPeriodSources,
    MemorySections,
    _validate_sections,
)


class MemoryMaintenanceModelRunner(Protocol):
    def run(self, call: TaskCall) -> TaskResult:
        ...


class LLMMemoryConsolidator:
    """Hierarchically reduce period facts through the dedicated LLM profile."""

    def __init__(self, runner: MemoryMaintenanceModelRunner) -> None:
        self._runner = runner

    def consolidate(
        self,
        request: MemoryConsolidationRequest,
        *,
        scope: RunScope,
    ) -> MemoryConsolidationResult:
        budget = _CallBudget(request.max_calls)
        target_chars = max(
            256,
            min(
                4000,
                request.chunk_max_chars // 3,
                request.max_document_chars // 3,
            ),
        )
        candidates = {
            item.period: self._reduce_period(
                request,
                item,
                target_chars=target_chars,
                budget=budget,
                scope=scope,
            )
            for item in request.periods
        }
        feedback: tuple[str, ...] = ()
        last_error: MemoryConsolidationError | None = None
        for _ in range(request.validation_retries + 1):
            try:
                sections = self._final_sections(
                    request,
                    candidates=candidates,
                    feedback=feedback,
                    budget=budget,
                    scope=scope,
                )
                _validate_sections(
                    request.day,
                    sections,
                    allowed_links=frozenset(request.allowed_links),
                    max_document_chars=request.max_document_chars,
                )
                return MemoryConsolidationResult(
                    sections=sections,
                    model_calls=budget.used,
                )
            except MemoryConsolidationError as exc:
                last_error = exc
                feedback = (str(exc)[:1000],)
        if last_error is None:
            raise MemoryConsolidationError(
                MemoryMaintenanceFailure.CONSOLIDATION_FAILED,
                "Memory consolidation ended without a result",
            )
        raise last_error

    def _reduce_period(
        self,
        request: MemoryConsolidationRequest,
        period_sources: MemoryPeriodSources,
        *,
        target_chars: int,
        budget: "_CallBudget",
        scope: RunScope,
    ) -> str:
        if not period_sources.sources:
            return ""
        level = _fragment_sources(
            period_sources.sources,
            max_chars=request.chunk_max_chars,
        )
        while True:
            reduced: list[str] = []
            for chunk in _pack_sources(level, max_chars=request.chunk_max_chars):
                value = self._run_json(
                    MessageStack.of(
                        SystemMessage.from_text(
                            "Consolidate only durable facts for one period of one "
                            "Business Day MEMORY. Preserve useful existing facts, "
                            "deduplicate repeated facts, do not invent facts, and "
                            "keep Home top links in <home:space@name> form.",
                            label="memory_maintenance_reduce_role",
                        ),
                        UserMessage.from_json(
                            {
                                "day": str(request.day),
                                "period": period_sources.period.value,
                                "sources": chunk,
                                "target_max_chars": target_chars,
                            },
                            label="memory_maintenance_reduce_input",
                        ),
                        UserMessage.from_text(
                            'Return exactly {"content":"Markdown body"}. Do not '
                            "include level-1 or level-2 headings.",
                            label="memory_maintenance_reduce_output",
                        ),
                    ),
                    budget=budget,
                    scope=scope,
                )
                if set(value) != {"content"}:
                    raise MemoryConsolidationError(
                        MemoryMaintenanceFailure.INVALID_OUTPUT,
                        "Memory reduce output must contain only content",
                    )
                content = _required_text(value, "content").strip()
                if len(content) > target_chars:
                    raise MemoryConsolidationError(
                        MemoryMaintenanceFailure.INVALID_OUTPUT,
                        "Memory reduce output exceeds its target size",
                    )
                if not content:
                    raise MemoryConsolidationError(
                        MemoryMaintenanceFailure.INVALID_OUTPUT,
                        "Memory reduce output cannot be empty for non-empty sources",
                    )
                reduced.append(content)
            if len(reduced) == 1:
                return reduced[0]
            level = tuple(reduced)

    def _final_sections(
        self,
        request: MemoryConsolidationRequest,
        *,
        candidates: dict[MemoryPeriod, str],
        feedback: tuple[str, ...],
        budget: "_CallBudget",
        scope: RunScope,
    ) -> MemorySections:
        messages = [
            SystemMessage.from_text(
                "Produce the complete replacement for one Business Day MEMORY. "
                "Keep facts in their supplied period, deduplicate, do not invent "
                "facts, and use only existing Home top links in "
                "<home:space@name> form. Section headings are rendered by the "
                "framework and must not appear in section bodies.",
                label="memory_maintenance_role",
            ),
            UserMessage.from_json(
                {
                    "day": str(request.day),
                    "period_candidates": {
                        period.value: candidates[period] for period in MemoryPeriod
                    },
                },
                label="memory_maintenance_candidates",
            ),
        ]
        if feedback:
            messages.append(
                UserMessage.from_json(
                    {"validation_errors": list(feedback)},
                    label="memory_maintenance_feedback",
                )
            )
        messages.append(
            UserMessage.from_text(
                "Return exactly one JSON object with string fields morning, "
                "afternoon, and evening. Values are Markdown bodies without "
                "level-1 or level-2 headings.",
                label="memory_maintenance_output",
            )
        )
        value = self._run_json(
            MessageStack(tuple(messages)),
            budget=budget,
            scope=scope,
        )
        return MemorySections.from_json(value)

    def _run_json(
        self,
        messages: MessageStack,
        *,
        budget: "_CallBudget",
        scope: RunScope,
    ) -> JsonObject:
        budget.consume()
        result = self._runner.run(
            TaskCall(
                profile=TaskProfile.MEMORY_MAINTENANCE,
                messages=messages,
                settings=CallSettings(
                    answer_format=AnswerFormat.JSON_OBJECT,
                    tool_use=ToolUse.DISABLED,
                ),
                scope=scope,
            )
        )
        if result.status is TaskResultStatus.FAILURE:
            raise MemoryConsolidationError(
                MemoryMaintenanceFailure.CONSOLIDATION_FAILED,
                "Memory maintenance LLM task failed",
            )
        if not isinstance(result.answer, JsonAnswer):
            raise MemoryConsolidationError(
                MemoryMaintenanceFailure.INVALID_OUTPUT,
                "Memory maintenance did not return a JSON object",
            )
        return result.answer.value


class _CallBudget:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self.used = 0

    def consume(self) -> None:
        if self.used >= self._limit:
            raise MemoryConsolidationError(
                MemoryMaintenanceFailure.CONSOLIDATION_FAILED,
                "Memory consolidation exhausted its model call budget",
            )
        self.used += 1


def _fragment_sources(sources: tuple[str, ...], *, max_chars: int) -> tuple[str, ...]:
    fragment_limit = max(1, max_chars - 96)
    fragments: list[str] = []
    for source_index, source in enumerate(sources, start=1):
        part_count = max(1, (len(source) + fragment_limit - 1) // fragment_limit)
        for part_index in range(part_count):
            start = part_index * fragment_limit
            fragment = source[start : start + fragment_limit]
            fragments.append(
                f"[source {source_index} part {part_index + 1}/{part_count}]\n{fragment}"
            )
    return tuple(fragments)


def _pack_sources(
    sources: tuple[str, ...],
    *,
    max_chars: int,
) -> tuple[tuple[str, ...], ...]:
    chunks: list[tuple[str, ...]] = []
    current: list[str] = []
    used = 0
    for source in sources:
        added = len(source) + (2 if current else 0)
        if current and used + added > max_chars:
            chunks.append(tuple(current))
            current = []
            used = 0
            added = len(source)
        if len(source) > max_chars:
            raise MemoryConsolidationError(
                MemoryMaintenanceFailure.INPUT_TOO_LARGE,
                "Memory source fragment exceeds its chunk budget",
            )
        current.append(source)
        used += added
    if current:
        chunks.append(tuple(current))
    return tuple(chunks)


def _required_text(value: JsonObject, name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str):
        raise MemoryConsolidationError(
            MemoryMaintenanceFailure.INVALID_OUTPUT,
            f"Memory output field must be a string: {name}",
        )
    return item
