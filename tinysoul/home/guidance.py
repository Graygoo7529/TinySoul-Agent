"""Agent Home HOW providers."""

from __future__ import annotations

from tinysoul.action.llm_action import ActionHow
from tinysoul.runtime.bridge import RuntimeAgentHomeBridge

from .engine import AgentHomeEngine
from .errors import AgentHomeRuntimeCopyRequired


class HomeDomainHowProvider:
    """Provide domain HOW text from Agent Home."""

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
                    payload=exc.to_payload(),
                ) from exc
            if guidance:
                snippets.append(guidance)
        return tuple(snippets)


class HomeActionHowProvider:
    """Provide action HOW text for nested LLM tasks."""

    def __init__(
        self,
        home: AgentHomeEngine,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    def guidance_for(self, *, domain: str, action_name: str) -> ActionHow:
        try:
            domain_guidance = self._home.guidance_for_domain(domain)
            action_guidance = self._home.guidance_for_action(domain, action_name)
        except AgentHomeRuntimeCopyRequired as exc:
            raise self._runtime_bridge.runtime_copy_required(
                link=exc.link,
                payload=exc.to_payload(),
            ) from exc
        return ActionHow(
            domain=(domain_guidance,) if domain_guidance else (),
            action=(action_guidance,) if action_guidance else (),
        )
