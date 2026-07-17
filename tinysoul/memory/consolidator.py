"""LLM-backed hierarchical consolidation for date-scoped MEMORY."""

from __future__ import annotations

from typing import Protocol

from tinysoul.infra.json import JsonObject
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

from .maintenance import (
    MemoryConsolidationError,
    MemoryConsolidationRequest,
    MemoryConsolidationResult,
    MemoryMaintenanceFailure,
    validate_memory_body,
)


class MemoryMaintenanceModelRunner(Protocol):
    def run(self, call: TaskCall) -> TaskResult: ...


class LLMMemoryConsolidator:
    """Hierarchically reduce ordered daily sources through one LLM profile."""

    def __init__(self, runner: MemoryMaintenanceModelRunner) -> None:
        self._runner = runner

    def consolidate(
        self,
        request: MemoryConsolidationRequest,
        *,
        scope: RunScope,
    ) -> MemoryConsolidationResult:
        budget = _CallBudget(request.max_calls)
        body_max_chars = max(
            1,
            request.max_document_chars - len(f"# {request.day}\n\n\n"),
        )
        target_chars = max(
            1,
            min(8000, request.chunk_max_chars // 3, body_max_chars),
        )
        candidate = self._reduce_sources(
            request,
            target_chars=target_chars,
            budget=budget,
            scope=scope,
        )
        feedback: tuple[str, ...] = ()
        last_error: MemoryConsolidationError | None = None
        for _ in range(request.validation_retries + 1):
            try:
                body = self._final_body(
                    request,
                    candidate=candidate,
                    feedback=feedback,
                    budget=budget,
                    scope=scope,
                )
                validate_memory_body(
                    request.day,
                    body,
                    allowed_home_links=frozenset(request.allowed_home_links),
                    allowed_memory_links=frozenset(request.allowed_memory_links),
                    max_document_chars=request.max_document_chars,
                )
                return MemoryConsolidationResult(
                    body=body,
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

    def _reduce_sources(
        self,
        request: MemoryConsolidationRequest,
        *,
        target_chars: int,
        budget: "_CallBudget",
        scope: RunScope,
    ) -> str:
        level = _fragment_sources(
            request.sources,
            max_chars=request.chunk_max_chars,
        )
        while True:
            reduced: list[str] = []
            for chunk in _pack_sources(level, max_chars=request.chunk_max_chars):
                value = self._run_json(
                    MessageStack.of(
                        SystemMessage.from_text(
                            "Consolidate only durable facts for one Business Day "
                            "MEMORY. Preserve useful existing facts, keep Session "
                            "facts in their supplied chronological order, deduplicate "
                            "repeated facts, do not invent facts, and preserve useful "
                            "Home and Memory links in angle-bracket form.",
                            label="memory_maintenance_reduce_role",
                        ),
                        UserMessage.from_json(
                            {
                                "day": str(request.day),
                                "sources": chunk,
                                "target_max_chars": target_chars,
                            },
                            label="memory_maintenance_reduce_input",
                        ),
                        UserMessage.from_text(
                            'Return exactly {"content":"Markdown body"}. Do not '
                            "include a level-1 heading.",
                            label="memory_maintenance_reduce_output",
                        ),
                    ),
                    budget=budget,
                    scope=scope,
                )
                content = _content(value)
                if len(content) > target_chars:
                    raise MemoryConsolidationError(
                        MemoryMaintenanceFailure.INVALID_OUTPUT,
                        "Memory reduce output exceeds its target size",
                    )
                reduced.append(content)
            if len(reduced) == 1:
                return reduced[0]
            level = tuple(reduced)

    def _final_body(
        self,
        request: MemoryConsolidationRequest,
        *,
        candidate: str,
        feedback: tuple[str, ...],
        budget: "_CallBudget",
        scope: RunScope,
    ) -> str:
        messages = [
            SystemMessage.from_text(
                "Produce the complete replacement body for one Business Day "
                "MEMORY. Use a clear free-form Markdown structure suited to the "
                "facts, deduplicate without inventing, and preserve chronology "
                "where it matters. The framework renders the date heading, so do "
                "not include a level-1 heading. Home links use <home:space@name> "
                "and Memory links use <memory:YYYY-MM-DD>. Link hints are useful "
                "known references, not an exhaustive catalog.",
                label="memory_maintenance_role",
            ),
            UserMessage.from_json(
                {
                    "day": str(request.day),
                    "consolidated_source": candidate,
                    "home_link_hints": list(request.home_link_hints),
                    "memory_link_hints": list(request.memory_link_hints),
                },
                label="memory_maintenance_candidate",
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
                'Return exactly {"content":"Markdown body"}. The body must be '
                "non-empty and must not contain a level-1 heading.",
                label="memory_maintenance_output",
            )
        )
        return _content(
            self._run_json(
                MessageStack(tuple(messages)),
                budget=budget,
                scope=scope,
            )
        )

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
                context_overflow_policy=ModelContextOverflowPolicy.END_TURN,
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


def _fragment_sources(
    sources: tuple[str, ...],
    *,
    max_chars: int,
) -> tuple[str, ...]:
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


def _content(value: JsonObject) -> str:
    if set(value) != {"content"}:
        raise MemoryConsolidationError(
            MemoryMaintenanceFailure.INVALID_OUTPUT,
            "Memory output must contain only content",
        )
    item = value.get("content")
    if not isinstance(item, str) or not item.strip():
        raise MemoryConsolidationError(
            MemoryMaintenanceFailure.INVALID_OUTPUT,
            "Memory output content must be non-empty text",
        )
    return item.strip()
