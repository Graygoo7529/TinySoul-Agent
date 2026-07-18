"""Workspace action handlers."""

from __future__ import annotations

from typing import Protocol

from tinysoul.action.backends.llm_action import LLMActionTaskRunner
from tinysoul.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
    ActionResult,
    ActionResultStage,
    ActionTraceProjection,
)
from tinysoul.context import (
    PromptReferenceError,
)
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.runtime import RuntimeException, SignalBus

from .engine import (
    WorkspaceAnalysisBudgetFailure,
    WorkspaceEngine,
    WorkspaceTextRangeResult,
)
from .errors import (
    WorkspaceContractError,
    WorkspaceError,
    WorkspaceTrashRestoreRequired,
)
from .manifest import WorkspaceResourceRecord, WorkspaceRetention
from .prompts import (
    WorkspaceAnalysisPromptBuilder,
    WorkspaceEditPromptBuilder,
)
from .projection import workspace_snapshot_signal
from .search import WorkspaceSearchScope, WorkspaceSearchScopeKind
from .text import WorkspaceTextPosition


WORKSPACE_REWRITE_ACTION = "workspace.rewrite"


class WorkspaceActionRuntimeBridge(Protocol):
    def trash_restore_required(self, *, link: str, trash_ref: str) -> RuntimeException:
        ...

class WorkspaceScanExecutor(ActionExecutor):
    """Scan workspace resources and sync their summaries into WorkingContext."""

    def __init__(self, workspace: WorkspaceEngine, bus: SignalBus) -> None:
        self._workspace = workspace
        self._bus = bus

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        scan = self._workspace.reconcile()
        if not scan.complete:
            skip_counts: JsonObject = {}
            for kind, count in scan.skip_counts().items():
                skip_counts[kind] = count
            return _failed(
                execution,
                "Workspace scan was incomplete; the existing manifest was preserved.",
                {
                    "reason": "incomplete_reconciliation",
                    "skipped_count": scan.skipped_count,
                    "skip_counts": skip_counts,
                    "limit_reached": scan.limit_reached,
                },
            )
        _emit_workspace_snapshot(
            self._workspace,
            execution=execution,
            context=context,
            bus=self._bus,
            source="workspace.scan",
        )
        skip_counts: JsonObject = {}
        for kind, count in scan.skip_counts().items():
            skip_counts[kind] = count
        return _success(
            execution,
            {
                "count": len(scan.manifest.resources),
                "resources": [
                    {"link": record.link, "summary": record.summary}
                    for record in scan.manifest.resources
                ],
                "skipped_count": scan.skipped_count,
                "skip_counts": skip_counts,
                "limit_reached": scan.limit_reached,
            },
        )


def register_workspace_actions(
    builder: ActionEngineBuilder,
    *,
    workspace: WorkspaceEngine,
    bus: SignalBus,
    llm_action: LLMActionTaskRunner,
    runtime_bridge: WorkspaceActionRuntimeBridge | None = None,
) -> ActionEngineBuilder:
    """Register workspace action executors on an action builder."""

    result = (
        builder.register_executor(
            "workspace.read",
            WorkspaceReadExecutor(workspace, runtime_bridge=runtime_bridge),
        )
        .register_executor(
            "workspace.search_text",
            WorkspaceSearchTextExecutor(workspace, runtime_bridge=runtime_bridge),
        )
        .register_executor(
            "workspace.analyze",
            WorkspaceAnalyzeExecutor(
                workspace=workspace,
                llm_action=llm_action,
                runtime_bridge=runtime_bridge,
            ),
        )
        .register_executor("workspace.scan", WorkspaceScanExecutor(workspace, bus))
        .register_executor(
            "workspace.describe",
            WorkspaceDescribeExecutor(
                workspace,
                bus,
                llm_action,
                runtime_bridge=runtime_bridge,
            ),
        )
        .register_executor(
            "workspace.write",
            WorkspaceWriteExecutor(
                workspace=workspace,
                bus=bus,
                llm_action=llm_action,
                runtime_bridge=runtime_bridge,
            ),
        )
        .register_executor(
            "workspace.patch",
            WorkspacePatchExecutor(
                workspace,
                bus,
                runtime_bridge=runtime_bridge,
            ),
        )
        .register_executor(
            "workspace.delete",
            WorkspaceDeleteExecutor(workspace, bus),
        )
        .register_executor(
            "workspace.restore",
            WorkspaceRestoreExecutor(workspace, bus),
        )
        .register_executor(
            "workspace.trash.list",
            WorkspaceTrashListExecutor(workspace),
        )
    )
    return result.register_executor(
        WORKSPACE_REWRITE_ACTION,
        WorkspaceRewriteExecutor(
            workspace=workspace,
            bus=bus,
            llm_action=llm_action,
            runtime_bridge=runtime_bridge,
        ),
    )


class WorkspaceReadExecutor(ActionExecutor):
    """Return one bounded, digest-bound Workspace text range."""

    def __init__(
        self,
        workspace: WorkspaceEngine,
        *,
        runtime_bridge: WorkspaceActionRuntimeBridge | None = None,
    ) -> None:
        self._workspace = workspace
        self._runtime_bridge = runtime_bridge

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        params = execution.call.params
        link = params.get("link")
        start_line = params.get("start_line")
        end_line = params.get("end_line")
        cursor = params.get("cursor", 0)
        max_chars = params.get("max_chars")
        expected_digest = params.get("expected_digest")
        if not isinstance(link, str) or not link:
            return _failed(
                execution,
                "workspace.read requires a non-empty 'link' parameter.",
                {"reason": "missing_link"},
            )
        if isinstance(start_line, bool) or not isinstance(start_line, int):
            return _failed(
                execution,
                "workspace.read start_line must be an integer.",
                {"reason": "invalid_start_line"},
            )
        if isinstance(end_line, bool) or not isinstance(end_line, int):
            return _failed(
                execution,
                "workspace.read end_line must be an integer.",
                {"reason": "invalid_end_line"},
            )
        if isinstance(cursor, bool) or not isinstance(cursor, int):
            return _failed(
                execution,
                "workspace.read cursor must be an integer.",
                {"reason": "invalid_cursor"},
            )
        if max_chars is not None and (
            isinstance(max_chars, bool) or not isinstance(max_chars, int)
        ):
            return _failed(
                execution,
                "workspace.read max_chars must be an integer when provided.",
                {"reason": "invalid_max_chars"},
            )
        if expected_digest is not None and not isinstance(expected_digest, str):
            return _failed(
                execution,
                "workspace.read expected_digest must be a string when provided.",
                {"reason": "invalid_expected_digest"},
            )
        try:
            result = self._workspace.read_text_range(
                link,
                start_line=start_line,
                end_line=end_line,
                cursor=cursor,
                max_chars=max_chars if isinstance(max_chars, int) else None,
                expected_digest=(
                    expected_digest if isinstance(expected_digest, str) else None
                ),
            )
        except WorkspaceTrashRestoreRequired as exc:
            if self._runtime_bridge is None:
                raise
            raise self._runtime_bridge.trash_restore_required(
                link=exc.link,
                trash_ref=exc.trash_ref,
            ) from exc
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace read failed: {exc}",
                {"reason": "workspace_read_failed", "error_type": type(exc).__name__},
            )
        payload = _text_range_payload(result)
        compact_payload = {key: value for key, value in payload.items() if key != "text"}
        compact_payload["folded"] = True
        return _success(
            execution,
            payload,
            trace_projection=ActionTraceProjection(
                origin_refs=(result.link,),
                compact_payload=compact_payload,
            ),
        )


class WorkspaceSearchTextExecutor(ActionExecutor):
    """Search an explicit Workspace text scope for one literal query."""

    def __init__(
        self,
        workspace: WorkspaceEngine,
        *,
        runtime_bridge: WorkspaceActionRuntimeBridge | None = None,
    ) -> None:
        self._workspace = workspace
        self._runtime_bridge = runtime_bridge

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        query = execution.call.params.get("query")
        if not isinstance(query, str) or not query:
            return _failed(
                execution,
                "workspace.search_text requires a non-empty 'query' parameter.",
                {"reason": "invalid_query"},
            )
        try:
            scope = _search_scope(execution.call.params.get("scope"))
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace text search scope is invalid: {exc}",
                {"reason": "invalid_scope", "error_type": type(exc).__name__},
            )
        case_sensitive = execution.call.params.get("case_sensitive", False)
        if not isinstance(case_sensitive, bool):
            return _failed(
                execution,
                "workspace.search_text case_sensitive must be boolean.",
                {"reason": "invalid_case_sensitive"},
            )
        top_k = execution.call.params.get("top_k")
        if top_k is not None and (
            isinstance(top_k, bool) or not isinstance(top_k, int)
        ):
            return _failed(
                execution,
                "workspace.search_text top_k must be an integer when provided.",
                {"reason": "invalid_top_k"},
            )
        try:
            result = self._workspace.search_text(
                query,
                scope=scope,
                case_sensitive=case_sensitive,
                top_k=top_k if isinstance(top_k, int) else None,
            )
        except WorkspaceTrashRestoreRequired as exc:
            if self._runtime_bridge is None:
                raise
            raise self._runtime_bridge.trash_restore_required(
                link=exc.link,
                trash_ref=exc.trash_ref,
            ) from exc
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace text search failed: {exc}",
                {"reason": "workspace_search_failed", "error_type": type(exc).__name__},
            )
        payload = result.to_json()
        compact_payload = result.to_json(include_text=False)
        compact_payload["folded"] = True
        origin_refs = tuple(
            dict.fromkeys(
                [
                    *(fragment.link for fragment in result.fragments),
                    *(hint.link for hint in result.line_hints),
                ]
            )
        )
        return _success(
            execution,
            payload,
            trace_projection=ActionTraceProjection(
                origin_refs=origin_refs,
                compact_payload=compact_payload,
            ),
        )


class WorkspaceAnalyzeExecutor(ActionExecutor):
    """Analyze explicit complete Workspace text references without mutation."""

    def __init__(
        self,
        *,
        workspace: WorkspaceEngine,
        llm_action: LLMActionTaskRunner,
        runtime_bridge: WorkspaceActionRuntimeBridge | None = None,
    ) -> None:
        self._workspace = workspace
        self._llm_action = llm_action
        self._runtime_bridge = runtime_bridge
        self._prompt_builder = WorkspaceAnalysisPromptBuilder()

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        intent = execution.call.params.get("intent")
        if not isinstance(intent, str) or not intent.strip():
            return _failed(
                execution,
                "workspace.analyze requires a non-empty 'intent' parameter.",
                {"reason": "invalid_intent"},
            )
        settings = self._workspace.settings.analysis
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
        if not isinstance(links_value, list) or not links_value or any(
            not isinstance(link, str) or not link for link in links_value
        ):
            return _failed(
                execution,
                "workspace.analyze reference_links must be a non-empty string array.",
                {"reason": "invalid_reference_links"},
            )
        links = tuple(link for link in links_value if isinstance(link, str))
        try:
            preparation = self._workspace.prepare_analysis_references(links)
        except WorkspaceTrashRestoreRequired as exc:
            if self._runtime_bridge is None:
                raise
            raise self._runtime_bridge.trash_restore_required(
                link=exc.link,
                trash_ref=exc.trash_ref,
            ) from exc
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace analysis preparation failed: {exc}",
                {
                    "reason": "workspace_analysis_preparation_failed",
                    "error_type": type(exc).__name__,
                },
            )
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
        value = self._llm_action.run_json(
            execution=execution,
            prompt=prompt,
            subject="Workspace analyze LLM task",
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
        if not isinstance(source_ids_value, list) or not source_ids_value or any(
            not isinstance(source_id, str) or not source_id
            for source_id in source_ids_value
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
            reference.source_id: reference
            for reference in analysis_input.references
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
                    "digest": reference.digest,
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


class WorkspaceDescribeExecutor(ActionExecutor):
    """Generate a digest-bound semantic description for one resource."""

    def __init__(
        self,
        workspace: WorkspaceEngine,
        bus: SignalBus,
        llm_action: LLMActionTaskRunner,
        runtime_bridge: WorkspaceActionRuntimeBridge | None = None,
    ) -> None:
        self._workspace = workspace
        self._bus = bus
        self._llm_action = llm_action
        self._runtime_bridge = runtime_bridge
        self._prompt_builder = WorkspaceEditPromptBuilder(
            workspace,
            runtime_bridge=self._runtime_bridge,
        )

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        target_link = _required_link(execution)
        if target_link is None:
            return _failed(
                execution,
                "workspace.describe requires a non-empty 'target_link' parameter.",
                {"reason": "missing_target_link"},
            )
        instruction = execution.call.params.get("instruction", "")
        if not isinstance(instruction, str):
            return _failed(
                execution,
                "workspace.describe instruction must be a string when provided.",
                {"reason": "invalid_instruction"},
            )
        try:
            prompt_build = self._prompt_builder.build_describe(
                target_link=target_link,
                instruction=instruction,
            )
        except PromptReferenceError as exc:
            return _failed(
                execution,
                str(exc),
                {**exc.payload, "reason": exc.reason},
            )
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace describe failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        payload = self._llm_action.run_json(
            execution=execution,
            prompt=prompt_build.prompt,
            subject="Workspace describe LLM task",
        )
        if isinstance(payload, ActionResult):
            return payload
        description = payload.get("description")
        if not isinstance(description, str) or not description.strip():
            return _failed(
                execution,
                "Workspace describe LLM task must return a non-empty description.",
                {"reason": "invalid_description"},
            )
        try:
            record = self._workspace.set_description(
                target_link,
                description,
                expected_digest=prompt_build.target_digest,
            )
        except WorkspaceTrashRestoreRequired as exc:
            if self._runtime_bridge is None:
                raise
            raise self._runtime_bridge.trash_restore_required(
                link=exc.link,
                trash_ref=exc.trash_ref,
            ) from exc
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace describe failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        _emit_workspace_snapshot(
            self._workspace,
            execution=execution,
            context=context,
            bus=self._bus,
            source="workspace.describe",
        )
        return _success(execution, _record_payload(record))


class WorkspaceWriteExecutor(ActionExecutor):
    """Generate and write one workspace text resource through an internal LLM task."""

    def __init__(
        self,
        *,
        workspace: WorkspaceEngine,
        bus: SignalBus,
        llm_action: LLMActionTaskRunner,
        runtime_bridge: WorkspaceActionRuntimeBridge | None = None,
    ) -> None:
        self._workspace = workspace
        self._bus = bus
        self._llm_action = llm_action
        self._runtime_bridge = runtime_bridge
        self._prompt_builder = WorkspaceEditPromptBuilder(
            workspace,
            runtime_bridge=self._runtime_bridge,
        )

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        target_link = _required_link(execution)
        if target_link is None:
            return _failed(
                execution,
                "workspace.write requires a non-empty 'target_link' parameter.",
                {"reason": "missing_target_link"},
            )
        instruction = execution.call.params.get("instruction")
        if not isinstance(instruction, str) or not instruction:
            return _failed(
                execution,
                "workspace.write requires a non-empty 'instruction' string parameter.",
                {"reason": "invalid_instruction"},
            )
        overwrite = execution.call.params.get("overwrite", False)
        if not isinstance(overwrite, bool):
            return _failed(
                execution,
                "workspace.write overwrite must be a boolean when provided.",
                {"reason": "invalid_overwrite"},
            )
        expected_digest = execution.call.params.get("expected_digest", "")
        if not isinstance(expected_digest, str):
            return _failed(
                execution,
                "workspace.write expected_digest must be a string when provided.",
                {"reason": "invalid_expected_digest"},
            )
        retention_value = execution.call.params.get("retention")
        retention = None
        if retention_value is not None:
            try:
                retention = WorkspaceRetention(retention_value)
            except (TypeError, ValueError):
                return _failed(
                    execution,
                    "workspace.write retention must be ephemeral, turn, day, or persistent.",
                    {"reason": "invalid_retention"},
                )
        reference_links = _string_list_param(
            execution.call.params.get("reference_links", []),
        )
        if reference_links is None:
            return _failed(
                execution,
                "workspace.write reference_links must be a list of strings.",
                {"reason": "invalid_reference_links"},
            )
        try:
            target_exists = self._workspace.write_target_exists(target_link)
            if target_exists and not overwrite:
                return _failed(
                    execution,
                    f"Workspace write target already exists: {target_link}",
                    {"reason": "target_exists", "link": target_link},
                )
            prompt_build = self._prompt_builder.build_write(
                target_link=target_link,
                instruction=instruction,
                reference_links=reference_links,
                include_target=target_exists,
                overwrite=overwrite,
            )
            if expected_digest:
                if not target_exists:
                    return _failed(
                        execution,
                        f"Workspace write target does not exist for digest check: {target_link}",
                        {"reason": "missing_digest_target", "link": target_link},
                    )
                if prompt_build.target_digest != expected_digest:
                    return _failed(
                        execution,
                        f"Workspace write target digest mismatch: {target_link}",
                        {"reason": "digest_mismatch", "link": target_link},
                    )
        except PromptReferenceError as exc:
            return _failed(
                execution,
                str(exc),
                {**exc.payload, "reason": exc.reason},
            )
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace write failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        payload = self._llm_action.run_json(
            execution=execution,
            prompt=prompt_build.prompt,
            subject="Workspace write LLM task",
        )
        if isinstance(payload, ActionResult):
            return payload
        text = payload.get("text")
        if not isinstance(text, str):
            return _failed(
                execution,
                "Workspace write LLM task must return a JSON object with string field 'text'.",
                {"reason": "invalid_write_text"},
            )
        try:
            record = self._workspace.write_text(
                target_link,
                text,
                overwrite=overwrite,
                expected_digest=expected_digest or prompt_build.target_digest,
                retention=retention,
                owner_turn_id=execution.framework.turn_id,
            )
        except WorkspaceTrashRestoreRequired as exc:
            if self._runtime_bridge is None:
                raise
            raise self._runtime_bridge.trash_restore_required(
                link=exc.link,
                trash_ref=exc.trash_ref,
            ) from exc
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace write failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        _emit_workspace_snapshot(
            self._workspace,
            execution=execution,
            context=context,
            bus=self._bus,
            source="workspace.write",
        )
        result_payload = _record_payload(record)
        result_payload["written"] = True
        return _success(execution, result_payload)

class WorkspacePatchExecutor(ActionExecutor):
    """Apply an exact text replacement to one workspace resource."""

    def __init__(
        self,
        workspace: WorkspaceEngine,
        bus: SignalBus,
        *,
        runtime_bridge: WorkspaceActionRuntimeBridge | None = None,
    ) -> None:
        self._workspace = workspace
        self._bus = bus
        self._runtime_bridge = runtime_bridge

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        link = _required_link(execution)
        if link is None:
            return _failed(
                execution,
                "workspace.patch requires a non-empty 'target_link' parameter.",
                {"reason": "missing_target_link"},
            )
        old_text = execution.call.params.get("old_text")
        if not isinstance(old_text, str) or not old_text:
            return _failed(
                execution,
                "workspace.patch requires a non-empty 'old_text' string parameter.",
                {"reason": "invalid_old_text"},
            )
        new_text = execution.call.params.get("new_text")
        if not isinstance(new_text, str):
            return _failed(
                execution,
                "workspace.patch requires a 'new_text' string parameter.",
                {"reason": "invalid_new_text"},
            )
        expected_digest = execution.call.params.get("expected_digest", "")
        if not isinstance(expected_digest, str):
            return _failed(
                execution,
                "workspace.patch expected_digest must be a string when provided.",
                {"reason": "invalid_expected_digest"},
            )
        try:
            record = self._workspace.patch_text(
                link,
                old_text=old_text,
                new_text=new_text,
                expected_digest=expected_digest,
            )
        except WorkspaceTrashRestoreRequired as exc:
            if self._runtime_bridge is None:
                raise
            raise self._runtime_bridge.trash_restore_required(
                link=exc.link,
                trash_ref=exc.trash_ref,
            ) from exc
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace patch failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        _emit_workspace_snapshot(
            self._workspace,
            execution=execution,
            context=context,
            bus=self._bus,
            source="workspace.patch",
        )
        return _success(execution, _record_payload(record))


class WorkspaceDeleteExecutor(ActionExecutor):
    """Move one resource to recoverable Trash and remove its active summary."""

    def __init__(self, workspace: WorkspaceEngine, bus: SignalBus) -> None:
        self._workspace = workspace
        self._bus = bus

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        link = _required_link(execution)
        if link is None:
            return _failed(
                execution,
                "workspace.delete requires a non-empty 'target_link' parameter.",
                {"reason": "missing_target_link"},
            )
        try:
            item = self._workspace.trash_resource(
                link,
                reason="workspace.delete",
                source_turn_id=execution.framework.turn_id,
            )
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace delete failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        _emit_workspace_snapshot(
            self._workspace,
            execution=execution,
            context=context,
            bus=self._bus,
            source="workspace.delete",
        )
        payload = _record_payload(item.original)
        payload["deleted"] = True
        payload["trashed"] = True
        payload["trash_ref"] = item.ref
        return _success(execution, payload)


class WorkspaceRestoreExecutor(ActionExecutor):
    """Restore one logically deleted resource from Workspace Trash."""

    def __init__(self, workspace: WorkspaceEngine, bus: SignalBus) -> None:
        self._workspace = workspace
        self._bus = bus

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        trash_ref = execution.call.params.get("trash_ref")
        if not isinstance(trash_ref, str) or not trash_ref:
            return _failed(
                execution,
                "workspace.restore requires a non-empty 'trash_ref' parameter.",
                {"reason": "missing_trash_ref"},
            )
        try:
            record = self._workspace.restore_resource(trash_ref)
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace restore failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        _emit_workspace_snapshot(
            self._workspace,
            execution=execution,
            context=context,
            bus=self._bus,
            source="workspace.restore",
        )
        payload = _record_payload(record)
        payload["restored"] = True
        payload["trash_ref"] = trash_ref
        return _success(execution, payload)


class WorkspaceTrashListExecutor(ActionExecutor):
    """List recoverable Workspace Trash items without exposing file content."""

    def __init__(self, workspace: WorkspaceEngine) -> None:
        self._workspace = workspace

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        try:
            items = self._workspace.trash_items()
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace Trash listing failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        return _success(
            execution,
            {
                "items": [
                    {
                        "trash_ref": item.ref,
                        "link": item.original.link,
                        "summary": item.original.context_summary,
                        "reason": item.reason,
                        "source_turn_id": item.source_turn_id,
                        "trashed_at": item.trashed_at,
                    }
                    for item in items
                ]
            },
        )


class WorkspaceRewriteExecutor(ActionExecutor):
    """Rewrite a workspace text resource through an internal LLM task."""

    def __init__(
        self,
        *,
        workspace: WorkspaceEngine,
        bus: SignalBus,
        llm_action: LLMActionTaskRunner,
        runtime_bridge: WorkspaceActionRuntimeBridge | None = None,
    ) -> None:
        self._workspace = workspace
        self._bus = bus
        self._llm_action = llm_action
        self._runtime_bridge = runtime_bridge
        self._prompt_builder = WorkspaceEditPromptBuilder(
            workspace,
            runtime_bridge=self._runtime_bridge,
        )

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        target_link = _required_link(execution)
        if target_link is None:
            return _failed(
                execution,
                "workspace.rewrite requires a non-empty 'target_link' parameter.",
                {"reason": "missing_target_link"},
            )
        instruction = execution.call.params.get("instruction")
        if not isinstance(instruction, str) or not instruction:
            return _failed(
                execution,
                "workspace.rewrite requires a non-empty 'instruction' string parameter.",
                {"reason": "invalid_instruction"},
            )
        expected_digest = execution.call.params.get("expected_digest", "")
        if not isinstance(expected_digest, str):
            return _failed(
                execution,
                "workspace.rewrite expected_digest must be a string when provided.",
                {"reason": "invalid_expected_digest"},
            )
        reference_links = _string_list_param(
            execution.call.params.get("reference_links", []),
        )
        if reference_links is None:
            return _failed(
                execution,
                "workspace.rewrite reference_links must be a list of strings.",
                {"reason": "invalid_reference_links"},
            )
        try:
            prompt_build = self._prompt_builder.build_rewrite(
                target_link=target_link,
                instruction=instruction,
                reference_links=reference_links,
            )
            if expected_digest and prompt_build.target_digest != expected_digest:
                return _failed(
                    execution,
                    f"Workspace rewrite target digest mismatch: {target_link}",
                    {"reason": "digest_mismatch", "link": target_link},
                )
        except PromptReferenceError as exc:
            return _failed(
                execution,
                str(exc),
                {**exc.payload, "reason": exc.reason},
            )
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace rewrite failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        payload = self._llm_action.run_json(
            execution=execution,
            prompt=prompt_build.prompt,
            subject="Workspace rewrite LLM task",
        )
        if isinstance(payload, ActionResult):
            return payload
        text = payload.get("text")
        if not isinstance(text, str):
            return _failed(
                execution,
                "Workspace rewrite LLM task must return a JSON object with string field 'text'.",
                {"reason": "invalid_rewrite_text"},
            )
        try:
            record = self._workspace.write_text(
                target_link,
                text,
                overwrite=True,
                expected_digest=expected_digest or prompt_build.target_digest,
            )
        except WorkspaceTrashRestoreRequired as exc:
            if self._runtime_bridge is None:
                raise
            raise self._runtime_bridge.trash_restore_required(
                link=exc.link,
                trash_ref=exc.trash_ref,
            ) from exc
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace rewrite failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        _emit_workspace_snapshot(
            self._workspace,
            execution=execution,
            context=context,
            bus=self._bus,
            source="workspace.rewrite",
        )
        result_payload = _record_payload(record)
        result_payload["rewritten"] = True
        return _success(execution, result_payload)

def _required_link(execution: ActionExecution) -> str | None:
    link = execution.call.params.get("target_link")
    if not isinstance(link, str) or not link:
        return None
    return link


def _string_list_param(value: object) -> tuple[str, ...] | None:
    if value is None:
        return ()
    if not isinstance(value, list):
        return None
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            return None
        if item not in result:
            result.append(item)
    return tuple(result)


def _emit_workspace_snapshot(
    workspace: WorkspaceEngine,
    *,
    execution: ActionExecution,
    context: ActionExecutionContext,
    bus: SignalBus,
    source: str,
) -> None:
    signal_bus = context.signal_bus or bus
    manifest = workspace.snapshot()
    signal_bus.emit(
        workspace_snapshot_signal(
            manifest,
            call_id=execution.call.call_id,
            scope=execution.framework.scope,
            source=source,
        )
    )


def _record_payload(record: WorkspaceResourceRecord) -> JsonObject:
    return {
        "link": record.link,
        "summary": record.summary,
        "description": record.description,
        "kind": record.kind.value,
        "media_type": record.media_type,
        "size": record.size,
        "mtime_ns": record.mtime_ns,
        "digest": record.digest,
    }


def _success(
    execution: ActionExecution,
    payload: JsonObject,
    *,
    trace_projection: ActionTraceProjection | None = None,
) -> ActionResult:
    return ActionResult.success(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        payload=payload,
        trace_projection=trace_projection,
    )


def _text_range_payload(result: WorkspaceTextRangeResult) -> JsonObject:
    page = result.page
    return {
        "link": result.link,
        "digest": result.digest,
        "size": result.size,
        "requested": {
            "start_line": result.start_line,
            "end_line": result.end_line,
            "cursor": page.cursor,
            "max_chars": result.max_chars,
        },
        "actual": {
            "start": _position_payload(page.actual_start),
            "end": _position_payload(page.actual_end),
        },
        "text": page.text,
        "truncated": page.truncated,
        "truncation_reason": "character_limit" if page.truncated else "",
        "next_cursor": page.next_cursor,
        "next_position": _position_payload(page.next_position),
        "eof_reached": page.eof_reached,
    }


def _position_payload(position: WorkspaceTextPosition | None) -> JsonObject | None:
    if position is None:
        return None
    return {"line": position.line, "column": position.column}


def _search_scope(value: object) -> WorkspaceSearchScope:
    if not isinstance(value, dict):
        raise WorkspaceContractError("Workspace search scope must be an object")
    kind_value = value.get("kind")
    if not isinstance(kind_value, str):
        raise WorkspaceContractError("Workspace search scope requires a kind")
    try:
        kind = WorkspaceSearchScopeKind(kind_value)
    except ValueError as exc:
        raise WorkspaceContractError(
            f"Unknown Workspace search scope kind: {kind_value}"
        ) from exc
    expected_keys = {
        WorkspaceSearchScopeKind.FILE: {"kind", "link"},
        WorkspaceSearchScopeKind.DIRECTORY: {"kind", "prefix"},
        WorkspaceSearchScopeKind.WORKSPACE: {"kind"},
    }[kind]
    if set(value) != expected_keys:
        raise WorkspaceContractError(
            f"Workspace {kind.value} search scope must contain exactly "
            f"{sorted(expected_keys)}"
        )
    if kind is WorkspaceSearchScopeKind.FILE:
        locator = value.get("link")
    elif kind is WorkspaceSearchScopeKind.DIRECTORY:
        locator = value.get("prefix")
    else:
        locator = ""
    if not isinstance(locator, str):
        raise WorkspaceContractError(
            f"Workspace {kind.value} search scope locator must be a string"
        )
    return WorkspaceSearchScope(kind=kind, locator=locator)


def _analysis_budget_payload(failure: WorkspaceAnalysisBudgetFailure) -> JsonObject:
    return {
        "reason": failure.reason.value,
        "limit": failure.limit,
        "observed_at_least": failure.observed,
        "offending_link": failure.offending_link,
        "references": [
            {
                "link": record.link,
                "digest": record.digest,
                "size": record.size,
            }
            for record in failure.inspected
        ],
        "hint": (
            "Reduce reference_links or inspect relevant ranges with "
            "workspace.read/workspace.search_text."
        ),
    }


def _failed(
    execution: ActionExecution,
    model_feedback: str,
    frame_data: JsonObject,
    *,
    payload: JsonObject | None = None,
) -> ActionResult:
    return ActionResult.failed(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        stage=ActionResultStage.EXECUTE,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        model_feedback=model_feedback,
        payload=payload,
        frame_data=frame_data,
    )
