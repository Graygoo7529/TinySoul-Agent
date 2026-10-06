"""Agent Home skill providers."""

from __future__ import annotations

from tinysoul.kernel.action.tasks import ActionSkillGuidance
from tinysoul.kernel.context.prompts import PromptGuidance
from tinysoul.plugins.home.runtime_bridge import RuntimeAgentHomeBridge

from ..errors import AgentHomeError, AgentHomeRuntimeCopyRequired
from ..services import HomeService


class HomeDomainSkillProvider:
    """Provide domain skill text from Agent Home."""

    def __init__(
        self,
        home: HomeService,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    async def guidance_for(
        self, domains: tuple[str, ...]
    ) -> tuple[PromptGuidance, ...]:
        snippets: list[PromptGuidance] = []
        for domain in domains:
            try:
                guidance = await self._home.guidance_for_domain(domain)
            except AgentHomeRuntimeCopyRequired as exc:
                raise self._runtime_bridge.runtime_copy_required(
                    ref=exc.ref,
                    payload=exc.to_payload(),
                ) from exc
            except AgentHomeError as exc:
                raise self._runtime_bridge.from_home_error(
                    exc,
                    payload={"domain": domain},
                ) from exc
            if guidance:
                snippets.append(
                    PromptGuidance(guidance, f"home:mount/domain/{domain}", "home")
                )
        return tuple(snippets)


class HomeActionSkillProvider:
    """Provide action skill text for nested LLM tasks."""

    def __init__(
        self,
        home: HomeService,
        runtime_bridge: RuntimeAgentHomeBridge | None = None,
    ) -> None:
        self._home = home
        self._runtime_bridge = runtime_bridge or RuntimeAgentHomeBridge()

    async def guidance_for(
        self, *, domain: str, action_name: str
    ) -> ActionSkillGuidance:
        try:
            domain_guidance = await self._home.guidance_for_domain(domain)
            action_guidance = await self._home.guidance_for_action(domain, action_name)
        except AgentHomeRuntimeCopyRequired as exc:
            raise self._runtime_bridge.runtime_copy_required(
                ref=exc.ref,
                payload=exc.to_payload(),
            ) from exc
        except AgentHomeError as exc:
            raise self._runtime_bridge.from_home_error(
                exc,
                payload={"domain": domain, "action_name": action_name},
            ) from exc
        return ActionSkillGuidance(
            domain=(
                PromptGuidance(domain_guidance, f"home:mount/domain/{domain}", "home"),
            )
            if domain_guidance
            else (),
            action=(
                PromptGuidance(
                    action_guidance,
                    f"home:mount/action/{domain}/{action_name.removeprefix(domain + '.')}",
                    "home",
                ),
            )
            if action_guidance
            else (),
        )
