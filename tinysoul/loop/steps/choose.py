"""Choose Action Task for Step 1 of the Query Loop.
"""

from typing import Any

from tinysoul.infra import EventLogger
from tinysoul.llm.tasks import (
    Example,
    InputSpec,
    Interpreter,
    OutputConstraint,
    PromptBuilder,
)
from tinysoul.llm.tasks.task import AITask
from tinysoul.llm.provider.config import LLMProfileName

from tinysoul.prompt.loop import get_choose_action_guide


class ChooseActionTask:
    """Step 1: Select the single most appropriate action from available actions."""

    def __init__(self, prompt_builder: PromptBuilder):
        self._builder = prompt_builder

    def run(
        self,
        system: list[dict[str, str]] | None,
        available_actions_meta: list[dict],
        action_schema: dict,
        client: Any | None = None,
        logger: EventLogger | None = None,
    ) -> dict[str, Any]:
        """
        Execute the choose-action AI task.

        Returns:
            Parsed dict with keys: action_name, selection_reason
        """
        task = AITask(
            prompt=self._builder.build(
                task_guide=get_choose_action_guide(),
                input_spec=InputSpec(
                    description="Available actions metadata and the action schema that defines how actions are structured.",
                    data={
                        "available_actions": available_actions_meta,
                        "action_schema": action_schema,
                    },
                ),
                output_constraint=OutputConstraint(
                    description='Respond EXACTLY with one of these JSON formats:\n'
                    'Format A (single action): {"action_name": "<action-name>", "selection_reason": "<selection-reason>"}\n'
                    'Format B (multiple parallel actions): {"actions": [{"action_name": "<name>", "selection_reason": "<reason>"}, ...]}\n'
                    "Use Format B only when multiple independent actions have no dependencies on each other and can safely execute in parallel.\n"
                    "<action-name>: Must be one of the available action names\n"
                    "<selection-reason>: Brief explanation (10-50 words) of why this action was chosen\n"
                    "DO NOT include markdown code blocks or any other text outside the JSON object.",
                ),
                examples=[
                    Example(
                        input={"available_actions": [{"name": "calculate"}]},
                        output={
                            "action_name": "calculate",
                            "selection_reason": "Need to compute the sum before proceeding",
                        },
                    ),
                    Example(
                        input={"available_actions": [{"name": "bash"}]},
                        output={
                            "action_name": "bash",
                            "selection_reason": "Must check file existence before processing",
                        },
                    ),
                    Example(
                        input={"available_actions": [
                            {"name": "read_file"},
                            {"name": "average_dog_weight"},
                        ]},
                        output={
                            "actions": [
                                {
                                    "action_name": "read_file",
                                    "selection_reason": "Need to check the design doc",
                                },
                                {
                                    "action_name": "average_dog_weight",
                                    "selection_reason": "Need to get dog weight in parallel",
                                },
                            ]
                        },
                    ),
                ],
            ),
            interpreter=Interpreter(),
            client=client,
            logger=logger,
        )
        return task.run(profile=LLMProfileName.STEP1, system=system).data
