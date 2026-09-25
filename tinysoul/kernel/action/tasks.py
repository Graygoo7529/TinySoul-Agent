"""Prepare Action-local model inputs without invoking models or interpreting business output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject
from tinysoul.kernel.context import ContextEngine, TaskPrompt, PromptBlock
from tinysoul.kernel.context.errors import ContextError
from tinysoul.kernel.context.runtime_bridge import RuntimeContextBridge
from tinysoul.llm.protocol.messages import MessageStack
from tinysoul.llm.protocol.requests import (
    TaskCall,
    TaskCancellation,
    CallSettings,
    ModelContextOverflowPolicy,
)
from tinysoul.llm.protocol.responses import (
    AnswerFormat,
    JsonAnswer,
    TextAnswer,
    TaskResult,
    TaskResultStatus,
)
from tinysoul.llm.protocol.tools import ToolUse
from .call import ActionExecution
from .models import ModelUseRegistry, ModelImplementation
from .execution.executor import ActionExecutionControl
from .result import (
    ActionResult,
    ActionLocalFailure,
    ActionFailureDisposition,
    ActionResultStage,
)


@dataclass(frozen=True)
class ActionSkillGuidance:
    """Skill snippets automatically mounted for one nested LLM action."""

    domain: tuple[str, ...] = ()
    action: tuple[str, ...] = ()


class ActionSkillProvider(Protocol):
    """Provide domain and action skill text for nested LLM tasks."""

    async def guidance_for(
        self, *, domain: str, action_name: str
    ) -> ActionSkillGuidance:
        """Return skill snippets for one action execution."""
        ...


class EmptyActionSkillProvider:
    """Empty action skill provider used before Agent Home is connected."""

    async def guidance_for(
        self, *, domain: str, action_name: str
    ) -> ActionSkillGuidance:
        return ActionSkillGuidance()


class ActionTaskFactory:
    """Compose one typed LLM input using an explicitly resolved consumer."""

    def __init__(
        self,
        *,
        context: ContextEngine,
        models: ModelUseRegistry,
        action_skills: ActionSkillProvider | None = None,
    ) -> None:
        self._context = context
        self._models = models
        self._action_skills = action_skills or EmptyActionSkillProvider()

    async def selection_input(
        self,
        execution: ActionExecution,
        *,
        include_context: bool,
        control: ActionExecutionControl | None = None,
    ):
        from tinysoul.kernel.retrieval.operations import SelectionInput

        if control:
            control.check_cancelled()
        guidance = await self._action_skills.guidance_for(
            domain=execution.framework.domain, action_name=execution.call.action_name
        )
        try:
            context = (
                self._context.compose(
                    TaskPrompt(
                        guide_blocks=(
                            PromptBlock.from_text(
                                "retrieval:context",
                                "Use the current Context as reference for the requested candidate selection.",
                            ),
                        )
                    )
                )
                if include_context
                else None
            )
        except ContextError as exc:
            raise RuntimeContextBridge().from_context_error(exc) from exc
        return SelectionInput(
            context=context,
            guidance=(*guidance.domain, *guidance.action),
            scope=execution.framework.scope,
            cancellation=TaskCancellation(
                cancelled=control.is_cancelled,
                remaining_seconds=control.remaining_seconds,
                reason=lambda: control.cancel_reason,
            )
            if control
            else None,
        )

    async def create(
        self,
        *,
        execution: ActionExecution,
        consumer: str,
        prompt: TaskPrompt,
        answer_format: AnswerFormat = AnswerFormat.JSON_OBJECT,
        control: ActionExecutionControl | None = None,
        include_context: bool = True,
        max_output_chars: int | None = None,
        context_overflow_policy: ModelContextOverflowPolicy = ModelContextOverflowPolicy.REQUEST_RECOVERY,
    ) -> TaskCall:
        if control is not None:
            control.check_cancelled()
        descriptor = self._models.descriptor(consumer)
        binding = self._models.binding(consumer)
        if (
            descriptor.action_id != execution.call.action_name
            or binding.implementation is not ModelImplementation.LLM_TASK
            or binding.task_profile is None
        ):
            raise ConfigError("Consumer is not an LLM use of this Action", key=consumer)
        prompt = with_action_skills(
            prompt,
            await self._action_skills.guidance_for(
                domain=execution.framework.domain,
                action_name=execution.call.action_name,
            ),
        )
        try:
            messages = (
                self._context.compose(prompt)
                if include_context
                else MessageStack(prompt.render_messages())
            )
        except ContextError as exc:
            raise RuntimeContextBridge().from_context_error(exc) from exc
        tokens = binding.max_output_tokens
        if max_output_chars is not None:
            tokens = (
                min(tokens, max(256, max_output_chars))
                if tokens
                else max(256, max_output_chars)
            )
        return TaskCall(
            profile=binding.task_profile,
            messages=messages,
            consumer=consumer,
            settings=CallSettings(
                answer_format=answer_format,
                tool_use=ToolUse.DISABLED,
                max_output_tokens=tokens,
            ),
            scope=execution.framework.scope,
            context_overflow_policy=context_overflow_policy,
            cancellation=TaskCancellation(
                cancelled=control.is_cancelled,
                remaining_seconds=control.remaining_seconds,
                reason=lambda: control.cancel_reason,
            )
            if control
            else None,
        )


class ActionTaskOutput:
    """Pure conversion of task protocol results; business validation stays with the owner."""

    @staticmethod
    def json(
        result: TaskResult, execution: ActionExecution, *, subject: str
    ) -> JsonObject | ActionResult:
        failure = ActionTaskOutput.failure(result, execution, subject=subject)
        if failure is not None:
            return failure
        if not isinstance(result.answer, JsonAnswer):
            return _failure(
                execution,
                feedback=f"{subject} did not return a JSON object.",
                reason="missing_json_answer",
                scope="llm.output_protocol",
                disposition=ActionFailureDisposition.RETRY_SAME,
            )
        return result.answer.value

    @staticmethod
    def text(
        result: TaskResult, execution: ActionExecution, *, subject: str, max_chars: int
    ) -> str | ActionResult:
        failure = ActionTaskOutput.failure(result, execution, subject=subject)
        if failure is not None:
            return failure
        if not isinstance(result.answer, TextAnswer) or not result.answer.text:
            return _failure(
                execution,
                feedback=f"{subject} did not return nonempty text.",
                reason="missing_text_answer",
                scope="llm.output_protocol",
                disposition=ActionFailureDisposition.RETRY_SAME,
            )
        text = result.answer.text
        if len(text) > max_chars:
            return _failure(
                execution,
                feedback=f"{subject} exceeded its artifact limit.",
                reason="artifact_too_large",
                scope="action.artifact",
                disposition=ActionFailureDisposition.CHANGE_REQUEST,
                constraint={"max_output_chars": max_chars},
                frame_data={"observed_chars": len(text)},
            )
        return text

    @staticmethod
    def failure(
        result: TaskResult, execution: ActionExecution, *, subject: str
    ) -> ActionResult | None:
        if result.status is not TaskResultStatus.FAILURE:
            return None
        failure = result.failure
        reason = failure.reason.value if failure else "task_failure"
        return _failure(
            execution,
            feedback=(failure.model_feedback if failure else None)
            or f"{subject} failed.",
            reason=reason,
            scope=failure.scope.value if failure else "llm.task",
            disposition=ActionFailureDisposition.CHANGE_REQUEST
            if reason in {"output_limit_reached", "content_filtered", "input_capacity"}
            else ActionFailureDisposition.RETRY_SAME,
            constraint=failure.constraint if failure else None,
            frame_data=failure.frame_data if failure else None,
        )


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
