"""Reflection action views: common domains plus one owner write domain."""

from __future__ import annotations

from dataclasses import replace

from tinysoul.action import ActionCatalog, ActionCatalogLoader, ActionEngine, LoadedActionCatalog
from tinysoul.context import ContextEngine
from tinysoul.loop.actions import CommonActionAssembly
from tinysoul.capabilities.supervised_process import SupervisedProcessManager

from .errors import MaintenanceContractError
from .home import HomeMaintenanceActionController, register_home_maintenance_actions
from .memory import MemoryMaintenanceActionController, register_memory_maintenance_actions
from .resources import maintenance_action_catalog_root


def build_maintenance_action(
    *, kind: str, context: ContextEngine,
    home_controller: HomeMaintenanceActionController,
    memory_controller: MemoryMaintenanceActionController,
    action_catalog: LoadedActionCatalog,
    assembly: CommonActionAssembly,
) -> tuple[ActionEngine, SupervisedProcessManager]:
    if kind not in {"home", "memory"}:
        raise MaintenanceContractError("Unknown Reflection kind")
    domain = f"{kind}_reflection"
    with maintenance_action_catalog_root() as root:
        reflection = ActionCatalogLoader().load(root).with_domains((domain,))
    actions = []
    for action in action_catalog.catalog.actions():
        if action.name == "core.answer":
            action = replace(
                action,
                tool=replace(
                    action.tool,
                    description="Conclude this Reflection with a concise summary of accepted changes, remaining work and limitations.",
                ),
                semantic=replace(
                    action.semantic,
                    use_when=("The Reflection has a useful result or an explicit stopping reason",),
                    avoid_when=("More inspection or a known necessary correction is required",),
                    examples=(),
                ),
            )
        actions.append(action)
    combined = LoadedActionCatalog(
        catalog=ActionCatalog(
            domains=(*action_catalog.catalog.domains(), *reflection.domains()),
            actions=(*actions, *reflection.actions()),
        ),
        documents=action_catalog.documents,
    )
    builder, jobs = assembly.prepare(context, combined)
    if kind == "home":
        register_home_maintenance_actions(builder, controller=home_controller)
    else:
        builder.mark_actions_unsupported("core.memory.memorize")
        register_memory_maintenance_actions(builder, controller=memory_controller)
    return builder.build(), jobs
