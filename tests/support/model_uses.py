"""Explicit test bindings for real Action consumers."""

from tinysoul.kernel.action.models import (
    ModelUseRegistry,
    ModelUseBinding,
    ModelUseDescriptor,
    ModelOperation,
    ModelImplementation,
)
from tinysoul.kernel.action.tasks import ActionTaskFactory, ActionSkillProvider
from tinysoul.kernel.context import ContextEngine


def action_tasks(
    context: ContextEngine,
    *,
    action_skills: ActionSkillProvider | None = None,
    max_output_tokens: int | None = None,
) -> ActionTaskFactory:
    descriptors = tuple(
        ModelUseDescriptor(f"{name}.generate", name, ModelOperation.GENERATE)
        for name in (
            "core.reason",
            "core.answer",
            "workspace.compose",
            "workspace.describe",
            "workspace.analyze",
        )
    ) + (
        ModelUseDescriptor(
            "expand.search.select", "expand.search", ModelOperation.SELECT
        ),
    )
    bindings = tuple(
        ModelUseBinding(
            item.consumer,
            ModelImplementation.LLM_TASK,
            task_profile="llm_action",
            max_output_tokens=max_output_tokens,
        )
        for item in descriptors
    )
    return ActionTaskFactory(
        context=context,
        action_skills=action_skills,
        models=ModelUseRegistry(descriptors, bindings),
    )
