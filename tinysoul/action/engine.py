"""Action module assembly facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.llm.tools import ToolCallRecord, ToolScope
from tinysoul.runtime import (
    CyclePhase,
    NullObservationEmitter,
    ObservationEmitter,
    RunScope,
)

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
from .core.loader import (
    ActionCatalogDocumentIndex,
    ActionCatalogDocumentRef,
    LoadedActionCatalog,
)
from .core.result import ActionPhaseResult, ActionResult
from .core.specs import ActionBackendKind
from .core.runner import ActionBatchRunner
from .core.scope import (
    DOMAIN_SELECTION_TOOL,
    ActionDomainSelection,
    ActionDomainPromptRenderer,
    ActionScopePreparation,
    Phase1DomainScopeBuilder,
    Phase2ActionScopeBuilder,
)


@dataclass(frozen=True)
class ActionCatalogEntry:
    """Finite public projection of one effective Action."""

    action_id: str
    domain: str
    description: str
    backend_kind: ActionBackendKind

    def to_json(self) -> JsonObject:
        return {
            "id": self.action_id,
            "domain": self.domain,
            "description": self.description,
            "backend_kind": self.backend_kind.value,
        }


class ActionEngine:
    """Assembled action module entry point for loop/context integration."""

    def __init__(
        self,
        *,
        catalog: ActionCatalog,
        configured_catalog: ActionCatalog,
        supported_actions: frozenset[str],
        catalog_documents: ActionCatalogDocumentIndex | None,
        normalizer: ActionCallNormalizer,
        builder: ActionExecutionBuilder,
        runner: ActionBatchRunner,
        renderer: ActionResultRenderer,
        phase1_scope_builder: Phase1DomainScopeBuilder,
        phase2_scope_builder: Phase2ActionScopeBuilder,
        domain_prompt_renderer: ActionDomainPromptRenderer,
    ) -> None:
        self._catalog = catalog
        self._configured_catalog = configured_catalog
        self._supported_actions = supported_actions
        self._catalog_documents = catalog_documents
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

    def catalog_projection(self) -> tuple[ActionCatalogEntry, ...]:
        """Expose the effective Action surface without catalog implementation state."""

        return tuple(
            ActionCatalogEntry(
                action_id=action.name,
                domain=action.domain,
                description=action.tool.description,
                backend_kind=action.backend.kind,
            )
            for action in self._catalog.actions()
        )

    def catalog_json(self) -> JsonObject:
        """Expose configured User Actions with availability and source bindings."""

        available_actions = {action.name for action in self._catalog.actions()}
        available_domains = {action.domain for action in self._catalog.actions()}
        documents = self._catalog_documents
        domains = []
        for domain in self._configured_catalog.domains():
            runtime = (
                documents.domain_runtimes.get(domain.name)
                if documents is not None
                else None
            )
            source = documents.domains.get(domain.name) if documents is not None else None
            domains.append(
                {
                    "id": domain.name,
                    "description": domain.description,
                    "selection_hint": domain.selection_hint,
                    "runtime": {
                        "enabled": (
                            runtime.enabled if runtime is not None else True
                        ),
                        "enabled_source": (
                            documents.domain_enabled_sources.get(
                                domain.name,
                                "default",
                            )
                            if documents is not None
                            else "default"
                        ),
                        "timeout_seconds": (
                            runtime.timeout_seconds if runtime is not None else None
                        ),
                        "parallel_policy": (
                            runtime.parallel_policy.value if runtime is not None else "allowed"
                        ),
                        "hooks": {
                            "normalize": (
                                list(runtime.hooks.normalize_hooks)
                                if runtime is not None
                                else []
                            ),
                            "execute": (
                                list(runtime.hooks.execution_hooks)
                                if runtime is not None
                                else []
                            ),
                        },
                        "trace_mode": (
                            runtime.result.trace_mode.value
                            if runtime is not None
                            else "standard"
                        ),
                    },
                    "available": domain.name in available_domains,
                    "action_count": len(
                        self._configured_catalog.actions_in_domain(domain.name)
                    ),
                    "source": (
                        _source_json(
                            source,
                            editable_paths=(
                                "description",
                                "selection_hint",
                                "runtime.enabled",
                                "runtime.timeout_seconds",
                            ),
                        )
                        if source is not None
                        else None
                    ),
                }
            )
        actions = []
        for action in self._configured_catalog.actions():
            source = documents.actions.get(action.name) if documents is not None else None
            actions.append(
                {
                    "id": action.name,
                    "domain": action.domain,
                    "tool": {
                        "description": action.tool.description,
                        "schema": action.tool.schema,
                    },
                    "semantic": {
                        "use_when": list(action.semantic.use_when),
                        "avoid_when": list(action.semantic.avoid_when),
                        "effects": [effect.value for effect in action.semantic.effects],
                        "examples": list(action.semantic.examples),
                    },
                    "runtime": {
                        "enabled": action.runtime.enabled,
                        "enabled_source": (
                            documents.enabled_sources.get(action.name, "default")
                            if documents is not None
                            else "default"
                        ),
                        "timeout_seconds": action.runtime.timeout_seconds,
                        "timeout_source": (
                            documents.timeout_sources.get(action.name, "none")
                            if documents is not None
                            else "none"
                        ),
                        "parallel_policy": action.runtime.parallel_policy.value,
                        "hooks": {
                            "normalize": list(action.runtime.hooks.normalize_hooks),
                            "execute": list(action.runtime.hooks.execution_hooks),
                        },
                        "trace_mode": action.runtime.result.trace_mode.value,
                    },
                    "backend": {
                        "kind": action.backend.kind.value,
                        "handler": action.backend.handler,
                        "options": action.backend.options,
                    },
                    "supported": action.name in self._supported_actions,
                    "available": action.name in available_actions,
                    "source": (
                        _source_json(
                            source,
                            editable_paths=_action_editable_paths(action.name),
                        )
                        if source is not None
                        else None
                    ),
                }
            )
        return to_json_object({"domains": domains, "actions": actions})

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
        configured_catalog = self._configured_catalog.with_actions(action_names)
        effective_action_names = tuple(
            name for name in action_names if self._catalog.has_action(name)
        )
        return ActionEngine(
            catalog=self._catalog.with_actions(effective_action_names),
            configured_catalog=configured_catalog,
            supported_actions=frozenset(
                self._supported_actions.intersection(action_names)
            ),
            catalog_documents=self._catalog_documents,
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
    """Assemble an ActionEngine from one already validated typed catalog."""

    def __init__(self, catalog: ActionCatalog | LoadedActionCatalog) -> None:
        if isinstance(catalog, LoadedActionCatalog):
            self._catalog = catalog.catalog
            self._catalog_documents: ActionCatalogDocumentIndex | None = catalog.documents
        elif isinstance(catalog, ActionCatalog):
            self._catalog = catalog
            self._catalog_documents = None
        else:
            raise ActionContractError(
                "ActionEngineBuilder requires an ActionCatalog or LoadedActionCatalog"
            )
        self._executors = ExecutorRegistry()
        self._hooks = ActionHookRegistry()
        self._max_workers = 8
        self._cooperative_cancel_grace_seconds = 0.05
        self._process_cancel_grace_seconds = 1.0
        self._observations: ObservationEmitter = NullObservationEmitter()
        self._unsupported_actions: set[str] = set()
        self._included_actions: set[str] | None = None

    def register_executor(
        self,
        handler: str,
        executor: ActionExecutor,
    ) -> Self:
        self._executors.register(handler, executor)
        return self

    def mark_actions_unsupported(self, *action_names: str) -> Self:
        """Mark actions whose runtime owner is unavailable in this Generation."""

        for action_name in action_names:
            if not isinstance(action_name, str) or not action_name:
                raise ActionContractError("Unsupported action name must be non-empty")
            self._unsupported_actions.add(action_name)
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
        complete_catalog = self._catalog
        complete_action_names = {action.name for action in complete_catalog.actions()}
        configured_catalog = complete_catalog
        if self._included_actions is not None:
            unknown_included = self._included_actions - complete_action_names
            if unknown_included:
                raise ActionContractError(
                    "Included actions are absent from the package catalog: "
                    + ", ".join(sorted(unknown_included))
                )
            configured_catalog = complete_catalog.with_actions(
                tuple(sorted(self._included_actions))
            )
        unknown_unsupported = self._unsupported_actions - complete_action_names
        if unknown_unsupported:
            raise ActionContractError(
                "Unsupported actions are absent from the package catalog: "
                + ", ".join(sorted(unknown_unsupported))
            )
        supported_actions = frozenset(
            action.name
            for action in configured_catalog.actions()
            if action.name not in self._unsupported_actions
        )
        catalog = configured_catalog.with_actions(
            action.name
            for action in configured_catalog.actions()
            if action.runtime.enabled and action.name in supported_actions
        )
        self._executors.validate_catalog(catalog)
        normalize_pipeline = ActionNormalizeHookPipeline(self._hooks)
        execution_pipeline = ActionExecutionHookPipeline(self._hooks)
        return ActionEngine(
            catalog=catalog,
            configured_catalog=configured_catalog,
            supported_actions=supported_actions,
            catalog_documents=self._catalog_documents,
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


def _source_json(
    source: ActionCatalogDocumentRef,
    *,
    editable_paths: tuple[str, ...],
) -> JsonObject:
    return {
        "source_id": source.source_id,
        "path": source.path,
        "document_kind": source.document_kind,
        "editable_paths": list(editable_paths),
    }


def _action_editable_paths(action_name: str) -> tuple[str, ...]:
    paths = (
        "tool.description",
        "semantic.use_when",
        "semantic.avoid_when",
        "semantic.effects",
        "semantic.examples",
        "runtime.enabled",
        "runtime.timeout_seconds",
    )
    if action_name == "execution.wait":
        return (
            *paths,
            "tool.schema.properties.wait_seconds.minimum",
            "tool.schema.properties.wait_seconds.default",
            "tool.schema.properties.wait_seconds.maximum",
        )
    return paths
