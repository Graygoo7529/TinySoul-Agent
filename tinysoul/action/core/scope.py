"""Build LLM tool scopes from action catalog views."""

from __future__ import annotations

from tinysoul.llm.tools import ToolKind, ToolScope, ToolSelection, ToolSpec

from .catalog import ActionCatalog
from .specs import ActionSpec


class Phase1DomainScopeBuilder:
    """Build a Phase1 control tool scope for selecting action domains."""

    def build(self, catalog: ActionCatalog) -> ToolScope:
        domains = tuple(
            domain
            for domain in catalog.domains()
            if catalog.actions_in_domain(domain.name)
        )
        tool = ToolSpec(
            name="select_action_domains",
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
            raise ValueError("Phase2 action scope must contain at least one action")
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
