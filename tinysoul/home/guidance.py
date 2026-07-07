"""Agent Home domain guidance provider."""

from __future__ import annotations

from tinysoul.runtime.bridge import RuntimeAgentHomeBridge

from .engine import AgentHomeEngine
from .errors import AgentHomeRuntimeCopyRequired


class HomeDomainGuidanceProvider:
    """Provide action-domain HOW text from Agent Home."""

    def __init__(
        self,
        home: AgentHomeEngine,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    def guidance_for(self, domains: tuple[str, ...]) -> tuple[str, ...]:
        snippets: list[str] = []
        for domain in domains:
            try:
                guidance = self._home.guidance_for_domain(domain)
            except AgentHomeRuntimeCopyRequired as exc:
                raise self._runtime_bridge.runtime_copy_required(
                    link=exc.link,
                    payload={
                        "source_path": str(exc.source_path),
                        "runtime_path": str(exc.runtime_path),
                    },
                ) from exc
            if guidance:
                snippets.append(guidance)
        return tuple(snippets)
