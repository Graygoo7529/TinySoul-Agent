"""Agent Home domain guidance provider."""

from __future__ import annotations

from .engine import AgentHomeEngine


class HomeDomainGuidanceProvider:
    """Provide action-domain HOW text from Agent Home."""

    def __init__(self, home: AgentHomeEngine) -> None:
        self._home = home

    def guidance_for(self, domains: tuple[str, ...]) -> tuple[str, ...]:
        snippets: list[str] = []
        for domain in domains:
            guidance = self._home.guidance_for_domain(domain)
            if guidance:
                snippets.append(guidance)
        return tuple(snippets)
