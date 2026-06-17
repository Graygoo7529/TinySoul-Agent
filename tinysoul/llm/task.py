"""LLM task execution."""

from __future__ import annotations

from .messages import ImagePart, MessageStack
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
    ResponseContract,
    ResponseInterpretError,
    ResponseInterpreter,
    TaskResult,
)


class LLMTaskError(Exception):
    """Raised when an LLM task cannot complete."""


class ModelCapabilityError(LLMTaskError):
    """Raised when a model cannot satisfy a request."""


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
    ) -> None:
        self._models = models
        self._providers = providers
        self._tasks = tasks
        self._interpreter = interpreter or ResponseInterpreter()
        self._sleeper = sleeper or Sleeper()
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
            raise LLMTaskError(str(exc)) from exc
        except ProviderError as exc:
            raise LLMTaskError(str(exc)) from exc

    def reset_route(self, profile: TaskProfile | str | None = None) -> None:
        self._chain_runner.reset(profile)

    def _try_model(self, call: TaskCall, task: TaskSpec, model_id: str) -> TaskResult:
        model = self._models.get(model_id)
        settings = self._resolve_settings(call, task)
        response_contract = settings.response_contract
        if response_contract is None:
            raise LLMTaskError(f"Task '{task.profile}' has no response contract")
        self._check_capabilities(call, model, response_contract=response_contract)
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
                        response_contract=response_contract,
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
            return self._interpreter.interpret(response, response_contract)

        if last_error is None:
            raise LLMTaskError("Model retry failed without a provider error")
        raise last_error

    def _is_fatal_error(self, error: Exception) -> bool:
        if isinstance(error, ModelCapabilityError):
            return True
        if isinstance(error, ProviderError):
            return error.kind in {
                ProviderErrorKind.AUTH,
                ProviderErrorKind.CONFIG,
                ProviderErrorKind.CAPABILITY,
            }
        return False

    def _check_capabilities(
        self,
        call: TaskCall,
        model: ModelSpec,
        *,
        response_contract: ResponseContract,
    ) -> None:
        required = {ModelCapability.TEXT_INPUT}
        if response_contract is ResponseContract.JSON_OBJECT:
            required.add(ModelCapability.JSON_OBJECT_OUTPUT)

        for message in call.messages.messages:
            for part in message.parts:
                if isinstance(part, ImagePart):
                    required.add(ModelCapability.IMAGE_INPUT)

        missing = [capability for capability in required if not model.supports(capability)]
        if missing:
            names = ", ".join(capability.value for capability in missing)
            raise ModelCapabilityError(f"Model '{model.id}' lacks required capabilities: {names}")

    def _resolve_settings(
        self,
        call: TaskCall,
        task: TaskSpec,
    ) -> CallSettings:
        return task.settings.override_with(call.overrides.settings)
