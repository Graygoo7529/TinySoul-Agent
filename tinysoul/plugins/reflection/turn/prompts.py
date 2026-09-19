"""Reflection Turn prompt guidance."""

from __future__ import annotations

from ..errors import ReflectionContractError


def reflection_turn_guidance(kind: str) -> tuple[str, ...]:
    common = (
        "This is an autonomous Reflection Turn.",
        "Use the supplied Background, Session, Workspace, and TurnTrace as context.",
        "Common domains remain available. Inspect evidence and act in small steps.",
        "Use core.answer to conclude with a summary of changes, remaining work and limitations.",
        "The summary is a Reflection result, not a user response. Normal Reflection needs no approval.",
    )
    if kind == "home":
        return (
            *common,
            "Review every runtime Home difference against actual Home and the actual core rules.",
            "Use home.diff; edit effective copies through home actions as needed.",
            "Use home.review to accept or reject selected changes.",
        )
    if kind == "memory":
        return (
            *common,
            "Distinguish the target day from the current execution day.",
            "Use the fixed target-day Session and active Memory sources. Archived Workspace is read-only; current Workspace is the execution workbench.",
            "Inspect/recall before writing. Write one document at a time and inspect the result.",
            "Create redirect targets before retiring source documents; committed writes remain if later work fails.",
        )
    raise ReflectionContractError(f"Unknown Reflection Turn kind: {kind}")
