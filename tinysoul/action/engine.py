"""Action module assembly facade."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Self

from tinysoul.infra.json import JsonObject
from tinysoul.llm.tools import ToolCallRecord, ToolScope
from tinysoul.runtime import (
    CyclePhase,
    NullObservationEmitter,
    ObservationEmitter,
    RunScope,
)

from .backends.llm_action import LLMActionBackendOptionsValidator
from .core.call import (
    ActionBatch,
    ActionBatchPreparation,
    ActionCall,
    ActionCallNormalizer,
    ActionExecutionBuilder,
    ActionNormalization,
)
from .core.catalog import ActionCatalog
from .core.errors import ActionContractError
from .core.executor import ActionExecutionContext, ActionExecutor, ExecutorRegistry
from .core.rendering import ActionResultRenderer, RenderedActionResult
from .core.hooks import (
    ActionExecutionHook,
    ActionExecutionHookPipeline,
    ActionHookRegistry,
    ActionNormalizeHook,
    ActionNormalizeHookPipeline,
)
from .core.loader import ActionCatalogLoader
from .core.result import ActionPhaseResult, ActionResult
from .core.specs import ActionBackendKind, ActionToolSpec
from .core.runner import ActionBatchRunner
from .core.scope import (
    DOMAIN_SELECTION_TOOL,
    ActionDomainSelection,
    ActionDomainPromptRenderer,
    ActionScopePreparation,
    Phase1DomainScopeBuilder,
    Phase2ActionScopeBuilder,
)


class ActionEngine:
    """Assembled action module entry point for loop/context integration."""

    def __init__(
        self,
        *,
        catalog: ActionCatalog,
        normalizer: ActionCallNormalizer,
        builder: ActionExecutionBuilder,
        runner: ActionBatchRunner,
        renderer: ActionResultRenderer,
        phase1_scope_builder: Phase1DomainScopeBuilder,
        phase2_scope_builder: Phase2ActionScopeBuilder,
        domain_prompt_renderer: ActionDomainPromptRenderer,
    ) -> None:
        self._catalog = catalog
        self._normalizer = normalizer
        self._builder = builder
        self._runner = runner
        self._renderer = renderer
        self._phase1_scope_builder = phase1_scope_builder
        self._phase2_scope_builder = phase2_scope_builder
        self._domain_prompt_renderer = domain_prompt_renderer

    def domain_names(self) -> tuple[str, ...]:
        """Expose stable catalog domain identities for framework integration."""

        return tuple(domain.name for domain in self._catalog.domains())

    def action_identifiers(self) -> tuple[tuple[str, str], ...]:
        """Expose catalog action identities without leaking mutable catalog state."""

        return tuple((action.domain, action.name) for action in self._catalog.actions())

    def view(self, action_names: tuple[str, ...]) -> "ActionEngine":
        """Return an immutable catalog view sharing the assembled runtime."""

        if not isinstance(action_names, tuple) or any(
            not isinstance(name, str) or not name for name in action_names
        ):
            raise ActionContractError(
                "ActionEngine view requires a tuple of non-empty action names"
            )
        if len(action_names) != len(set(action_names)):
            raise ActionContractError("ActionEngine view actions must be unique")
        return ActionEngine(
            catalog=self._catalog.with_actions(action_names),
            normalizer=self._normalizer,
            builder=self._builder,
            runner=self._runner,
            renderer=self._renderer,
            phase1_scope_builder=self._phase1_scope_builder,
            phase2_scope_builder=self._phase2_scope_builder,
            domain_prompt_renderer=self._domain_prompt_renderer,
        )

    def phase1_scope(self) -> ToolScope:
        return self._phase1_scope_builder.build(self._catalog)

    def phase1_domain_tool_name(self) -> str:
        return DOMAIN_SELECTION_TOOL

    def phase1_domain_prompt(self) -> str:
        return self._domain_prompt_renderer.render(self._catalog)

    def normalize_domain_selection(
        self,
        tool_calls: tuple[ToolCallRecord, ...],
    ) -> ActionDomainSelection:
        """Normalize Phase1 action-domain control calls."""

        return self._phase1_scope_builder.normalize_selection(
            self._catalog,
            tool_calls,
        )

    def phase2_scope(
        self,
        selected_domains: tuple[str, ...],
        *,
        turn_id: str = "",
        cycle_id: str = "",
    ) -> ActionScopePreparation:
        return self._phase2_scope_builder.prepare(
            self._catalog,
            selected_domains=selected_domains,
            phase=CyclePhase.PHASE2,
            turn_id=turn_id,
            cycle_id=cycle_id,
        )

    def normalize(
        self,
        tool_calls: tuple[ToolCallRecord, ...],
    ) -> ActionNormalization:
        return self._normalizer.normalize(
            tool_calls,
            catalog=self._catalog,
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
        return self._builder.prepare_batch(
            calls,
            catalog=self._catalog,
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
        return self._runner.run(batch, context or ActionExecutionContext())

    def render_result_model_payload(self, result: ActionResult) -> JsonObject:
        """Render one action result for model feedback."""

        return self._renderer.render_model_payload(result)

    def render_call_trace_payload(self, call: ActionCall) -> JsonObject:
        """Render one normalized action call for external observation."""

        action = self._catalog.get_action(call.action_name)
        return {
            "call_id": call.call_id,
            "action": call.action_name,
            "domain": action.domain,
            "sequence": call.sequence,
            "params": call.params,
        }

    def render_result_trace_payload(self, result: ActionResult) -> JsonObject:
        """Render one action result for trace storage."""

        return self._renderer.render_trace_payload(result)

    def render_tool_results(
        self,
        results: tuple[ActionResult, ...],
    ) -> tuple[RenderedActionResult, ...]:
        """Render visible and canonical model-side action result messages."""

        return self._renderer.render_many(results)

    def render_phase_model_payload(self, result: ActionPhaseResult) -> JsonObject:
        """Render one phase-level action result for model feedback."""

        return self._renderer.render_phase_model_payload(result)

    def render_phase_trace_payload(self, result: ActionPhaseResult) -> JsonObject:
        """Render one phase-level action result for trace storage."""

        return self._renderer.render_phase_trace_payload(result)

    def render_phase_model_payloads(
        self,
        results: tuple[ActionPhaseResult, ...],
    ) -> tuple[JsonObject, ...]:
        """Render phase-level action results for compact model feedback."""

        return self._renderer.render_phase_many(results)


class ActionEngineBuilder:
    """Assemble an ActionEngine from a catalog root and registered handlers."""

    def __init__(self, catalog_root: Path) -> None:
        self._catalog_root = catalog_root
        self._executors = ExecutorRegistry()
        self._hooks = ActionHookRegistry()
        self._max_workers = 8
        self._cooperative_cancel_grace_seconds = 0.05
        self._process_cancel_grace_seconds = 1.0
        self._observations: ObservationEmitter = NullObservationEmitter()
        self._disabled_actions: set[str] = set()
        self._included_actions: set[str] | None = None
        self._tool_property_schema_updates: dict[tuple[str, str], JsonObject] = {}

    def register_executor(
        self,
        handler: str,
        executor: ActionExecutor,
    ) -> Self:
        self._executors.register(handler, executor)
        return self

    def disable_actions(self, *action_names: str) -> Self:
        """Remove explicitly disabled package actions from the effective catalog."""

        for action_name in action_names:
            if not isinstance(action_name, str) or not action_name:
                raise ActionContractError("Disabled action name must be non-empty")
            self._disabled_actions.add(action_name)
        return self

    def include_actions(self, *action_names: str) -> Self:
        """Build an engine containing exactly the named package actions."""

        if self._included_actions is not None:
            raise ActionContractError("Included actions can only be configured once")
        if any(not isinstance(name, str) or not name for name in action_names):
            raise ActionContractError("Included action names must be non-empty")
        if len(action_names) != len(set(action_names)):
            raise ActionContractError("Included action names must be unique")
        self._included_actions = set(action_names)
        return self

    def update_tool_property_schema(
        self,
        action_name: str,
        property_name: str,
        updates: JsonObject,
    ) -> Self:
        """Merge validated schema keywords into one effective tool property."""

        if not action_name or not property_name:
            raise ActionContractError(
                "Action tool schema update requires non-empty action and property names"
            )
        key = (action_name, property_name)
        if key in self._tool_property_schema_updates:
            raise ActionContractError(
                f"Duplicate action tool schema update: {action_name}.{property_name}"
            )
        self._tool_property_schema_updates[key] = dict(updates)
        return self

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

    def with_observations(self, observations: ObservationEmitter) -> Self:
        self._observations = observations
        return self

    def build(self) -> ActionEngine:
        catalog = ActionCatalogLoader(
            backend_kind_options_validators={
                ActionBackendKind.LLM_ACTION: LLMActionBackendOptionsValidator(),
            },
        ).load(self._catalog_root)
        if self._included_actions is not None:
            available = {action.name for action in catalog.actions()}
            unknown_included = self._included_actions - available
            if unknown_included:
                raise ActionContractError(
                    "Included actions are absent from the package catalog: "
                    + ", ".join(sorted(unknown_included))
                )
            catalog = catalog.with_actions(tuple(sorted(self._included_actions)))
        unknown_disabled = self._disabled_actions - {
            action.name for action in catalog.actions()
        }
        if unknown_disabled:
            raise ActionContractError(
                "Disabled actions are absent from the package catalog: "
                + ", ".join(sorted(unknown_disabled))
            )
        if self._disabled_actions:
            catalog = catalog.with_actions(
                action.name
                for action in catalog.actions()
                if action.name not in self._disabled_actions
            )
        catalog = self._apply_tool_property_schema_updates(catalog)
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
                observations=self._observations,
            ),
            renderer=ActionResultRenderer(),
            phase1_scope_builder=Phase1DomainScopeBuilder(),
            phase2_scope_builder=Phase2ActionScopeBuilder(),
            domain_prompt_renderer=ActionDomainPromptRenderer(),
        )

    def _apply_tool_property_schema_updates(
        self,
        catalog: ActionCatalog,
    ) -> ActionCatalog:
        if not self._tool_property_schema_updates:
            return catalog
        unknown_actions = {
            action_name
            for action_name, _ in self._tool_property_schema_updates
            if not catalog.has_action(action_name)
        }
        if unknown_actions:
            raise ActionContractError(
                "Tool schema updates reference absent effective actions: "
                + ", ".join(sorted(unknown_actions))
            )
        actions = []
        for action in catalog.actions():
            updates = tuple(
                (property_name, values)
                for (action_name, property_name), values in (
                    self._tool_property_schema_updates.items()
                )
                if action_name == action.name
            )
            if not updates:
                actions.append(action)
                continue
            schema = dict(action.tool.schema)
            raw_properties = schema.get("properties")
            if not isinstance(raw_properties, dict):
                raise ActionContractError(
                    f"Action tool schema has no properties object: {action.name}"
                )
            properties = {
                name: dict(value) if isinstance(value, dict) else value
                for name, value in raw_properties.items()
            }
            for property_name, values in updates:
                raw_property = properties.get(property_name)
                if not isinstance(raw_property, dict):
                    raise ActionContractError(
                        "Action tool schema update references an absent property: "
                        f"{action.name}.{property_name}"
                    )
                raw_property.update(values)
                properties[property_name] = raw_property
            schema["properties"] = properties
            actions.append(
                replace(
                    action,
                    tool=ActionToolSpec(
                        name=action.tool.name,
                        description=action.tool.description,
                        schema=schema,
                    ),
                )
            )
        return ActionCatalog(domains=catalog.domains(), actions=actions)
