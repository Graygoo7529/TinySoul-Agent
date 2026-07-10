"""Agent Home integration for lazy BackgroundContext content."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.runtime.bridge import RuntimeAgentHomeBridge

from .engine import AgentHomeEngine
from .errors import AgentHomeError, AgentHomeRuntimeCopyRequired


@dataclass(frozen=True)
class HomeBackgroundContentLoader:
    """Load one Home top-level entry through Runtime recovery semantics."""

    home: AgentHomeEngine
    link: str
    runtime_bridge: RuntimeAgentHomeBridge = RuntimeAgentHomeBridge()

    def load(self) -> str:
        try:
            return self.home.read_top(self.link)
        except AgentHomeRuntimeCopyRequired as exc:
            raise self.runtime_bridge.runtime_copy_required(
                link=exc.link,
                message=str(exc),
                payload=exc.to_payload(),
            ) from exc
        except AgentHomeError as exc:
            raise self.runtime_bridge.from_home_error(
                exc,
                payload={"link": self.link},
            ) from exc
