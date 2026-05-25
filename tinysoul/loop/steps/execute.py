"""Take Action Task for Step 2a of the Query Loop.
"""

from typing import Any

from tinysoul.infra import EventLogger
from tinysoul.llm.tasks import (
    InputSpec,
    Interpreter,
    OutputConstraint,
    PromptBuilder,
)
from tinysoul.llm.tasks.task import AITask
from tinysoul.llm.provider.config import LLMProfileName

from tinysoul.prompt.loop import get_generate_parameters_guide


class TakeActionTask:
    """Step 2a: Generate JSON arguments for the selected action."""

    def __init__(self, prompt_builder: PromptBuilder):
        self._builder = prompt_builder

    def run(
        self,
        system: list[dict[str, str]] | None,
        selected_action_detail: dict,
        client: Any | None = None,
        logger: EventLogger | None = None,
        selection_reason: str = "",
    ) -> dict[str, Any]:
        """
        Execute the take-action AI task.

        Args:
            selection_reason: The reason this action was selected (from Step 1).
                Used to align generated parameters with the action's intended purpose.

        Returns:
            Parsed dict of action arguments conforming to the action's parameter_schema
        """
        data: dict[str, Any] = {"selected_action_detail": selected_action_detail}
        if selection_reason:
            data["selection_reason"] = selection_reason
        task = AITask(
            prompt=self._builder.build(
                task_guide=get_generate_parameters_guide(),
                input_spec=InputSpec(
                    description="The selected action's detail schema (parameter_schema, examples, edge_case_handling).",
                    data=data,
                ),
                output_constraint=OutputConstraint(
                    description="Respond EXACTLY with a JSON object conforming to the action's parameter_schema. "
                    "DO NOT include markdown code blocks or any other text outside the JSON object.",
                ),
            ),
            interpreter=Interpreter(),
            client=client,
            logger=logger,
        )
        return task.run(profile=LLMProfileName.STEP2, system=system).data
