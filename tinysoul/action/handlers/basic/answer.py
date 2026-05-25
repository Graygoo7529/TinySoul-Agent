"""
Answer Action - generates the final answer and terminates the query loop.

This action is the ONLY legal terminator of the QueryLoop. It synthesizes
all collected information into a final answer and emits LOOP_COMPLETE.
"""
import json

from tinysoul.action.framework.handler import ActionBase
from tinysoul.action.executors.llm import OneStepAIExecutor
from tinysoul.trap.signal import Signal, SignalType
from tinysoul.llm.tasks import InputSpec, OutputConstraint

ACTION_SPEC_ANSWER = {
    "name": "answer",
    "description": "Generate the final answer to the user's query and TERMINATE the query loop immediately. This action is the EXCLUSIVE and MANDATORY terminator — you MUST select it when the task is complete. It synthesizes all action records, milestones, and workspace files into a comprehensive response. No further actions will execute after this one.",
    "cluster": {
        "type": "NATIVE",
        "domain": "BASIC",
    },
    "profile": {
        "action_intention": "INTERNAL_REASONING",
        "action_environment_effect": "READ_ONLY",
        "action_mode": "SINGLE_RUN",
        "llm_dependency": "REQUIRED",
    },
    "contract": {
        "applicability": {
            "mode": "CONDITIONAL",
            "conditions": [
                "all necessary information has been gathered",
                "the task is complete and ready to present results",
                "no further actions are needed to fulfill the loop_target",
            ],
        },
        "preconditions": [
            "Sufficient action records and milestones exist to synthesize an answer",
            "The answer must directly address the user's original query",
        ],
        "postconditions": {
            "logical_state_effects": [
                "The query loop terminates immediately",
                "The answer is recorded in action_record_list",
            ],
            "physical_environment_effects": [],
        },
    },
    "detail": {
        "parameter_schema": {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "Brief direction (1-3 sentences) on how to synthesize the answer. E.g., 'Summarize the findings from report.md and the calculation results.'",
                },
                "reference_accesses": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                    "description": "Workspace files to read before generating the answer.",
                },
            },
            "required": [
                "instruction",
            ],
        },
        "examples": [
            {
                "instruction": "Based on report.md and the weight calculations, provide the combined weight answer",
                "reference_accesses": [
                    "report.md",
                ],
            },
        ],
        "edge_case_handling": [
            "Missing reference files: answer based on available action records and milestones",
            "Incomplete information: provide a partial answer with clear caveats",
            "Conflicting information: present both sides and indicate the conflict",
        ],
    },
}

ACTION_JSON_ANSWER = json.dumps(ACTION_SPEC_ANSWER, ensure_ascii=False, indent=2)


def _build_answer_prompt(builder, params, workspace):
    """Build prompt for generating the final answer."""
    instruction = params.get("instruction", "")
    refs_data = workspace.load_reference_data(params.get("reference_accesses", []))

    return builder.build(
        task_guide=(
            "You are the Answer Action. Your job is to produce the FINAL answer to the user's query.\n"
            "Synthesize all information from action records, milestones, and reference files.\n"
            "Be direct, accurate, and comprehensive."
        ),
        input_spec=InputSpec(
            description="Instruction for answer synthesis, plus optional reference files.",
            data={
                "instruction": instruction,
                "reference_files": refs_data,
            },
        ),
        output_constraint=OutputConstraint(
            description='Provide a JSON object with exactly these fields: '
            '"answer_text": the complete final answer (can be multi-paragraph), '
            '"confidence": "high" | "medium" | "low", '
            '"references": [list of source action names or file paths that informed the answer]\n'
            "DO NOT include markdown code blocks or any other text outside the JSON object. Return raw JSON only.",
        ),
    )


def _apply_answer_result(params, generated, workspace, context_provider):
    """Apply the generated answer and emit LOOP_COMPLETE."""
    answer_text = generated.get("answer_text", "")
    confidence = generated.get("confidence", "medium")
    references = generated.get("references", [])

    result = {
        "answer": answer_text,
        "confidence": confidence,
        "references": references,
    }

    # Emit LOOP_COMPLETE to terminate the query loop.
    # Control flow signals carry NO data; action data travels via ACTION_COMPLETED.
    context_provider.emit_signal(
        Signal(
            type=SignalType.LOOP_COMPLETE,
            turn=context_provider.current_turn,
            step="execute_action",
            action_name="answer",
            action_input=params,
            payload={},
        )
    )

    return result


class AnswerAction(ActionBase):
    """Action to generate the final answer and terminate the loop."""

    action_name = "answer"
    ACTION_JSON = ACTION_JSON_ANSWER

    def __init__(self):
        super().__init__()
        self._executor = OneStepAIExecutor(
            build_prompt=_build_answer_prompt,
            apply_result=_apply_answer_result,
        )


def register_to(registry):
    """Register answer action to the given registry."""
    from tinysoul.action.framework.registry import ActionRegistry

    if isinstance(registry, ActionRegistry):
        registry.register_action_class(AnswerAction)
