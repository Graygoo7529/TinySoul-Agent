"""Workspace actions use the same scoped service as SDK and Gateway."""

from __future__ import annotations

from tinysoul.kernel.action.tasks import ActionTaskFactory, ActionTaskOutput
from tinysoul.kernel.loop.phases import LLMRunner
from tinysoul.llm.protocol.responses import AnswerFormat
from tinysoul.kernel.action import (
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
    ActionResult,
)
from tinysoul.infra.json import JsonObject, to_json_object
from ..services import WorkspaceService
from ..errors import WorkspaceContractError, WorkspaceError
from ..runtime_bridge import RuntimeWorkspaceBridge
from ..inspection.models import WorkspaceAnalysisBudgetFailure
from ..prompts import WorkspaceAnalysisPromptBuilder

from .results import _success, _failed


class WorkspaceAnalyzeExecutor(ActionExecutor):
    """Analyze explicit complete Workspace text references without mutation."""

    def __init__(
        self,
        *,
        workspace: WorkspaceService,
        tasks: ActionTaskFactory,
        llm: LLMRunner,
        runtime_bridge: RuntimeWorkspaceBridge | None = None,
    ) -> None:
        self._workspace = workspace
        self._tasks, self._llm = tasks, llm
        self._runtime_bridge = runtime_bridge
        self._prompt_builder = WorkspaceAnalysisPromptBuilder()

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        workspace = self._workspace.using(context.owner_operations)
        intent = execution.call.params.get("intent")
        if not isinstance(intent, str) or not intent.strip():
            return _failed(
                execution,
                "workspace.analyze requires a non-empty 'intent' parameter.",
                {"reason": "invalid_intent"},
            )
        settings = workspace.analysis_settings
        if len(intent) > settings.max_intent_chars:
            return _failed(
                execution,
                "workspace.analyze intent exceeds its size limit.",
                {
                    "reason": "intent_chars_exceeded",
                    "limit": settings.max_intent_chars,
                    "observed": len(intent),
                },
            )
        links_value = execution.call.params.get("reference_links")
        if (
            not isinstance(links_value, list)
            or not links_value
            or any(not isinstance(link, str) or not link for link in links_value)
        ):
            return _failed(
                execution,
                "workspace.analyze reference_links must be a non-empty string array.",
                {"reason": "invalid_reference_links"},
            )
        links = tuple(link for link in links_value if isinstance(link, str))
        try:
            preparation = await workspace.prepare_analysis_references(links)
        except WorkspaceContractError as exc:
            return _failed(
                execution,
                "Workspace analysis references are invalid or unavailable.",
                {
                    "reason": "workspace_analysis_preparation_failed",
                    "error_type": type(exc).__name__,
                },
            )
        except WorkspaceError as exc:
            raise (
                self._runtime_bridge or RuntimeWorkspaceBridge()
            ).from_workspace_error(exc) from exc
        if preparation.failure is not None:
            budget_payload = _analysis_budget_payload(preparation.failure)
            return _failed(
                execution,
                "Workspace analysis references exceed the configured source budget.",
                budget_payload,
                payload=budget_payload,
            )
        analysis_input = preparation.input
        if analysis_input is None:
            return _failed(
                execution,
                "Workspace analysis preparation returned no input.",
                {"reason": "missing_analysis_input"},
            )
        prompt = self._prompt_builder.build(
            intent=intent.strip(),
            analysis_input=analysis_input,
            max_answer_chars=settings.max_answer_chars,
        )
        context.owner_operations.check_cancelled()
        context.control.check_cancelled()
        _task_result = await self._llm.run(
            await self._tasks.create(
                execution=execution,
                prompt=prompt,
                control=context.control,
                consumer=f"{execution.call.action_name}.generate",
                answer_format=AnswerFormat.JSON_OBJECT,
            )
        )
        value = ActionTaskOutput.json(
            _task_result, execution, subject="Workspace analyze LLM task"
        )
        if isinstance(value, ActionResult):
            return value
        if set(value) != {"answer", "source_ids"}:
            return _failed(
                execution,
                "workspace.analyze LLM output must contain only answer and source_ids.",
                {"reason": "invalid_analysis_output"},
            )
        answer = value.get("answer")
        source_ids_value = value.get("source_ids")
        if not isinstance(answer, str) or not answer.strip():
            return _failed(
                execution,
                "workspace.analyze LLM output requires a non-empty answer.",
                {"reason": "invalid_analysis_answer"},
            )
        if len(answer) > settings.max_answer_chars:
            return _failed(
                execution,
                "workspace.analyze LLM answer exceeds its size limit.",
                {
                    "reason": "analysis_answer_chars_exceeded",
                    "limit": settings.max_answer_chars,
                    "observed": len(answer),
                },
            )
        if (
            not isinstance(source_ids_value, list)
            or not source_ids_value
            or any(
                not isinstance(source_id, str) or not source_id
                for source_id in source_ids_value
            )
        ):
            return _failed(
                execution,
                "workspace.analyze source_ids must be a non-empty string array.",
                {"reason": "invalid_analysis_source_ids"},
            )
        source_ids = tuple(
            source_id for source_id in source_ids_value if isinstance(source_id, str)
        )
        by_id = {
            reference.source_id: reference for reference in analysis_input.references
        }
        if len(set(source_ids)) != len(source_ids) or any(
            source_id not in by_id for source_id in source_ids
        ):
            return _failed(
                execution,
                "workspace.analyze source_ids must uniquely reference supplied sources.",
                {"reason": "unknown_analysis_source_ids"},
            )
        sources: list[JsonObject] = []
        for source_id in source_ids:
            reference = by_id[source_id]
            sources.append(
                {
                    "source_id": source_id,
                    "link": reference.link,
                    "size": reference.size,
                    "range": {"start_line": 1, "end_line": reference.end_line},
                }
            )
        payload = to_json_object(
            {
                "intent": intent.strip(),
                "answer": answer.strip(),
                "sources": sources,
                "coverage": {
                    "complete": True,
                    "files_loaded": len(analysis_input.references),
                    "source_chars": analysis_input.total_chars,
                },
            }
        )
        return _success(execution, payload)


def _analysis_budget_payload(failure: WorkspaceAnalysisBudgetFailure) -> JsonObject:
    return {
        "reason": failure.reason.value,
        "limit": failure.limit,
        "observed_at_least": failure.observed,
        "offending_link": failure.offending_link,
        "references": [
            {
                "link": record.link,
                "size": record.size,
            }
            for record in failure.inspected
        ],
        "hint": (
            "Reduce reference_links or inspect relevant ranges with "
            "workspace.read/workspace.search."
        ),
    }
