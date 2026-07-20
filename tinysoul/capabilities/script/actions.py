"""ActionEngine integration for Script authoring and supervised execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from tinysoul.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
    ActionResult,
    ActionResultStage,
)
from tinysoul.action.backends import LLMActionTaskRunner
from tinysoul.capabilities.supervised_process import (
    SupervisedProcessManager,
    SupervisedProcessObservation,
    SupervisedProcessOwner,
)
from tinysoul.capabilities.supervised_process.errors import SupervisedProcessError
from tinysoul.context import PromptReferenceError
from tinysoul.home import (
    AgentHomeContractError,
    AgentHomeError,
    AgentHomeRuntimeCopyRequired,
)
from tinysoul.infra import JsonObject
from tinysoul.runtime import RuntimeException, SignalBus
from tinysoul.workspace import (
    WorkspaceEngine,
    WorkspaceContractError,
    WorkspaceError,
    WorkspaceMirrorConflict,
    WorkspacePromptReferenceResolver,
    WorkspaceTrashRestoreRequired,
    workspace_snapshot_signal,
)

from .config import ScriptSettings
from .dependencies import require_script_dependencies
from .errors import ScriptError, ScriptPolicyError
from .models import ScriptLanguage, ScriptMutation, ScriptSource
from .policy import ScriptPolicy
from .process import ScriptProcessPreparer
from .prompts import ScriptEditPromptBuilder
from .sources import ScriptSourceResolver


SCRIPT_ACTIONS = (
    "script.write",
    "script.rewrite",
    "script.patch",
    "script.promote",
    "script.run_python",
    "script.run_bash",
    "script.wait",
    "script.stop",
    "script.read_candidate",
    "script.apply",
    "script.discard",
)


class ScriptHomeRuntimeBridge(Protocol):
    def runtime_copy_required(
        self,
        *,
        link: str,
        message: str = "Agent Home runtime copy is required.",
        payload: JsonObject | None = None,
    ) -> RuntimeException: ...

    def from_home_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException: ...


class ScriptWorkspaceRuntimeBridge(Protocol):
    def trash_restore_required(self, *, link: str, trash_ref: str) -> RuntimeException: ...

    def from_workspace_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException: ...


@dataclass(frozen=True)
class _AuthoringParams:
    target_link: str
    instruction: str
    reference_links: tuple[str, ...]
    expected_digest: str
    overwrite: bool


class ScriptAuthoringExecutor(ActionExecutor):
    """Create or rewrite one complete Script source through an internal LLM task."""

    def __init__(
        self,
        *,
        mode: str,
        resolver: ScriptSourceResolver,
        policy: ScriptPolicy,
        prompts: ScriptEditPromptBuilder,
        llm_action: LLMActionTaskRunner,
        workspace: WorkspaceEngine,
        bus: SignalBus,
        home_bridge: ScriptHomeRuntimeBridge | None,
        workspace_bridge: ScriptWorkspaceRuntimeBridge | None,
    ) -> None:
        self._mode = mode
        self._resolver = resolver
        self._policy = policy
        self._prompts = prompts
        self._llm_action = llm_action
        self._workspace = workspace
        self._bus = bus
        self._home_bridge = home_bridge
        self._workspace_bridge = workspace_bridge

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        params = _authoring_params(execution, rewrite=self._mode == "rewrite")
        if isinstance(params, ActionResult):
            return params
        try:
            language = self._resolver.validate_link(params.target_link)
            existing: ScriptSource | None = None
            if self._mode == "rewrite" or params.overwrite:
                existing = self._resolver.read(params.target_link)
                if params.expected_digest and existing.digest != params.expected_digest:
                    return _failed(
                        execution,
                        "Script target digest mismatch.",
                        {"reason": "digest_mismatch", "link": params.target_link},
                    )
            if self._mode == "rewrite":
                if existing is None:
                    raise ScriptError("Script rewrite target disappeared")
                prompt = self._prompts.build_rewrite(
                    source=existing,
                    instruction=params.instruction,
                    reference_links=params.reference_links,
                )
            else:
                prompt = self._prompts.build_write(
                    target_link=params.target_link,
                    instruction=params.instruction,
                    reference_links=params.reference_links,
                    existing=existing,
                )
        except Exception as exc:
            mapped = self._source_failure(execution, exc)
            if mapped is not None:
                return mapped
            raise
        payload = self._llm_action.run_json(
            execution=execution,
            prompt=prompt,
            subject=f"Script {self._mode} LLM task",
            control=context.control,
        )
        if isinstance(payload, ActionResult):
            return payload
        text = payload.get("text")
        if not isinstance(text, str):
            return _failed(
                execution,
                "Script authoring task must return a JSON string field named 'text'.",
                {"reason": "invalid_script_source"},
            )
        try:
            source = ScriptSource(params.target_link, text, "", language)
            self._policy.validate(source)
            mutation = self._resolver.write(
                params.target_link,
                text,
                overwrite=self._mode == "rewrite" or params.overwrite,
                expected_digest=(
                    params.expected_digest
                    or (existing.digest if existing is not None else "")
                ),
                owner_turn_id=execution.framework.turn_id,
            )
        except Exception as exc:
            mapped = self._source_failure(execution, exc)
            if mapped is not None:
                return mapped
            raise
        if mutation.link.startswith("workspace:"):
            _emit_workspace(self._workspace, self._bus, execution, context)
        return _success(execution, _mutation_payload(mutation, language))

    def _source_failure(
        self,
        execution: ActionExecution,
        exc: Exception,
    ) -> ActionResult | None:
        if isinstance(exc, AgentHomeRuntimeCopyRequired):
            if self._home_bridge is None:
                return None
            raise self._home_bridge.runtime_copy_required(
                link=exc.link,
                payload=exc.to_payload(),
            ) from exc
        if isinstance(exc, WorkspaceTrashRestoreRequired):
            if self._workspace_bridge is None:
                return None
            raise self._workspace_bridge.trash_restore_required(
                link=exc.link,
                trash_ref=exc.trash_ref,
            ) from exc
        if isinstance(exc, PromptReferenceError):
            return _failed(execution, str(exc), {**exc.payload, "reason": exc.reason})
        if isinstance(exc, ScriptPolicyError):
            return _failed(execution, str(exc), {"reason": "script_policy_rejected"})
        if isinstance(exc, (ScriptError, AgentHomeContractError, WorkspaceContractError)):
            return _failed(
                execution,
                "Script source could not be written.",
                {"reason": "script_source_failed", "error_type": type(exc).__name__},
            )
        _raise_owner_error(
            exc,
            home_bridge=self._home_bridge,
            workspace_bridge=self._workspace_bridge,
        )
        return None


class ScriptPatchExecutor(ActionExecutor):
    def __init__(
        self,
        *,
        resolver: ScriptSourceResolver,
        policy: ScriptPolicy,
        workspace: WorkspaceEngine,
        bus: SignalBus,
        home_bridge: ScriptHomeRuntimeBridge | None,
        workspace_bridge: ScriptWorkspaceRuntimeBridge | None,
    ) -> None:
        self._resolver = resolver
        self._policy = policy
        self._workspace = workspace
        self._bus = bus
        self._home_bridge = home_bridge
        self._workspace_bridge = workspace_bridge

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        target = _required_text(execution, "target_link")
        old_text = _required_text(execution, "old_text")
        new_text = execution.call.params.get("new_text")
        expected = execution.call.params.get("expected_digest", "")
        if target is None or old_text is None or not isinstance(new_text, str):
            return _failed(
                execution,
                "Script patch parameters are invalid.",
                {"reason": "invalid_patch"},
            )
        if not isinstance(expected, str):
            return _failed(
                execution,
                "Script expected_digest must be text.",
                {"reason": "invalid_digest"},
            )
        try:
            current = self._resolver.read(target)
            if expected and current.digest != expected:
                return _failed(
                    execution,
                    "Script target digest mismatch.",
                    {"reason": "digest_mismatch"},
                )
            if current.text.count(old_text) != 1:
                return _failed(
                    execution,
                    "Script patch old_text must occur exactly once.",
                    {"reason": "ambiguous_patch"},
                )
            candidate = ScriptSource(
                current.link,
                current.text.replace(old_text, new_text, 1),
                current.digest,
                current.language,
            )
            self._policy.validate(candidate)
            mutation = self._resolver.patch(
                current,
                old_text=old_text,
                new_text=new_text,
            )
        except AgentHomeRuntimeCopyRequired as exc:
            if self._home_bridge is None:
                raise
            raise self._home_bridge.runtime_copy_required(
                link=exc.link,
                payload=exc.to_payload(),
            ) from exc
        except WorkspaceTrashRestoreRequired as exc:
            if self._workspace_bridge is None:
                raise
            raise self._workspace_bridge.trash_restore_required(
                link=exc.link,
                trash_ref=exc.trash_ref,
            ) from exc
        except (ScriptError, AgentHomeContractError, WorkspaceContractError) as exc:
            return _failed(
                execution,
                "Script patch failed.",
                {"reason": "script_patch_failed", "error_type": type(exc).__name__},
            )
        except AgentHomeError as exc:
            _raise_home_error(exc, self._home_bridge)
        except WorkspaceError as exc:
            _raise_workspace_error(exc, self._workspace_bridge)
        if mutation.link.startswith("workspace:"):
            _emit_workspace(self._workspace, self._bus, execution, context)
        return _success(execution, _mutation_payload(mutation, current.language))


class ScriptPromoteExecutor(ActionExecutor):
    def __init__(
        self,
        *,
        resolver: ScriptSourceResolver,
        policy: ScriptPolicy,
        home_bridge: ScriptHomeRuntimeBridge | None,
        workspace_bridge: ScriptWorkspaceRuntimeBridge | None,
    ) -> None:
        self._resolver = resolver
        self._policy = policy
        self._home_bridge = home_bridge
        self._workspace_bridge = workspace_bridge

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        del context
        source = _required_text(execution, "source_link")
        target = _required_text(execution, "target_link")
        expected_source = execution.call.params.get("expected_source_digest", "")
        expected_target = execution.call.params.get("expected_target_digest", "")
        overwrite = execution.call.params.get("overwrite", False)
        if source is None or target is None or not isinstance(overwrite, bool):
            return _failed(
                execution,
                "Script promote parameters are invalid.",
                {"reason": "invalid_promote"},
            )
        if not isinstance(expected_source, str) or not isinstance(expected_target, str):
            return _failed(
                execution,
                "Script promote digest guards must be text.",
                {"reason": "invalid_digest"},
            )
        try:
            source_snapshot = self._resolver.read(source)
            self._policy.validate(source_snapshot)
            mutation = self._resolver.promote(
                source_snapshot,
                target,
                expected_source_digest=expected_source,
                overwrite=overwrite,
                expected_target_digest=expected_target,
            )
        except AgentHomeRuntimeCopyRequired as exc:
            if self._home_bridge is None:
                raise
            raise self._home_bridge.runtime_copy_required(
                link=exc.link,
                payload=exc.to_payload(),
            ) from exc
        except WorkspaceTrashRestoreRequired as exc:
            if self._workspace_bridge is None:
                raise
            raise self._workspace_bridge.trash_restore_required(
                link=exc.link,
                trash_ref=exc.trash_ref,
            ) from exc
        except (ScriptError, AgentHomeContractError, WorkspaceContractError) as exc:
            return _failed(
                execution,
                "Script promote failed.",
                {"reason": "script_promote_failed", "error_type": type(exc).__name__},
            )
        except AgentHomeError as exc:
            _raise_home_error(exc, self._home_bridge)
        except WorkspaceError as exc:
            _raise_workspace_error(exc, self._workspace_bridge)
        return _success(
            execution,
            _mutation_payload(mutation, self._resolver.validate_link(target)),
        )


class ScriptRunExecutor(ActionExecutor):
    def __init__(
        self,
        *,
        language: ScriptLanguage,
        settings: ScriptSettings,
        resolver: ScriptSourceResolver,
        policy: ScriptPolicy,
        jobs: SupervisedProcessManager,
        bus: SignalBus,
        home_bridge: ScriptHomeRuntimeBridge | None,
        workspace_bridge: ScriptWorkspaceRuntimeBridge | None,
    ) -> None:
        self._language = language
        self._settings = settings
        self._resolver = resolver
        self._policy = policy
        self._jobs = jobs
        self._bus = bus
        self._home_bridge = home_bridge
        self._workspace_bridge = workspace_bridge

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        source_link = _required_text(execution, "source_link")
        args = _string_list(execution.call.params.get("args", []))
        if source_link is None or args is None:
            return _failed(
                execution,
                "Script run parameters are invalid.",
                {"reason": "invalid_run"},
            )
        if len(args) > self._settings.max_args or any(
            len(arg) > self._settings.max_arg_chars for arg in args
        ):
            return _failed(
                execution,
                "Script arguments exceed configured boundaries.",
                {"reason": "args_limit"},
            )
        try:
            source = self._resolver.read(source_link, language=self._language)
            self._policy.validate(source)
            observation = self._jobs.start(
                turn_id=execution.framework.turn_id,
                owner=SupervisedProcessOwner.SCRIPT,
                identity={
                    "source_link": source.link,
                    "source_digest": source.digest,
                    "source_snapshot_digest": source.snapshot_digest,
                    "language": source.language.value,
                },
                prepare=ScriptProcessPreparer(
                    source=source,
                    args=args,
                    settings=self._settings,
                ),
                control=context.control,
                bus=context.signal_bus or self._bus,
            )
        except AgentHomeRuntimeCopyRequired as exc:
            if self._home_bridge is None:
                raise
            raise self._home_bridge.runtime_copy_required(
                link=exc.link,
                payload=exc.to_payload(),
            ) from exc
        except WorkspaceTrashRestoreRequired as exc:
            if self._workspace_bridge is None:
                raise
            raise self._workspace_bridge.trash_restore_required(
                link=exc.link,
                trash_ref=exc.trash_ref,
            ) from exc
        except WorkspaceMirrorConflict:
            return _failed(
                execution,
                "Workspace changed while the Script execution mirror was prepared.",
                {"reason": "workspace_mirror_changed"},
            )
        except (
            ScriptError,
            SupervisedProcessError,
            AgentHomeContractError,
            WorkspaceContractError,
        ) as exc:
            return _failed(
                execution,
                "Script execution could not start.",
                {"reason": "script_start_failed", "error_type": type(exc).__name__},
            )
        except AgentHomeError as exc:
            _raise_home_error(exc, self._home_bridge)
        except WorkspaceError as exc:
            _raise_workspace_error(exc, self._workspace_bridge)
        return _observation_result(execution, observation)


class ScriptJobExecutor(ActionExecutor):
    def __init__(
        self,
        *,
        operation: str,
        jobs: SupervisedProcessManager,
        bus: SignalBus,
        workspace_bridge: ScriptWorkspaceRuntimeBridge | None,
    ) -> None:
        self._operation = operation
        self._jobs = jobs
        self._bus = bus
        self._workspace_bridge = workspace_bridge

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        execution_id = _required_text(execution, "execution_id")
        if execution_id is None:
            return _failed(
                execution,
                "Script job action requires execution_id.",
                {"reason": "missing_execution_id"},
            )
        try:
            if self._operation == "wait":
                wait = execution.call.params.get(
                    "wait_seconds",
                    self._jobs.settings.default_wait_seconds,
                )
                if isinstance(wait, bool) or not isinstance(wait, int):
                    return _failed(
                        execution,
                        "Script wait_seconds must be an integer.",
                        {"reason": "invalid_wait"},
                    )
                return _observation_result(
                    execution,
                    self._jobs.wait(
                        turn_id=execution.framework.turn_id,
                        owner=SupervisedProcessOwner.SCRIPT,
                        execution_id=execution_id,
                        wait_seconds=wait,
                        control=context.control,
                        bus=context.signal_bus or self._bus,
                    ),
                )
            if self._operation == "stop":
                return _observation_result(
                    execution,
                    self._jobs.stop(
                        turn_id=execution.framework.turn_id,
                        owner=SupervisedProcessOwner.SCRIPT,
                        execution_id=execution_id,
                    ),
                )
            if self._operation == "read_candidate":
                path = _required_text(execution, "path")
                cursor = execution.call.params.get("cursor", 0)
                max_chars = execution.call.params.get(
                    "max_chars",
                    self._jobs.settings.max_candidate_read_chars,
                )
                if (
                    path is None
                    or isinstance(cursor, bool)
                    or not isinstance(cursor, int)
                    or isinstance(max_chars, bool)
                    or not isinstance(max_chars, int)
                ):
                    return _failed(
                        execution,
                        "Script candidate read parameters are invalid.",
                        {"reason": "invalid_candidate_read"},
                    )
                return _success(
                    execution,
                    self._jobs.read_candidate(
                        turn_id=execution.framework.turn_id,
                        owner=SupervisedProcessOwner.SCRIPT,
                        execution_id=execution_id,
                        path=path,
                        cursor=cursor,
                        max_chars=max_chars,
                    ),
                )
            if self._operation == "apply":
                applied = self._jobs.apply(
                    turn_id=execution.framework.turn_id,
                    owner=SupervisedProcessOwner.SCRIPT,
                    execution_id=execution_id,
                )
                (context.signal_bus or self._bus).emit(
                    workspace_snapshot_signal(
                        applied.manifest,
                        call_id=execution.call.call_id,
                        scope=execution.framework.scope,
                        source="script.apply",
                    )
                )
                return _success(execution, applied.payload)
            if self._operation == "discard":
                return _success(
                    execution,
                    self._jobs.discard(
                        turn_id=execution.framework.turn_id,
                        owner=SupervisedProcessOwner.SCRIPT,
                        execution_id=execution_id,
                    ),
                )
        except WorkspaceMirrorConflict:
            return _failed(
                execution,
                "Script apply conflicts with a concurrently changed Workspace path. "
                "The job remains available for review or discard.",
                {"reason": "workspace_apply_conflict"},
            )
        except (ScriptError, SupervisedProcessError, WorkspaceContractError) as exc:
            return _failed(
                execution,
                "Script job operation failed.",
                {"reason": "script_job_failed", "error_type": type(exc).__name__},
            )
        except WorkspaceError as exc:
            _raise_workspace_error(exc, self._workspace_bridge)
        return _failed(
            execution,
            "Script job operation is unavailable.",
            {"reason": "unknown_job_operation"},
        )


def register_script_actions(
    builder: ActionEngineBuilder,
    *,
    settings: ScriptSettings,
    resolver: ScriptSourceResolver,
    jobs: SupervisedProcessManager,
    workspace: WorkspaceEngine,
    bus: SignalBus,
    llm_action: LLMActionTaskRunner,
    home_bridge: ScriptHomeRuntimeBridge | None = None,
    workspace_bridge: ScriptWorkspaceRuntimeBridge | None = None,
) -> ActionEngineBuilder:
    """Register enabled Script authoring and execution actions."""

    require_script_dependencies(settings)
    if not settings.enabled:
        builder.disable_actions(*SCRIPT_ACTIONS)
        return builder
    policy = ScriptPolicy(max_source_chars=settings.max_source_chars)
    prompts = ScriptEditPromptBuilder(
        WorkspacePromptReferenceResolver(
            workspace,
            runtime_bridge=workspace_bridge,
        )
    )
    for mode in ("write", "rewrite"):
        builder.register_executor(
            f"script.{mode}",
            ScriptAuthoringExecutor(
                mode=mode,
                resolver=resolver,
                policy=policy,
                prompts=prompts,
                llm_action=llm_action,
                workspace=workspace,
                bus=bus,
                home_bridge=home_bridge,
                workspace_bridge=workspace_bridge,
            ),
        )
    builder.register_executor(
        "script.patch",
        ScriptPatchExecutor(
            resolver=resolver,
            policy=policy,
            workspace=workspace,
            bus=bus,
            home_bridge=home_bridge,
            workspace_bridge=workspace_bridge,
        ),
    )
    builder.register_executor(
        "script.promote",
        ScriptPromoteExecutor(
            resolver=resolver,
            policy=policy,
            home_bridge=home_bridge,
            workspace_bridge=workspace_bridge,
        ),
    )
    for language, action_name, enabled in (
        (ScriptLanguage.PYTHON, "script.run_python", settings.python.enabled),
        (ScriptLanguage.BASH, "script.run_bash", settings.bash.enabled),
    ):
        if not enabled:
            builder.disable_actions(action_name)
            continue
        builder.register_executor(
            action_name,
            ScriptRunExecutor(
                language=language,
                settings=settings,
                resolver=resolver,
                policy=policy,
                jobs=jobs,
                bus=bus,
                home_bridge=home_bridge,
                workspace_bridge=workspace_bridge,
            ),
        )
    for operation in ("wait", "stop", "read_candidate", "apply", "discard"):
        builder.register_executor(
            f"script.{operation}",
            ScriptJobExecutor(
                operation=operation,
                jobs=jobs,
                bus=bus,
                workspace_bridge=workspace_bridge,
            ),
        )
    return builder


def _authoring_params(
    execution: ActionExecution,
    *,
    rewrite: bool,
) -> _AuthoringParams | ActionResult:
    target = _required_text(execution, "target_link")
    instruction = _required_text(execution, "instruction")
    references = _string_list(execution.call.params.get("reference_links", []))
    expected = execution.call.params.get("expected_digest", "")
    overwrite = execution.call.params.get("overwrite", False)
    if target is None or instruction is None or references is None:
        return _failed(
            execution,
            "Script authoring parameters are invalid.",
            {"reason": "invalid_authoring"},
        )
    if not isinstance(expected, str) or not isinstance(overwrite, bool):
        return _failed(
            execution,
            "Script authoring guards are invalid.",
            {"reason": "invalid_authoring_guard"},
        )
    return _AuthoringParams(
        target,
        instruction,
        references,
        expected,
        True if rewrite else overwrite,
    )


def _required_text(execution: ActionExecution, name: str) -> str | None:
    value = execution.call.params.get(name)
    return value if isinstance(value, str) and value else None


def _string_list(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        result.append(item)
    return tuple(result)


def _mutation_payload(
    mutation: ScriptMutation,
    language: ScriptLanguage,
) -> JsonObject:
    return {
        "link": mutation.link,
        "digest": mutation.digest,
        "size": mutation.size,
        "state": mutation.state,
        "language": language.value,
    }


def _observation_result(
    execution: ActionExecution,
    observation: SupervisedProcessObservation,
) -> ActionResult:
    if observation.timed_out:
        return ActionResult.timeout(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            model_feedback=(
                "Script job reached a configured timeout and must be discarded."
            ),
            payload=observation.payload,
            frame_data={"reason": "script_job_timeout", "executor_leaked": False},
        )
    if observation.failed:
        return _failed(
            execution,
            "Script process failed. Candidate output remains inspectable but cannot be applied.",
            {"reason": "script_process_failed"},
            payload=observation.payload,
        )
    return _success(execution, observation.payload)


def _emit_workspace(
    workspace: WorkspaceEngine,
    bus: SignalBus,
    execution: ActionExecution,
    context: ActionExecutionContext,
) -> None:
    (context.signal_bus or bus).emit(
        workspace_snapshot_signal(
            workspace.snapshot(),
            call_id=execution.call.call_id,
            scope=execution.framework.scope,
            source=execution.call.action_name,
        )
    )


def _success(execution: ActionExecution, payload: JsonObject) -> ActionResult:
    return ActionResult.success(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        payload=payload,
    )


def _failed(
    execution: ActionExecution,
    feedback: str,
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
        model_feedback=feedback,
        frame_data=frame_data,
        payload=payload,
    )


def _raise_owner_error(
    exc: Exception,
    *,
    home_bridge: ScriptHomeRuntimeBridge | None,
    workspace_bridge: ScriptWorkspaceRuntimeBridge | None,
) -> None:
    if isinstance(exc, AgentHomeError):
        _raise_home_error(exc, home_bridge)
    if isinstance(exc, WorkspaceError):
        _raise_workspace_error(exc, workspace_bridge)


def _raise_home_error(
    exc: AgentHomeError,
    bridge: ScriptHomeRuntimeBridge | None,
) -> None:
    if bridge is None:
        raise exc
    raise bridge.from_home_error(
        exc,
        payload={"capability": "script"},
    ) from exc


def _raise_workspace_error(
    exc: WorkspaceError,
    bridge: ScriptWorkspaceRuntimeBridge | None,
) -> None:
    if bridge is None:
        raise exc
    raise bridge.from_workspace_error(
        exc,
        payload={"capability": "script"},
    ) from exc
