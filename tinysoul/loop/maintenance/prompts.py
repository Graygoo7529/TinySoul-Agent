"""Maintenance Turn prompt guidance."""

from __future__ import annotations

from ..errors import LoopContractError


def maintenance_turn_guidance(kind: str) -> tuple[str, ...]:
    common = (
        "This is an autonomous Maintenance Turn, not a user conversation.",
        "Use the supplied Background, Session, Workspace, and TurnTrace as context.",
        "Do not produce a user answer or wait for human approval.",
        "Call maintenance.complete only after all owner postconditions are satisfied.",
    )
    if kind == "home":
        return (
            *common,
            "Review every runtime Home difference against actual Home and the actual core rules.",
            "Resolve each difference with accept, reject, or rewrite until none remain.",
        )
    if kind == "memory":
        return (
            *common,
            "Reflect on the closed day's archived Session facts and Workspace projection.",
            "Consolidate the durable Memory document before completing.",
        )
    raise LoopContractError(f"Unknown Maintenance Turn kind: {kind}")
