"""LLM task execution."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.runtime import RuntimeException
from tinysoul.runtime.bridge import RuntimeLLMBridge

from .messages import ImagePart, ImageUrlPart, MessageStack
from .model_chain import (
    Clock,
    ModelChainExhaustedError,
    ModelChainPlanner,
    ModelChainRunner,
    ModelChainState,
    Sleeper,
    TaskSpec,
    TaskSpecTable,
)
from .models import ModelCapability, ModelRegistry, ModelSpec
from .provider import ProviderError, ProviderErrorKind, ProviderRegistry, ProviderRequest
from .requests import CallSettings, TaskCall, TaskProfile
from .responses import (
    AnswerFormat,
    ResponseInterpretError,
    ResponseInterpreter,
    TASK_FAILURE_RESPONSE_INTERPRETATION_FAILED,
    TaskFailure,
    TaskResult,
)
from .tools import ToolUse


class LLMTaskError(Exception):
    """Raised when an LLM task cannot complete."""


class ModelCapabilityError(LLMTaskError):
    """Raised when a model cannot satisfy a request."""


@dataclass(frozen=True)
class CurrentModelCapabilities:
    """Current preferred model capability view for a task."""

    profile: str
    model_id: str
    provider_id: str
    provider_model: str
    capabilities: frozenset[ModelCapability]

    def supports(self, capability: ModelCapability) -> bool:
        return capability in self.capabilities


class CapabilityPolicy:
    """Resolve and validate hard model capabilities for a task call."""

    def required_capabilities(
        self,
        call: TaskCall,
        *,
        settings: CallSettings,
    ) -> frozenset[ModelCapability]:
        required = {ModelCapability.TEXT_INPUT} | set(settings.required_capabilities)
        if settings.tool_use is not ToolUse.DISABLED:
            required.add(ModelCapability.TOOL_CALLING)
        for message in call.messages.messages:
            for part in message.parts:
                if isinstance(part, ImagePart):
                    required.add(ModelCapability.IMAGE_INPUT)
                if isinstance(part, ImageUrlPart):
                    required.add(ModelCapability.IMAGE_REMOTE_URL)
        return frozenset(required)

    def missing_capabilities(
        self,
        model: ModelSpec,
        required: frozenset[ModelCapability],
    ) -> tuple[ModelCapability, ...]:
        return tuple(capability for capability in required if not model.supports(capability))

    def ensure_supported(
        self,
        model: ModelSpec,
        required: frozenset[ModelCapability],
    ) -> None:
        missing = self.missing_capabilities(model, required)
        if missing:
            names = ", ".join(capability.value for capability in missing)
            raise ModelCapabilityError(
                f"Model '{model.id}' lacks required capabilities: {names}"
            )


class TaskCallValidator:
    """Validate semantic consistency of a task call."""

    def validate(self, call: TaskCall, *, settings: CallSettings) -> None:
        tool_use = settings.tool_use
        if tool_use is None:
            raise LLMTaskError("Task has no tool use policy")
        if tool_use is ToolUse.DISABLED:
            if not call.tool_scope.is_empty():
                raise LLMTaskError("Tool scope must be empty when tool use is disabled")
            return
        if not call.tool_scope.visible_tools():
            raise LLMTaskError("Tool use requires at least one visible tool")
        if (
            call.tool_scope.selection.forced_name is not None
            and tool_use is not ToolUse.REQUIRED
        ):
            raise LLMTaskError("Forced tool selection requires required tool use")


class LLMTaskRunner:
    """Execute LLM task calls over registered model chains."""

    def __init__(
        self,
        *,
        models: ModelRegistry,
        providers: ProviderRegistry,
        tasks: TaskSpecTable,
        interpreter: ResponseInterpreter | None = None,
        chain_state: ModelChainState | None = None,
        chain_planner: ModelChainPlanner | None = None,
        sleeper: Sleeper | None = None,
        clock: Clock | None = None,
        chain_runner: ModelChainRunner | None = None,
        capability_policy: CapabilityPolicy | None = None,
        call_validator: TaskCallValidator | None = None,
        runtime_bridge: RuntimeLLMBridge | None = None,
    ) -> None:
        self._models = models
        self._providers = providers
        self._tasks = tasks
        self._interpreter = interpreter or ResponseInterpreter()
        self._capability_policy = capability_policy or CapabilityPolicy()
        self._call_validator = call_validator or TaskCallValidator()
        self._sleeper = sleeper or Sleeper()
        self._runtime_bridge = runtime_bridge or RuntimeLLMBridge()
        self._chain_runner = chain_runner or ModelChainRunner(
            state=chain_state,
            planner=chain_planner,
            sleeper=self._sleeper,
            clock=clock,
        )

    def run(self, call: TaskCall) -> TaskResult:
        task = self._tasks.get(call.profile)
        try:
            return self._chain_runner.run(
                task.chain,
                lambda model_id: self._try_model(call, task, model_id),
                is_fatal=self._is_fatal_error,
            )
        except ModelChainExhaustedError as exc:
            raise self._runtime_bridge.model_chain_exhausted(
                message=str(exc),
                payload={"profile": task.profile},
            ) from exc
        except ProviderError as exc:
            raise self._runtime_bridge.unhandled_failure(
                message=str(exc),
                payload={
                    "profile": task.profile,
                    "kind": exc.kind.value,
                },
            ) from exc
        except LLMTaskError as exc:
            raise self._runtime_bridge.unhandled_failure(
                message=str(exc),
                payload={"profile": task.profile},
            ) from exc

    def reset_route(self, profile: TaskProfile | str | None = None) -> None:
        self._chain_runner.reset(profile)

    def current_model_capabilities(
        self,
        profile: TaskProfile | str,
    ) -> CurrentModelCapabilities:
        task = self._tasks.get(profile)
        model_id = self._chain_runner.current_model_id(task.chain)
        model = self._models.get(model_id)
        return CurrentModelCapabilities(
            profile=task.profile,
            model_id=model.id,
            provider_id=model.provider_id,
            provider_model=model.provider_model,
            capabilities=model.capabilities,
        )

    def _try_model(self, call: TaskCall, task: TaskSpec, model_id: str) -> TaskResult:
        model = self._models.get(model_id)
        settings = self._resolve_settings(call, task)
        answer_format = settings.answer_format
        if answer_format is None:
            raise LLMTaskError(f"Task '{task.profile}' has no answer format")
        tool_use = settings.tool_use
        if tool_use is None:
            raise LLMTaskError(f"Task '{task.profile}' has no tool use policy")
        self._call_validator.validate(call, settings=settings)
        self._capability_policy.ensure_supported(
            model,
            self._capability_policy.required_capabilities(call, settings=settings),
        )
        provider = self._providers.get(model.provider_id)
        last_error: ProviderError | None = None

        for attempt in range(task.chain.retry_policy.max_retries_per_model):
            if attempt > 0:
                self._sleeper.sleep(task.chain.retry_policy.retry_wait_seconds)
            try:
                response = provider.invoke(
                    ProviderRequest(
                        model=model,
                        messages=call.messages,
                        answer_format=answer_format,
                        tool_use=tool_use,
                        tool_scope=call.tool_scope,
                        prompt_cache=call.prompt_cache,
                        temperature=settings.temperature,
                        max_output_tokens=settings.max_output_tokens,
                        provider_options=dict(model.provider_options.values),
                    )
                )
            except ProviderError as exc:
                if exc.kind is not ProviderErrorKind.TRANSIENT:
                    raise
                last_error = exc
                continue
            try:
                return self._interpreter.interpret(
                    response,
                    answer_format,
                    tool_use,
                    tool_scope=call.tool_scope,
                )
            except ResponseInterpretError as exc:
                return TaskResult.failure_result(
                    raw_response=response,
                    failure=TaskFailure(
                        kind=TASK_FAILURE_RESPONSE_INTERPRETATION_FAILED,
                        model_feedback=str(exc),
                        frame_data={
                            "task_profile": task.profile,
                            "model_id": model.id,
                            "provider_id": model.provider_id,
                        },
                    ),
                )

        if last_error is None:
            raise LLMTaskError("Model retry failed without a provider error")
        raise last_error

    def _is_fatal_error(self, error: Exception) -> bool:
        if isinstance(error, RuntimeException):
            return True
        if isinstance(error, ProviderError):
            return error.kind is not ProviderErrorKind.TRANSIENT
        return isinstance(error, LLMTaskError)

    def _resolve_settings(
        self,
        call: TaskCall,
        task: TaskSpec,
    ) -> CallSettings:
        return task.settings.override_with(call.settings)
