"""LLM task execution."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.runtime import (
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RuntimeException,
    emit_observation,
    observation_enabled,
)
from tinysoul.runtime.bridge import RuntimeLLMBridge

from .errors import LLMContractError, LLMError, TaskCancelled
from .failures import LLMFailureKind
from .context_window import (
    ModelContextPolicy,
    ModelContextPressureError,
    RequestTokenEstimator,
)
from .messages import ImagePart, ImageUrlPart, MessageStack
from .model_chain import (
    ChainErrorDisposition,
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
from .observation_payloads import task_request_observation, task_response_observation
from .provider import ProviderError, ProviderErrorKind, ProviderRegistry, ProviderRequest
from .provider.base import ProviderAdapter
from .requests import (
    CallSettings,
    ModelContextOverflowPolicy,
    TaskCall,
    TaskProfile,
)
from .responses import (
    AnswerFormat,
    RawResponse,
    ResponseInterpretError,
    ResponseStopReason,
    ResponseInterpreter,
    TaskFailure,
    TaskFailureReason,
    TaskFailureScope,
    TaskResult,
)
from .tools import ToolUse


class LLMTaskError(LLMContractError):
    """Raised when an LLM task cannot complete."""


class ModelCapabilityError(LLMTaskError):
    """Raised when a model cannot satisfy a request."""

    def __init__(
        self,
        *,
        model_id: str,
        missing: tuple[ModelCapability, ...],
    ) -> None:
        names = ", ".join(capability.value for capability in missing)
        super().__init__(f"Model '{model_id}' lacks required capabilities: {names}")
        self.model_id = model_id
        self.missing = missing


@dataclass(frozen=True)
class CurrentModelCapabilities:
    """Current preferred model capability view for a task."""

    profile: str
    model_id: str
    provider_id: str
    provider_model: str
    context_window_tokens: int
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
            raise ModelCapabilityError(model_id=model.id, missing=missing)


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
        observations: ObservationEmitter | None = None,
        context_trigger_ratio: float = 0.80,
        token_estimator: RequestTokenEstimator | None = None,
    ) -> None:
        self._models = models
        self._providers = providers
        self._tasks = tasks
        self._interpreter = interpreter or ResponseInterpreter()
        self._capability_policy = capability_policy or CapabilityPolicy()
        self._call_validator = call_validator or TaskCallValidator()
        self._sleeper = sleeper or Sleeper()
        self._runtime_bridge = runtime_bridge or RuntimeLLMBridge()
        self._observations = observations or NullObservationEmitter()
        self._context_policy = ModelContextPolicy(
            trigger_ratio=context_trigger_ratio,
            estimator=token_estimator,
        )
        self._chain_runner = chain_runner or ModelChainRunner(
            state=chain_state,
            planner=chain_planner,
            sleeper=self._sleeper,
            clock=clock,
        )

    def run(self, call: TaskCall) -> TaskResult:
        self._emit(
            call,
            "llm.task.started",
            ObservationLevel.VERBOSE,
            "LLM task started.",
            {"profile": call.profile},
        )
        try:
            result = self._run_task(call)
        except Exception as exc:
            self._emit(
                call,
                "llm.task.failed",
                ObservationLevel.VERBOSE,
                "LLM task failed.",
                {
                    "profile": call.profile,
                    "error_type": type(exc).__name__,
                },
            )
            raise
        self._emit(
            call,
            "llm.task.completed",
            ObservationLevel.VERBOSE,
            "LLM task completed.",
            {
                "profile": call.profile,
                "status": result.status.value,
            },
        )
        return result

    def _run_task(self, call: TaskCall) -> TaskResult:
        try:
            _check_cancellation(call)
            task = self._tasks.get(call.profile)
            return self._chain_runner.run(
                task.chain,
                lambda model_id: self._run_model(call, task, model_id),
                classify_error=self._classify_chain_error,
            )
        except ModelContextPressureError as exc:
            kind = LLMFailureKind.MODEL_CONTEXT_LIMIT_REACHED
            if (
                call.context_overflow_policy
                is ModelContextOverflowPolicy.RECOMPOSE_CONTEXT
            ):
                kind = LLMFailureKind.MODEL_CONTEXT_COMPRESSION_REQUIRED
            raise self._runtime_bridge.from_exception(
                kind,
                exc,
                payload=to_json_object(
                    {"profile": call.profile, **exc.usage.to_payload()}
                ),
            ) from exc
        except ModelChainExhaustedError as exc:
            raise self._runtime_bridge.from_exception(
                LLMFailureKind.MODEL_CHAIN_EXHAUSTED,
                exc,
                payload=self._model_chain_exhausted_payload(call, exc),
            ) from exc
        except TaskCancelled:
            raise
        except LLMContractError as exc:
            raise self._runtime_bridge.from_exception(
                LLMFailureKind.CONTRACT_VIOLATION,
                exc,
                payload={"profile": call.profile},
            ) from exc
        except LLMError as exc:
            raise self._runtime_bridge.from_exception(
                LLMFailureKind.INTERNAL_FAILURE,
                exc,
                payload={"profile": call.profile},
            ) from exc
        except RuntimeException:
            raise
        except Exception as exc:
            raise self._runtime_bridge.from_exception(
                LLMFailureKind.INTERNAL_FAILURE,
                exc,
                payload={"profile": call.profile},
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
            context_window_tokens=model.context_window_tokens,
            capabilities=model.capabilities,
        )

    def _try_model(self, call: TaskCall, task: TaskSpec, model_id: str) -> TaskResult:
        _check_cancellation(call)
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
        reserved_output_tokens = _effective_max_output_tokens(model, settings)
        context_usage = self._context_policy.usage(
            model=model,
            messages=call.messages,
            tool_scope=call.tool_scope,
            reserved_output_tokens=reserved_output_tokens,
        )
        if context_usage.over_trigger:
            raise ModelContextPressureError(context_usage)
        provider = self._providers.get(model.provider_id)
        last_error: ProviderError | None = None

        for attempt in range(task.chain.retry_policy.max_retries_per_model):
            _check_cancellation(call)
            if attempt > 0:
                self._emit(
                    call,
                    "llm.model.retry",
                    ObservationLevel.VERBOSE,
                    "Retrying transient provider failure.",
                    {
                        "profile": task.profile,
                        "model_id": model.id,
                        "provider_id": model.provider_id,
                        "attempt": attempt + 1,
                    },
                )
                self._sleeper.sleep(task.chain.retry_policy.retry_wait_seconds)
                _check_cancellation(call)
            if observation_enabled(self._observations, ObservationLevel.MODEL):
                request_payload = task_request_observation(
                    call.messages,
                    call.tool_scope,
                )
                request_payload.update(
                    {
                        "profile": task.profile,
                        "model_id": model.id,
                        "provider_id": model.provider_id,
                        "provider_model": model.provider_model,
                        "attempt": attempt + 1,
                    }
                )
                self._emit(
                    call,
                    "llm.model.request",
                    ObservationLevel.MODEL,
                    "Provider-neutral model request.",
                    request_payload,
                )
            try:
                _check_cancellation(call)
                response = _invoke_provider(
                    provider,
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
                        timeout_seconds=_remaining_seconds(call),
                    ),
                    call,
                )
            except ProviderError as exc:
                if exc.kind is ProviderErrorKind.CONTEXT_LIMIT:
                    raise ModelContextPressureError(
                        self._context_policy.usage(
                            model=model,
                            messages=call.messages,
                            tool_scope=call.tool_scope,
                            reserved_output_tokens=reserved_output_tokens,
                            provider_reported_limit=True,
                        )
                    ) from exc
                if exc.kind is not ProviderErrorKind.TRANSIENT:
                    raise
                last_error = exc
                continue
            if observation_enabled(self._observations, ObservationLevel.MODEL):
                self._emit(
                    call,
                    "llm.model.response",
                    ObservationLevel.MODEL,
                    "Provider-neutral model response.",
                    task_response_observation(response),
                )
            completion_failure = _completion_failure(
                response,
                max_output_tokens=settings.max_output_tokens,
            )
            if completion_failure is not None:
                return TaskResult.failure_result(
                    raw_response=response,
                    failure=completion_failure,
                )
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
                        model_feedback=str(exc),
                        reason=TaskFailureReason.INVALID_OUTPUT_PROTOCOL,
                        scope=TaskFailureScope.OUTPUT_PROTOCOL,
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

    def _run_model(
        self,
        call: TaskCall,
        task: TaskSpec,
        model_id: str,
    ) -> TaskResult:
        model = self._models.get(model_id)
        payload: JsonObject = {
            "profile": task.profile,
            "model_id": model.id,
            "provider_id": model.provider_id,
        }
        self._emit(
            call,
            "llm.model.started",
            ObservationLevel.VERBOSE,
            "Starting model attempt.",
            payload,
        )
        try:
            result = self._try_model(call, task, model_id)
        except Exception as exc:
            failure_payload = {**payload, "error_type": type(exc).__name__}
            if isinstance(exc, ProviderError):
                failure_payload["provider_error_kind"] = exc.kind.value
            self._emit(
                call,
                "llm.model.failed",
                ObservationLevel.VERBOSE,
                "Model attempt failed.",
                failure_payload,
            )
            raise
        self._emit(
            call,
            "llm.model.completed",
            ObservationLevel.VERBOSE,
            "Model attempt completed.",
            {**payload, "status": result.status.value},
        )
        return result

    def _emit(
        self,
        call: TaskCall,
        name: str,
        level: ObservationLevel,
        message: str,
        payload: JsonObject,
    ) -> None:
        if not observation_enabled(self._observations, level):
            return
        emit_observation(
            self._observations,
            ObservationEvent(
                name=name,
                level=level,
                source="llm.task",
                scope=call.scope,
                message=message,
                payload={"task_id": call.task_id, **payload},
            ),
        )

    def _classify_chain_error(self, error: Exception) -> ChainErrorDisposition:
        if isinstance(error, TaskCancelled):
            return ChainErrorDisposition.ABORT
        if isinstance(error, RuntimeException):
            return ChainErrorDisposition.ABORT
        if isinstance(error, ModelContextPressureError):
            return ChainErrorDisposition.ABORT
        if isinstance(error, ModelCapabilityError):
            return ChainErrorDisposition.SWITCH
        if isinstance(error, ProviderError):
            if error.kind is ProviderErrorKind.TRANSIENT:
                return ChainErrorDisposition.RETRY_NEXT_CYCLE
            return ChainErrorDisposition.SWITCH
        return ChainErrorDisposition.ABORT

    def _model_chain_exhausted_payload(
        self,
        call: TaskCall,
        error: ModelChainExhaustedError,
    ) -> JsonObject:
        payload: JsonObject = {"profile": call.profile}
        last_error = error.last_error
        if last_error is None:
            return payload
        payload["last_error_type"] = type(last_error).__name__
        if isinstance(last_error, ProviderError):
            payload["provider_error_kind"] = last_error.kind.value
        if isinstance(last_error, ModelCapabilityError):
            payload["model_id"] = last_error.model_id
            payload["missing_capabilities"] = [
                capability.value for capability in last_error.missing
            ]
        return payload

    def _resolve_settings(
        self,
        call: TaskCall,
        task: TaskSpec,
    ) -> CallSettings:
        return task.settings.override_with(call.settings)


def _completion_failure(
    response: RawResponse,
    *,
    max_output_tokens: int | None,
) -> TaskFailure | None:
    if response.stop_reason is ResponseStopReason.OUTPUT_LIMIT:
        constraint: JsonObject = {}
        if max_output_tokens is not None:
            constraint["max_output_tokens"] = max_output_tokens
        return TaskFailure(
            model_feedback="Model generation reached its output token limit.",
            reason=TaskFailureReason.OUTPUT_LIMIT_REACHED,
            scope=TaskFailureScope.OUTPUT,
            constraint=constraint,
        )
    if response.stop_reason is ResponseStopReason.CONTENT_FILTER:
        return TaskFailure(
            model_feedback="Model generation was stopped by a content filter.",
            reason=TaskFailureReason.CONTENT_FILTERED,
            scope=TaskFailureScope.OUTPUT,
        )
    if response.stop_reason is ResponseStopReason.INCOMPLETE:
        return TaskFailure(
            model_feedback="Model generation ended before producing a complete response.",
            reason=TaskFailureReason.INCOMPLETE_RESPONSE,
            scope=TaskFailureScope.OUTPUT,
        )
    return None


def _effective_max_output_tokens(
    model: ModelSpec,
    settings: CallSettings,
) -> int:
    override = model.provider_options.request_overrides().max_output_tokens
    if override is not None:
        return override
    return settings.max_output_tokens or 0


def _check_cancellation(call: TaskCall) -> None:
    if call.cancellation is not None:
        call.cancellation.check()


_PROVIDER_CANCEL_POLL_SECONDS = 0.1


def _invoke_provider(
    provider: ProviderAdapter,
    request: ProviderRequest,
    call: TaskCall,
) -> RawResponse:
    """Invoke the provider, abandoning the wait when the task is cancelled.

    Without a cancellation contract the provider call runs inline. With
    one, the blocking call runs on a daemon worker thread while this
    thread waits in short slices and re-checks the cancel/deadline hooks.
    On cancellation the in-flight request is orphaned: it completes or
    times out in the background and its result is discarded without
    touching any task state.
    """

    cancellation = call.cancellation
    if cancellation is None:
        return provider.invoke(request)
    responses: list[RawResponse] = []
    errors: list[BaseException] = []
    done = Event()

    def _worker() -> None:
        try:
            responses.append(provider.invoke(request))
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    Thread(
        target=_worker,
        name="tinysoul-llm-provider",
        daemon=True,
    ).start()
    while not done.wait(_PROVIDER_CANCEL_POLL_SECONDS):
        cancellation.check()
    # The provider may finish in the same polling interval as cancellation.
    # Re-check before publishing either success or an error from the worker.
    cancellation.check()
    if errors:
        raise errors[0]
    return responses[0]


def _remaining_seconds(call: TaskCall) -> float | None:
    if call.cancellation is None:
        return None
    remaining = call.cancellation.remaining_seconds()
    if remaining is None:
        return None
    if remaining <= 0:
        call.cancellation.check()
        raise TaskCancelled("deadline_expired")
    return remaining
