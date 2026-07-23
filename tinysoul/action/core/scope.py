"""Build LLM tool scopes from action catalog views."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.llm.tools import ToolCallRecord, ToolKind, ToolScope, ToolSelection, ToolSpec

from .catalog import ActionCatalog
from tinysoul.runtime import CyclePhase

from .errors import ActionContractError
from .result import (
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionPhaseResult,
    ActionPhaseResultStage,
)
from .specs import ActionSpec

DOMAIN_SELECTION_TOOL = "select_action_domains"


@dataclass(frozen=True)
class ActionDomainSelection:
    """Normalized Phase1 action domain selection."""

    selected_domains: tuple[str, ...]
    feedback: tuple[str, ...] = ()


class Phase1DomainScopeBuilder:
    """Build a Phase1 control tool scope for selecting action domains."""

    def build(self, catalog: ActionCatalog) -> ToolScope:
        domains = tuple(
            domain
            for domain in catalog.domains()
            if catalog.actions_in_domain(domain.name)
        )
        tool = ToolSpec(
            name=DOMAIN_SELECTION_TOOL,
            description="Select action domains for the next action-parameter generation phase.",
            parameters={
                "type": "object",
                "properties": {
                    "domains": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [domain.name for domain in domains],
                        },
                        "description": "Action domain names to expose in Phase2.",
                    },
                    "intent": {
                        "type": "string",
                        "description": "Brief reason for the selected action domains.",
                    },
                },
                "required": ["domains"],
                "additionalProperties": False,
            },
            kind=ToolKind.CONTROL,
        )
        return ToolScope(
            tools=(tool,),
            selection=ToolSelection(allowed_names=(tool.name,)),
        )

    def normalize_selection(
        self,
        catalog: ActionCatalog,
        tool_calls: tuple[ToolCallRecord, ...],
    ) -> ActionDomainSelection:
        selections = tuple(
            call for call in tool_calls if call.name == DOMAIN_SELECTION_TOOL
        )
        if not selections:
            return ActionDomainSelection(
                selected_domains=(),
                feedback=("Phase1 must call select_action_domains.",),
            )
        if len(selections) > 1:
            return ActionDomainSelection(
                selected_domains=(),
                feedback=("Phase1 must call select_action_domains only once.",),
            )
        value = selections[0].arguments.get("domains")
        if not isinstance(value, list) or not value:
            return ActionDomainSelection(
                selected_domains=(),
                feedback=(
                    "select_action_domains.domains must be a non-empty string list.",
                ),
            )
        selected_domains: list[str] = []
        feedback: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str) or not item:
                feedback.append(
                    "select_action_domains.domains must contain non-empty strings."
                )
                continue
            if item in seen:
                continue
            seen.add(item)
            domain_feedback = _domain_selection_feedback(catalog, item)
            if domain_feedback is not None:
                feedback.append(domain_feedback)
                continue
            selected_domains.append(item)
        if not selected_domains and not feedback:
            feedback.append("select_action_domains.domains contained no usable domains.")
        return ActionDomainSelection(
            selected_domains=tuple(selected_domains),
            feedback=tuple(feedback),
        )


class ActionDomainPromptRenderer:
    """Render Phase1-visible domain descriptions for task prompt overlays."""

    def render(self, catalog: ActionCatalog) -> str:
        lines = ["Available action domains:"]
        for domain in catalog.domains():
            if not catalog.actions_in_domain(domain.name):
                continue
            lines.append(f"- {domain.name}: {domain.description}")
            if domain.selection_hint:
                lines.append(f"  Selection hint: {domain.selection_hint}")
        return "\n".join(lines)


class Phase2ActionScopeBuilder:
    """Build a Phase2 action tool scope from selected catalog domains."""

    def prepare(
        self,
        catalog: ActionCatalog,
        *,
        selected_domains: tuple[str, ...],
        phase: CyclePhase = CyclePhase.PHASE2,
        turn_id: str = "",
        cycle_id: str = "",
    ) -> "ActionScopePreparation":
        try:
            return ActionScopePreparation(
                tool_scope=self.build(
                    catalog,
                    selected_domains=selected_domains,
                ),
            )
        except ActionContractError as exc:
            return ActionScopePreparation(
                tool_scope=None,
                phase_results=(
                    ActionPhaseResult.failed(
                        phase=phase,
                        stage=ActionPhaseResultStage.SCOPE,
                        failure=ActionLocalFailure(
                            reason="scope_preparation_failed",
                            scope="action.scope",
                            disposition=ActionFailureDisposition.STOP,
                            feedback="Action scope preparation failed.",
                        ),
                        frame_data={
                            "error_type": type(exc).__name__,
                            "selected_domains": list(selected_domains),
                        },
                        turn_id=turn_id,
                        cycle_id=cycle_id,
                    ),
                ),
            )

    def build(
        self,
        catalog: ActionCatalog,
        *,
        selected_domains: tuple[str, ...],
    ) -> ToolScope:
        actions: list[ActionSpec] = []
        for domain in selected_domains:
            actions.extend(catalog.actions_in_domain(domain))
        if not actions:
            raise ActionContractError("Phase2 action scope must contain at least one action")
        tools = tuple(self._tool_spec(action) for action in actions)
        return ToolScope(
            tools=tools,
            selection=ToolSelection(allowed_names=tuple(tool.name for tool in tools)),
        )

    def _tool_spec(self, action: ActionSpec) -> ToolSpec:
        description = self._description(action)
        return ToolSpec(
            name=action.name,
            description=description,
            parameters=action.tool.schema,
            kind=ToolKind.ACTION,
        )

    def _description(self, action: ActionSpec) -> str:
        lines = [action.tool.description]
        if action.semantic.use_when:
            lines.append("Use when: " + "; ".join(action.semantic.use_when))
        if action.semantic.avoid_when:
            lines.append("Avoid when: " + "; ".join(action.semantic.avoid_when))
        if action.semantic.effects:
            effects = ", ".join(effect.value for effect in action.semantic.effects)
            lines.append("Effects: " + effects)
        if action.semantic.examples:
            lines.append("Examples: " + "; ".join(action.semantic.examples))
        return "\n".join(lines)


@dataclass(frozen=True)
class ActionScopePreparation:
    """Prepared action tool scope plus phase-level preparation results."""

    tool_scope: ToolScope | None
    phase_results: tuple[ActionPhaseResult, ...] = ()


def _domain_selection_feedback(catalog: ActionCatalog, domain: str) -> str | None:
    if not catalog.has_domain(domain):
        return f"Unknown action domain: {domain}"
    if not catalog.actions_in_domain(domain):
        return f"Action domain has no available actions: {domain}"
    return None
