"""
Reasoning Action - structured explicit thinking for the query loop.

Produces a reasoning record without external side effects. The detailed
thinking is stored in action_record_list (not workspace files).
Emits LOOP_NEXT_TURN when skip_step3 is true.
"""
import json

from tinysoul.action.framework.handler import ActionBase
from tinysoul.action.executors.llm import OneStepAIExecutor
from tinysoul.trap import ActionExecutionError
from tinysoul.trap.signal import Signal, SignalType
from tinysoul.llm.tasks import InputSpec, OutputConstraint

ACTION_SPEC_REASONING = {
    "name": "reasoning",
    "description": "Perform structured explicit thinking: analyze failures, plan complex tasks, synthesize insights, or form hypotheses. This action has no external side effects; it only produces a thinking record that aids future action selection.",
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
                "need to reflect on consecutive failures",
                "need to plan before a complex multi-step task",
                "need to synthesize insights from multiple action records",
                "need to form a verifiable hypothesis",
            ],
        },
        "preconditions": [
            "Sufficient context exists to perform meaningful reasoning",
        ],
        "postconditions": {
            "logical_state_effects": [
                "A reasoning record is added to action_record_list",
                "May emit LOOP_NEXT_TURN to bypass Step 3 if no state changes are needed",
            ],
            "physical_environment_effects": [],
        },
    },
    "detail": {
        "parameter_schema": {
            "type": "object",
            "properties": {
                "reasoning_type": {
                    "type": "string",
                    "enum": [
                        "reflection",
                        "planning",
                        "synthesis",
                        "hypothesis",
                    ],
                    "description": "Type of reasoning to perform",
                },
                "topic": {
                    "type": "string",
                    "description": "The subject or question to reason about",
                },
                "reference_accesses": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                    "description": "Workspace files to read as reference before reasoning.",
                },
            },
            "required": [
                "reasoning_type",
                "topic",
            ],
        },
        "examples": [
            {
                "reasoning_type": "synthesis",
                "topic": "What have we learned about the user's intent from the last 3 turns?",
                "reference_accesses": [
                    "notes.md",
                ],
            },
        ],
        "edge_case_handling": [
            "No relevant action records: reason based on query_events and loop_target only",
            "Conflicting information: present both perspectives and indicate uncertainty",
            "Reasoning produces a clear next action: set skip_step3=true and list proposed_next_actions",
        ],
    },
}

ACTION_JSON_REASONING = json.dumps(ACTION_SPEC_REASONING, ensure_ascii=False, indent=2)


def _build_reasoning_prompt(builder, params, workspace):
    """Build prompt for structured reasoning."""
    reasoning_type = params.get("reasoning_type", "synthesis")
    topic = params.get("topic", "")
    refs_data = workspace.load_reference_data(params.get("reference_accesses", []))

    type_guide = {
        "reflection": "Analyze what went wrong in recent turns and identify root causes.",
        "planning": "Create a detailed step-by-step plan to achieve the loop_target.",
        "synthesis": "Combine insights from multiple action records into coherent conclusions.",
        "hypothesis": "Form a testable hypothesis based on available evidence.",
    }.get(reasoning_type, "Perform structured thinking on the given topic.")

    return builder.build(
        task_guide=(
            f"You are the Reasoning Action. {type_guide}\n"
            "Your thinking is recorded internally and helps guide future action selection.\n"
            "Be thorough but concise. Focus on actionable insights."
        ),
        input_spec=InputSpec(
            description="Reasoning topic and optional reference files.",
            data={
                "reasoning_type": reasoning_type,
                "topic": topic,
                "reference_files": refs_data,
            },
        ),
        output_constraint=OutputConstraint(
            description='Provide a JSON object with these fields: '
            '"content": the detailed reasoning (multi-paragraph allowed), '
            '"conclusions": ["concise insight 1", "concise insight 2", ...], '
            '"proposed_next_actions": ["action_name_1", "action_name_2", ...] or [], '
            '"skip_step3": true | false — set to true if your conclusions are purely analytical and no todo/milestone updates are needed\n'
            "DO NOT include markdown code blocks or any other text outside the JSON object. Return raw JSON only.",
        ),
    )


def _apply_reasoning_result(params, generated, workspace, context_provider):
    """Apply the generated reasoning result."""
    content = generated.get("content", "")
    conclusions = generated.get("conclusions", [])
    proposed_next_actions = generated.get("proposed_next_actions", [])
    skip_step3 = generated.get("skip_step3", False)

    result = {
        "content": content,
        "conclusions": conclusions,
        "proposed_next_actions": proposed_next_actions,
        "skip_step3": skip_step3,
    }

    if skip_step3 or not proposed_next_actions:
        # Emit LOOP_NEXT_TURN to bypass Step 3.
        # Control flow signals carry NO data; action data travels via ACTION_COMPLETED.
        context_provider.emit_signal(
            Signal(
                type=SignalType.LOOP_NEXT_TURN,
                turn=context_provider.current_turn,
                step="execute_action",
                action_name="reasoning",
                action_input=params,
                payload={},
            )
        )

    return result


class ReasoningAction(ActionBase):
    """Action to perform structured explicit thinking."""

    action_name = "reasoning"
    ACTION_JSON = ACTION_JSON_REASONING

    def __init__(self):
        super().__init__()
        self._executor = OneStepAIExecutor(
            build_prompt=_build_reasoning_prompt,
            apply_result=_apply_reasoning_result,
        )


def register_to(registry):
    """Register reasoning action to the given registry."""
    from tinysoul.action.framework.registry import ActionRegistry

    if isinstance(registry, ActionRegistry):
        registry.register_action_class(ReasoningAction)
