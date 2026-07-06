"""Action module assembly facade."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Self

from tinysoul.llm.tools import ToolCallRecord, ToolScope
from tinysoul.runtime import RunScope

from tinysoul.action.backends.native import NativeActionFunction, NativeFunctionExecutor
from tinysoul.action.backends.script import TemporaryScriptExecutor
from tinysoul.action.backends.subprocess import SubprocessActionExecutor

from .call import (
    ActionBatch,
    ActionBatchPreparation,
    ActionCall,
    ActionCallNormalizer,
    ActionExecutionBuilder,
    ActionNormalization,
)
from .catalog import ActionCatalog
from .executor import ActionExecutionContext, ActionExecutor, ExecutorRegistry
from .feedback import ActionFeedbackRenderer
from .hooks import (
    ActionExecutionHook,
    ActionExecutionHookPipeline,
    ActionHookRegistry,
    ActionNormalizeContext,
    ActionNormalizeHook,
    ActionNormalizeHookPipeline,
)
from .loader import ActionCatalogLoader
from .phase import ActionCyclePhase
from .result import ActionResult
from .runner import ActionBatchRunner
from .scope import (
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
            phase=ActionCyclePhase.PHASE2,
            turn_id=turn_id,
            cycle_id=cycle_id,
        )

    def normalize(
        self,
        tool_calls: tuple[ToolCallRecord, ...],
        *,
        context: ActionNormalizeContext | None = None,
    ) -> ActionNormalization:
        return self.normalizer.normalize(
            tool_calls,
            catalog=self.catalog,
            context=context,
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
            phase=ActionCyclePhase.PHASE3,
        )

    def run_batch(
        self,
        batch: ActionBatch,
        *,
        context: ActionExecutionContext | None = None,
    ) -> tuple[ActionResult, ...]:
        return self.runner.run(batch, context or ActionExecutionContext())


class ActionEngineBuilder:
    """Assemble an ActionEngine from a catalog root and registered handlers."""

    def __init__(self, catalog_root: Path) -> None:
        self._catalog_root = catalog_root
        self._loader = ActionCatalogLoader()
        self._executors = ExecutorRegistry()
        self._hooks = ActionHookRegistry()
        self._max_workers = 8
        self._cooperative_cancel_grace_seconds = 0.05
        self._process_cancel_grace_seconds = 1.0
        self.register_executor("subprocess.default", SubprocessActionExecutor())
        self.register_executor("script.temporary", TemporaryScriptExecutor())

    def register_executor(self, handler: str, executor: ActionExecutor) -> Self:
        self._executors.register(handler, executor)
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
        catalog = self._loader.load(self._catalog_root)
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
