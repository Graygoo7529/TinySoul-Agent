"""Action backend support for nested LLM tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from tinysoul.action.core.call import ActionExecution
from tinysoul.action.core.executor import ActionExecutionControl
from tinysoul.action.core.result import (
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResult,
    ActionResultStage,
)
from tinysoul.action.core.specs import ActionBackendSpec
from tinysoul.context import ContextEngine, PromptBlock, TaskPrompt
from tinysoul.context.errors import ContextError
from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject
from tinysoul.llm.errors import TaskCancelled
from tinysoul.llm.requests import (
    CallSettings,
    ModelContextOverflowPolicy,
    TaskCall,
    TaskCancellation,
    TaskProfile,
)
from tinysoul.llm.responses import (
    AnswerFormat,
    JsonAnswer,
    TaskResult,
    TaskResultStatus,
    TaskFailureReason,
    TextAnswer,
)
from tinysoul.llm.tools import ToolUse
from tinysoul.runtime import CONTEXT_COMPRESSION_REQUIRED, RuntimeException
from tinysoul.runtime.bridge import RuntimeContextBridge


class LLMActionModelRunner(Protocol):
    """LLM runner surface required by action-internal LLM tasks."""

    def run(self, call: TaskCall) -> TaskResult:
        """Run one LLM task."""
        ...


@dataclass(frozen=True)
class ActionSkillGuidance:
    """Skill snippets automatically mounted for one nested LLM action."""

    domain: tuple[str, ...] = ()
    action: tuple[str, ...] = ()


class ActionSkillProvider(Protocol):
    """Provide domain and action skill text for nested LLM tasks."""

    def guidance_for(self, *, domain: str, action_name: str) -> ActionSkillGuidance:
        """Return skill snippets for one action execution."""
        ...


class EmptyActionSkillProvider:
    """Empty action skill provider used before Agent Home is connected."""

    def guidance_for(self, *, domain: str, action_name: str) -> ActionSkillGuidance:
        return ActionSkillGuidance()


@dataclass(frozen=True)
class LLMActionBackendOptions:
    """Validated per-action generation and artifact limits."""

    max_output_tokens: int | None = None
    max_output_chars: int | None = None


class LLMActionBackendOptionsValidator:
    """Validate llm_action backend options while loading the Catalog."""

    def validate(self, backend: ActionBackendSpec, *, key: str) -> None:
        parse_llm_action_options(backend.options, key=key)


_COMPLETION_RESERVE_SECONDS = 5.0


class LLMActionTaskRunner:
    """Run action-internal LLM tasks using Context-built message stacks."""

    def __init__(
        self,
        *,
        llm_runner: LLMActionModelRunner,
        context: ContextEngine,
        action_skills: ActionSkillProvider | None = None,
        context_bridge: RuntimeContextBridge | None = None,
    ) -> None:
        self._llm_runner = llm_runner
        self._context = context
        self._action_skills = action_skills or EmptyActionSkillProvider()
        self._context_bridge = context_bridge or RuntimeContextBridge()

    def prompt_with_skills(
        self,
        prompt: TaskPrompt,
        *,
        execution: ActionExecution,
    ) -> TaskPrompt:
        """Return a prompt with Phase3 domain/action skills appended."""

        return with_action_skills(
            prompt,
            self._action_skills.guidance_for(
                domain=execution.framework.domain,
                action_name=execution.call.action_name,
            ),
        )

    def run_json(
        self,
        *,
        execution: ActionExecution,
        prompt: TaskPrompt,
        subject: str,
        control: ActionExecutionControl | None = None,
    ) -> JsonObject | ActionResult:
        """Run one JSON-object LLM action task and normalize local failures."""

        result = self._run(
            execution=execution,
            prompt=prompt,
            answer_format=AnswerFormat.JSON_OBJECT,
            subject=subject,
            control=control,
        )
        if isinstance(result, ActionResult):
            return result
        if not isinstance(result.answer, JsonAnswer):
            return _failure(
                execution,
                feedback=f"{subject} did not return a JSON object.",
                reason="missing_json_answer",
                scope="llm.output_protocol",
                disposition=ActionFailureDisposition.RETRY_SAME,
            )
        return result.answer.value

    def run_text(
        self,
        *,
        execution: ActionExecution,
        prompt: TaskPrompt,
        subject: str,
        control: ActionExecutionControl | None = None,
        max_output_chars: int | None = None,
    ) -> str | ActionResult:
        """Run one complete text-artifact task without returning it to Context."""

        result = self._run(
            execution=execution,
            prompt=prompt,
            answer_format=AnswerFormat.TEXT,
            subject=subject,
            control=control,
            max_output_chars=max_output_chars,
        )
        if isinstance(result, ActionResult):
            return result
        if not isinstance(result.answer, TextAnswer):
            return _failure(
                execution,
                feedback=f"{subject} did not return text.",
                reason="missing_text_answer",
                scope="llm.output_protocol",
                disposition=ActionFailureDisposition.RETRY_SAME,
            )
        text = result.answer.text
        if not text:
            return _failure(
                execution,
                feedback=f"{subject} returned an empty text artifact.",
                reason="empty_text_artifact",
                scope="action.artifact",
                disposition=ActionFailureDisposition.RETRY_SAME,
            )
        options = _execution_options(execution)
        if isinstance(options, ActionResult):
            return options
        artifact_limit = _artifact_limit(
            options.max_output_chars,
            max_output_chars,
        )
        if artifact_limit is not None and len(text) > artifact_limit:
            return _failure(
                execution,
                feedback=(
                    f"{subject} exceeded its artifact character limit of "
                    f"{artifact_limit}."
                ),
                reason="artifact_too_large",
                scope="action.artifact",
                disposition=ActionFailureDisposition.CHANGE_REQUEST,
                constraint={"max_output_chars": artifact_limit},
                frame_data={"observed_chars": len(text)},
            )
        return text

    def _run(
        self,
        *,
        execution: ActionExecution,
        prompt: TaskPrompt,
        answer_format: AnswerFormat,
        subject: str,
        control: ActionExecutionControl | None,
        max_output_chars: int | None = None,
    ) -> TaskResult | ActionResult:
        prompt = self.prompt_with_skills(prompt, execution=execution)
        options = _execution_options(execution)
        if isinstance(options, ActionResult):
            return options
        cancellation = (
            TaskCancellation(
                cancelled=control.is_cancelled,
                remaining_seconds=lambda: _nested_task_remaining_seconds(control),
                reason=lambda: control.cancel_reason,
            )
            if control is not None
            else None
        )
        try:
            if cancellation is not None:
                cancellation.check()
            result = self._llm_runner.run(
                TaskCall(
                    profile=TaskProfile.LLM_ACTION,
                    messages=self._context.compose(prompt),
                    settings=CallSettings(
                        answer_format=answer_format,
                        tool_use=ToolUse.DISABLED,
                        max_output_tokens=_bounded_output_tokens(
                            options.max_output_tokens,
                            max_output_chars,
                        ),
                    ),
                    scope=execution.framework.scope,
                    context_overflow_policy=(
                        ModelContextOverflowPolicy.RECOMPOSE_CONTEXT
                    ),
                    cancellation=cancellation,
                )
            )
            if (
                cancellation is not None
                and result.status is TaskResultStatus.SUCCESS
            ):
                cancellation.check()
        except TaskCancelled as exc:
            cancel_reason = str(exc)
            reserved_deadline_expired = (
                cancel_reason == "deadline_expired"
                and control is not None
                and not control.is_cancelled()
                and control.remaining_seconds() is not None
            )
            failure = (
                ActionLocalFailure(
                    reason="execution_timeout",
                    scope="action.timeout",
                    disposition=ActionFailureDisposition.RETRY_SAME,
                    feedback="Action timed out during execution.",
                )
                if reserved_deadline_expired
                else ActionLocalFailure(
                    reason="cancelled",
                    scope="llm.execution",
                    disposition=ActionFailureDisposition.RETRY_SAME,
                    feedback="Action stopped after cancellation was requested.",
                )
            )
            return ActionResult.timeout(
                call_id=execution.call.call_id,
                invoke_id=execution.framework.invoke_id,
                batch_id=execution.framework.batch_id,
                action_name=execution.call.action_name,
                sequence=execution.call.sequence,
                domain=execution.framework.domain,
                failure=failure,
                frame_data={
                    "cancel_reason": cancel_reason or "cancelled",
                    "cancel_requested": control.is_cancelled() if control else False,
                    "executor_started": True,
                    "executor_leaked": False,
                    "late_success": False,
                },
            )
        except RuntimeException as exc:
            if exc.reason != CONTEXT_COMPRESSION_REQUIRED:
                raise
            protected_links = _protected_resource_links(execution)
            if not protected_links:
                raise
            raise RuntimeException(
                reason=exc.reason,
                message=exc.message,
                payload={
                    **exc.payload,
                    "protected_resource_links": list(protected_links),
                },
            ) from exc
        except ContextError as exc:
            protected_links = _protected_resource_links(execution)
            payload: JsonObject | None = None
            if protected_links:
                payload = {"protected_resource_links": list(protected_links)}
            raise self._context_bridge.from_context_error(exc, payload=payload) from exc
        if result.status is TaskResultStatus.FAILURE:
            feedback = f"{subject} output did not satisfy its protocol."
            if result.failure is not None and result.failure.model_feedback:
                feedback = result.failure.model_feedback
            failure = result.failure
            reason = (
                failure.reason.value
                if failure is not None
                else TaskFailureReason.TASK_FAILURE.value
            )
            scope = failure.scope.value if failure is not None else "llm.task"
            return _failure(
                execution,
                feedback=feedback,
                reason=reason,
                scope=scope,
                disposition=_failure_disposition(reason),
                constraint=failure.constraint if failure is not None else None,
                frame_data=failure.frame_data if failure is not None else None,
            )
        return result


def _nested_task_remaining_seconds(
    control: ActionExecutionControl,
) -> float | None:
    remaining = control.remaining_seconds()
    if remaining is None:
        return None
    return max(0.0, remaining - _COMPLETION_RESERVE_SECONDS)


def parse_llm_action_options(
    options: JsonObject,
    *,
    key: str,
) -> LLMActionBackendOptions:
    allowed = {"max_output_tokens", "max_output_chars"}
    unknown = sorted(name for name in options if name not in allowed)
    if unknown:
        raise ConfigError(
            "Unsupported llm_action backend option",
            key=f"{key}.{unknown[0]}",
            value=options[unknown[0]],
            expected=", ".join(sorted(allowed)),
        )
    return LLMActionBackendOptions(
        max_output_tokens=_positive_int_option(
            options,
            "max_output_tokens",
            key=key,
        ),
        max_output_chars=_positive_int_option(
            options,
            "max_output_chars",
            key=key,
        ),
    )


def _execution_options(
    execution: ActionExecution,
) -> LLMActionBackendOptions | ActionResult:
    try:
        return parse_llm_action_options(
            execution.action.backend.options,
            key=f"ActionBackendSpec({execution.action.name}).backend.options",
        )
    except ConfigError as exc:
        return _failure(
            execution,
            feedback="LLM action backend options are invalid.",
            reason="invalid_backend_options",
            scope="action.configuration",
            disposition=ActionFailureDisposition.STOP,
            frame_data={"error_type": type(exc).__name__, "key": exc.key},
        )


def _positive_int_option(
    options: JsonObject,
    name: str,
    *,
    key: str,
) -> int | None:
    value = options.get(name)
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    raise ConfigError(
        "llm_action backend option must be a positive integer",
        key=f"{key}.{name}",
        value=value,
        expected="positive int",
    )


def _bounded_output_tokens(
    configured: int | None,
    max_output_chars: int | None,
) -> int | None:
    """Keep bounded Workspace artifacts from spending the full action budget."""

    if max_output_chars is None:
        return configured
    # This is a generation guard, not a content conversion rule. Use one token
    # per character as the conservative ceiling; the final character check
    # remains authoritative because token/character ratios vary by language.
    derived = max(256, max_output_chars)
    if configured is None:
        return derived
    return min(configured, derived)


def _artifact_limit(
    configured: int | None,
    owner_limit: int | None,
) -> int | None:
    """Keep an owner-specific bound within the Catalog backend ceiling."""

    if configured is None:
        return owner_limit
    if owner_limit is None:
        return configured
    return min(configured, owner_limit)


def _failure_disposition(reason: str) -> ActionFailureDisposition:
    if reason in {"invalid_output_protocol", "incomplete_response"}:
        return ActionFailureDisposition.RETRY_SAME
    if reason in {"output_limit_reached", "content_filtered"}:
        return ActionFailureDisposition.CHANGE_REQUEST
    return ActionFailureDisposition.USE_FALLBACK


def _protected_resource_links(execution: ActionExecution) -> tuple[str, ...]:
    links: list[str] = []
    target = execution.call.params.get("target_link")
    if isinstance(target, str) and target:
        links.append(target)
    references = execution.call.params.get("reference_links", [])
    if isinstance(references, list):
        for link in references:
            if isinstance(link, str) and link and link not in links:
                links.append(link)
    return tuple(links)


def with_action_skills(prompt: TaskPrompt, skills: ActionSkillGuidance) -> TaskPrompt:
    """Return a prompt with domain/action skill blocks appended."""

    if not skills.domain and not skills.action:
        return prompt
    guide_blocks = [*prompt.guide_blocks]
    for index, item in enumerate(skills.domain, start=1):
        if item:
            guide_blocks.append(
                PromptBlock.from_text(
                    f"task_prompt:guide:domain_skill:{index}",
                    "# Domain Skill\n" + item,
                )
            )
    for index, item in enumerate(skills.action, start=1):
        if item:
            guide_blocks.append(
                PromptBlock.from_text(
                    f"task_prompt:guide:action_skill:{index}",
                    "# Action Skill\n" + item,
                )
            )
    return TaskPrompt(
        guide_blocks=tuple(guide_blocks),
        input_blocks=prompt.input_blocks,
        output_blocks=prompt.output_blocks,
    )


def _failure(
    execution: ActionExecution,
    *,
    feedback: str,
    reason: str,
    scope: str,
    disposition: ActionFailureDisposition,
    constraint: JsonObject | None = None,
    frame_data: JsonObject | None = None,
) -> ActionResult:
    return ActionResult.failed(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        stage=ActionResultStage.EXECUTE,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        failure=ActionLocalFailure(
            reason=reason,
            scope=scope,
            disposition=disposition,
            feedback=feedback,
            constraint=constraint or {},
        ),
        frame_data=frame_data,
    )
