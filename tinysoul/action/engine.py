"""Action module assembly facade."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Self

from tinysoul.infra.json import JsonObject
from tinysoul.llm.messages import ToolResultMessage
from tinysoul.llm.tools import ToolCallRecord, ToolScope
from tinysoul.runtime import CyclePhase, RunScope

from .backends.native import NativeActionFunction, NativeFunctionExecutor
from .backends.script import TemporaryScriptBackendOptionsValidator, TemporaryScriptExecutor
from .backends.subprocess import SubprocessBackendOptionsValidator, SubprocessActionExecutor
from .core.call import (
    ActionBatch,
    ActionBatchPreparation,
    ActionCall,
    ActionCallNormalizer,
    ActionExecutionBuilder,
    ActionNormalization,
)
from .core.catalog import ActionCatalog
from .core.executor import ActionExecutionContext, ActionExecutor, ExecutorRegistry
from .core.feedback import ActionFeedbackRenderer
from .core.hooks import (
    ActionExecutionHook,
    ActionExecutionHookPipeline,
    ActionHookRegistry,
    ActionNormalizeHook,
    ActionNormalizeHookPipeline,
)
from .core.loader import ActionBackendOptionsValidator, ActionCatalogLoader
from .core.result import ActionPhaseResult, ActionResult
from .core.runner import ActionBatchRunner
from .core.scope import (
    ActionDomainPromptRenderer,
    ActionScopePreparation,
    Phase1DomainScopeBuilder,
    Phase2ActionScopeBuilder,
)


@dataclass(frozen=True)
class ActionEngine:
    """Assembled action module entry point for loop/context integration."""

    catalog: ActionCatalog
    normalizer: ActionCallNormalizer
    builder: ActionExecutionBuilder
    runner: ActionBatchRunner
    renderer: ActionFeedbackRenderer
    phase1_scope_builder: Phase1DomainScopeBuilder
    phase2_scope_builder: Phase2ActionScopeBuilder
    domain_prompt_renderer: ActionDomainPromptRenderer

    def phase1_scope(self) -> ToolScope:
        return self.phase1_scope_builder.build(self.catalog)

    def phase1_domain_prompt(self) -> str:
        return self.domain_prompt_renderer.render(self.catalog)

    def validate_domain_selection(self, domain: str) -> str | None:
        """Return model feedback when an action domain cannot be selected."""

        if not self.catalog.has_domain(domain):
            return f"Unknown action domain: {domain}"
        if not self.catalog.actions_in_domain(domain):
            return f"Action domain has no available actions: {domain}"
        return None

    def phase2_scope(
        self,
        selected_domains: tuple[str, ...],
        *,
        turn_id: str = "",
        cycle_id: str = "",
    ) -> ActionScopePreparation:
        return self.phase2_scope_builder.prepare(
            self.catalog,
            selected_domains=selected_domains,
            phase=CyclePhase.PHASE2,
            turn_id=turn_id,
            cycle_id=cycle_id,
        )

    def normalize(
        self,
        tool_calls: tuple[ToolCallRecord, ...],
    ) -> ActionNormalization:
        return self.normalizer.normalize(
            tool_calls,
            catalog=self.catalog,
        )

    def prepare_batch(
        self,
        calls: tuple[ActionCall, ...],
        *,
        scope: RunScope,
        batch_id: str | None = None,
        turn_id: str = "",
        cycle_id: str = "",
    ) -> ActionBatchPreparation:
        return self.builder.prepare_batch(
            calls,
            catalog=self.catalog,
            scope=scope,
            batch_id=batch_id,
            turn_id=turn_id,
            cycle_id=cycle_id,
            phase=CyclePhase.PHASE3,
        )

    def run_batch(
        self,
        batch: ActionBatch,
        *,
        context: ActionExecutionContext | None = None,
    ) -> tuple[ActionResult, ...]:
        return self.runner.run(batch, context or ActionExecutionContext())

    def render_result_model_payload(self, result: ActionResult) -> JsonObject:
        """Render one action result for model feedback."""

        return self.renderer.render_model_payload(result)

    def render_result_trace_payload(self, result: ActionResult) -> JsonObject:
        """Render one action result for trace storage."""

        return self.renderer.render_trace_payload(result)

    def render_result_model_payloads(
        self,
        results: tuple[ActionResult, ...],
    ) -> tuple[JsonObject, ...]:
        """Render action results for compact model feedback."""

        return self.renderer.render_many(results)

    def to_tool_result_messages(
        self,
        results: tuple[ActionResult, ...],
    ) -> tuple[ToolResultMessage, ...]:
        """Render action results as model-side tool result replay messages."""

        return self.renderer.to_tool_result_messages(results)

    def render_phase_model_payload(self, result: ActionPhaseResult) -> JsonObject:
        """Render one phase-level action result for model feedback."""

        return self.renderer.render_phase_model_payload(result)

    def render_phase_trace_payload(self, result: ActionPhaseResult) -> JsonObject:
        """Render one phase-level action result for trace storage."""

        return self.renderer.render_phase_trace_payload(result)

    def render_phase_model_payloads(
        self,
        results: tuple[ActionPhaseResult, ...],
    ) -> tuple[JsonObject, ...]:
        """Render phase-level action results for compact model feedback."""

        return self.renderer.render_phase_many(results)


class ActionEngineBuilder:
    """Assemble an ActionEngine from a catalog root and registered handlers."""

    def __init__(self, catalog_root: Path) -> None:
        self._catalog_root = catalog_root
        self._executors = ExecutorRegistry()
        self._backend_options_validators: dict[str, ActionBackendOptionsValidator] = {}
        self._hooks = ActionHookRegistry()
        self._max_workers = 8
        self._cooperative_cancel_grace_seconds = 0.05
        self._process_cancel_grace_seconds = 1.0
        self.register_executor(
            "subprocess.default",
            SubprocessActionExecutor(),
            options_validator=SubprocessBackendOptionsValidator(),
        )
        self.register_executor(
            "script.temporary",
            TemporaryScriptExecutor(),
            options_validator=TemporaryScriptBackendOptionsValidator(),
        )

    def register_executor(
        self,
        handler: str,
        executor: ActionExecutor,
        *,
        options_validator: ActionBackendOptionsValidator | None = None,
    ) -> Self:
        self._executors.register(handler, executor)
        if options_validator is not None:
            self._backend_options_validators[handler] = options_validator
        return self

    def register_backend_options_validator(
        self,
        handler: str,
        validator: ActionBackendOptionsValidator,
    ) -> Self:
        self._backend_options_validators[handler] = validator
        return self

    def register_native(self, handler: str, function: NativeActionFunction) -> Self:
        return self.register_executor(handler, NativeFunctionExecutor(function))

    def register_normalize_hook(self, name: str, hook: ActionNormalizeHook) -> Self:
        self._hooks.register_normalize_hook(name, hook)
        return self

    def register_execution_hook(self, name: str, hook: ActionExecutionHook) -> Self:
        self._hooks.register_execution_hook(name, hook)
        return self

    def use_global_normalize_hooks(self, *names: str) -> Self:
        self._hooks.register_global_normalize(*names)
        return self

    def use_global_execution_hooks(self, *names: str) -> Self:
        self._hooks.register_global_execution(*names)
        return self

    def use_domain_normalize_hooks(self, domain: str, *names: str) -> Self:
        self._hooks.register_domain_normalize(domain, *names)
        return self

    def use_domain_execution_hooks(self, domain: str, *names: str) -> Self:
        self._hooks.register_domain_execution(domain, *names)
        return self

    def use_action_normalize_hooks(self, action_name: str, *names: str) -> Self:
        self._hooks.register_action_normalize(action_name, *names)
        return self

    def use_action_execution_hooks(self, action_name: str, *names: str) -> Self:
        self._hooks.register_action_execution(action_name, *names)
        return self

    def with_max_workers(self, max_workers: int) -> Self:
        self._max_workers = max_workers
        return self

    def with_cooperative_cancel_grace(self, seconds: float) -> Self:
        self._cooperative_cancel_grace_seconds = seconds
        return self

    def with_process_cancel_grace(self, seconds: float) -> Self:
        self._process_cancel_grace_seconds = seconds
        return self

    def build(self) -> ActionEngine:
        catalog = ActionCatalogLoader(
            backend_options_validators=self._backend_options_validators,
        ).load(self._catalog_root)
        self._executors.validate_catalog(catalog)
        normalize_pipeline = ActionNormalizeHookPipeline(self._hooks)
        execution_pipeline = ActionExecutionHookPipeline(self._hooks)
        return ActionEngine(
            catalog=catalog,
            normalizer=ActionCallNormalizer(normalize_pipeline),
            builder=ActionExecutionBuilder(),
            runner=ActionBatchRunner(
                executors=self._executors,
                hooks=execution_pipeline,
                max_workers=self._max_workers,
                cooperative_cancel_grace_seconds=self._cooperative_cancel_grace_seconds,
                process_cancel_grace_seconds=self._process_cancel_grace_seconds,
            ),
            renderer=ActionFeedbackRenderer(),
            phase1_scope_builder=Phase1DomainScopeBuilder(),
            phase2_scope_builder=Phase2ActionScopeBuilder(),
            domain_prompt_renderer=ActionDomainPromptRenderer(),
        )
