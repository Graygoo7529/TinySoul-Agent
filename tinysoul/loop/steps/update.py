"""Update State Task for Step 3 of the Query Loop.
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

from tinysoul.prompt.loop import get_update_state_guide


class UpdateStateTask:
    """Step 3: Update runtime state based on action results."""

    def __init__(self, prompt_builder: PromptBuilder):
        self._builder = prompt_builder

    def run(
        self,
        system: list[dict[str, str]] | None,
        state_schema: dict,
        new_action_records: list[dict],
        client: Any | None = None,
        logger: EventLogger | None = None,
    ) -> dict[str, Any]:
        """
        Execute the update-state AI task.

        Returns:
            Parsed dict with todo_operations, milestone_operation, milestone_param
        """
        task = AITask(
            prompt=self._builder.build(
                task_guide=get_update_state_guide(),
                input_spec=InputSpec(
                    description="New action records since last state update, plus the state schema.",
                    data={
                        "new_action_records": new_action_records,
                        "state_schema": state_schema,
                    },
                ),
                output_constraint=OutputConstraint(
                    description='Respond EXACTLY with a JSON object: '
                    '{"todo_operations": [...], "milestone_operation": "add"|"no-change", "milestone_param": "..."|null}\n'
                    "DO NOT include markdown code blocks or any other text outside the JSON object.",
                ),
                examples=[
                    Example(
                        input={
                            "new_action_records": [
                                {
                                    "action_name": "average_dog_weight",
                                    "action_result": {"average_weight": "37 lbs", "breed": "Golden Retriever"},
                                }
                            ]
                        },
                        output={
                            "todo_operations": [
                                {
                                    "operation": "add",
                                    "key": "get_second_weight",
                                    "description": "Get the second dog's weight",
                                }
                            ],
                            "milestone_operation": "no-change",
                            "milestone_param": None,
                        },
                    ),
                    Example(
                        input={
                            "new_action_records": [
                                {
                                    "action_name": "calculate",
                                    "action_result": {"value": "57", "expression": "3 * 19"},
                                }
                            ]
                        },
                        output={
                            "todo_operations": [
                                {"operation": "complete", "key": "get_second_weight"}
                            ],
                            "milestone_operation": "add",
                            "milestone_param": "Combined weight calculated as 57 lbs",
                        },
                    ),
                    Example(
                        input={
                            "new_action_records": [
                                {
                                    "action_name": "bash",
                                    "action_result": {"status": "error"},
                                }
                            ]
                        },
                        output={
                            "todo_operations": [
                                {
                                    "operation": "cancel",
                                    "key": "run_command",
                                },
                                {
                                    "operation": "add",
                                    "key": "retry",
                                    "description": "Retry with fixed parameters",
                                },
                            ],
                            "milestone_operation": "no-change",
                            "milestone_param": None,
                        },
                    ),
                ],
            ),
            interpreter=Interpreter(),
            client=client,
            logger=logger,
        )
        return task.run(profile=LLMProfileName.STEP3, system=system).data
