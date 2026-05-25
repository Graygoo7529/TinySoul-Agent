"""Prompt construction for LLM Task module.

Defines the five-element prompt structure and the PromptBuilder that
assembles them into a serialized string.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from tinysoul.context.protocols import ContextProvider

from .multimodal import Attachment


@dataclass
class InputSpec:
    """Specification of the input data for an LLM task."""

    description: str
    data: dict


@dataclass
class OutputConstraint:
    """Constraint on the expected LLM output."""

    description: str
    schema: dict | None = None


@dataclass
class Example:
    """An input/output example for few-shot prompting."""

    input: dict
    output: dict


@dataclass
class LLMPrompt:
    """
    A structured LLM prompt composed of five elements plus optional attachments:

    1. Task Guide          – what the model should do
    2. Context             – runtime environment (query_events, loop_target, etc.)
    3. Input Spec          – description + actual input data
    4. Output Constraint   – expected format and schema
    5. Examples            – few-shot demonstrations
    6. Attachments         – multimodal content (images, files)
    """

    task_guide: str
    context: dict
    input_spec: InputSpec
    output_constraint: OutputConstraint
    examples: list[Example] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)

    def serialize(self) -> str:
        """Serialize the five text elements into a single prompt string."""
        parts: list[str] = []

        parts.append(f"=== TASK GUIDE ===\n{self.task_guide.strip()}")

        if self.context:
            parts.append(
                f"\n\n=== CONTEXT ===\n"
                f"{json.dumps(self.context, ensure_ascii=False, indent=2)}"
            )

        parts.append(f"\n\n=== INPUT ===\n{self.input_spec.description.strip()}")
        if self.input_spec.data is not None:
            data_str = json.dumps(self.input_spec.data, ensure_ascii=False, indent=2)
            parts.append(f"\n{data_str}")

        parts.append(
            f"\n\n=== OUTPUT CONSTRAINT ===\n{self.output_constraint.description.strip()}"
        )
        if self.output_constraint.schema:
            schema_str = json.dumps(
                self.output_constraint.schema, ensure_ascii=False, indent=2
            )
            parts.append(f"\n\nSchema:\n{schema_str}")

        if self.examples:
            parts.append("\n\n=== EXAMPLES ===")
            for idx, ex in enumerate(self.examples, 1):
                parts.append(f"\nExample {idx}:")
                parts.append(f"Input:\n{json.dumps(ex.input, ensure_ascii=False, indent=2)}")
                parts.append(f"Output:\n{json.dumps(ex.output, ensure_ascii=False, indent=2)}")

        return "\n".join(parts)


class PromptBuilder:
    """
    Builds LLMPrompt instances from a ContextProvider and per-task overrides.

    The ContextProvider supplies the shared runtime context (query_events,
    loop_target, current_state, workspace, current_turn). Task-specific data
    is passed via InputSpec.data or extra_context.

    Callers can use ``include_context`` to select which fields are injected,
    avoiding unnecessary token usage when only a subset of context is needed.
    """

    # Fields injected by default when include_context is not specified.
    # Order is preserved in the serialized prompt.
    _DEFAULT_FIELDS = [
        "query_events",
        "loop_target",
        "current_turn",
        "current_state",
        "workspace",
    ]

    def __init__(self, provider: ContextProvider):
        self._provider = provider

    def build(
        self,
        *,
        task_guide: str,
        input_spec: InputSpec,
        output_constraint: OutputConstraint,
        examples: list[Example] | None = None,
        extra_context: dict | None = None,
        include_context: list[str] | None = None,
        attachments: list[Attachment] | None = None,
    ) -> LLMPrompt:
        """Construct an LLMPrompt with shared context from the provider.

        Args:
            include_context: Optional whitelist of context fields to include.
                Supports top-level keys (e.g. ``"query_events"``, ``"current_state"``)
                and nested keys (e.g. ``"current_state.todo_list"``).
                When ``None``, all shared fields are injected (default behaviour).
        """
        if include_context is None:
            context = {f: self._resolve_field(f) for f in self._DEFAULT_FIELDS}
        else:
            context = self._build_selected_context(include_context)

        if extra_context:
            context.update(extra_context)

        return LLMPrompt(
            task_guide=task_guide,
            context=context,
            input_spec=input_spec,
            output_constraint=output_constraint,
            examples=examples or [],
            attachments=attachments or [],
        )

    def _resolve_field(self, name: str) -> Any:
        """Resolve a single context field from the provider by convention.

        Resolution order:
        1. ``get_{name}()`` method — e.g. ``get_current_state()``
        2. Direct attribute access — e.g. ``provider.query_events``

        Raises:
            KeyError: if the field cannot be resolved on the provider.
        """
        provider = self._provider
        getter_name = f"get_{name}"
        getter = getattr(provider, getter_name, None)
        if getter is not None and callable(getter):
            return getter()
        if hasattr(provider, name):
            return getattr(provider, name)
        raise KeyError(f"Unknown context field: {name!r}")

    def _build_selected_context(self, include_context: list[str]) -> dict[str, Any]:
        """Build a context dict containing only the requested fields.

        Nested selections such as ``"current_state.todo_list"`` are supported.
        A top-level key (e.g. ``"current_state"``) overrides any nested
        selections for that same parent.
        """
        result: dict[str, Any] = {}
        nested_specs: dict[str, list[str]] = {}
        top_levels: set[str] = set()

        for field in include_context:
            if "." in field:
                top, sub = field.split(".", 1)
                nested_specs.setdefault(top, []).append(sub)
            else:
                top_levels.add(field)

        for field in top_levels:
            result[field] = self._resolve_field(field)

        for field, subs in nested_specs.items():
            if field in result:
                continue  # Parent requested whole; skip nested slicing
            full_value = self._resolve_field(field)
            if isinstance(full_value, dict):
                result[field] = {k: full_value[k] for k in subs if k in full_value}

        return result
