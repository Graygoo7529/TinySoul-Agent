from __future__ import annotations

from enum import StrEnum

import pytest

from tinysoul.action.failures import ActionFailureKind
from tinysoul.app.failures import AppFailureKind
from tinysoul.context.failures import ContextFailureKind
from tinysoul.home.failures import AgentHomeFailureKind
from tinysoul.infra.failures import InfraFailureKind
from tinysoul.llm.failures import LLMFailureKind
from tinysoul.loop.failures import LoopFailureKind
from tinysoul.session.failures import SessionFailureKind
from tinysoul.workspace.failures import WorkspaceFailureKind


@pytest.mark.parametrize(
    ("module", "failure_kind"),
    (
        ("action", ActionFailureKind),
        ("app", AppFailureKind),
        ("context", ContextFailureKind),
        ("home", AgentHomeFailureKind),
        ("infra", InfraFailureKind),
        ("llm", LLMFailureKind),
        ("loop", LoopFailureKind),
        ("session", SessionFailureKind),
        ("workspace", WorkspaceFailureKind),
    ),
)
def test_runtime_failure_kind_values_are_module_qualified(
    module: str,
    failure_kind: type[StrEnum],
) -> None:
    prefix = f"{module}."
    for item in failure_kind:
        assert item.value.startswith(prefix)
        assert item.value != prefix
