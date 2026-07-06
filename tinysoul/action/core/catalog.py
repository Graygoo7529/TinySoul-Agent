"""Action catalog and catalog views."""

from __future__ import annotations

from collections.abc import Iterable

from .errors import ActionContractError, ActionInvariantError
from .specs import ActionDomainSpec, ActionSpec


class ActionCatalog:
    """Read-only action catalog resolved from domain packages."""

    def __init__(
        self,
        *,
        domains: Iterable[ActionDomainSpec] = (),
        actions: Iterable[ActionSpec] = (),
    ) -> None:
        self._domains: dict[str, ActionDomainSpec] = {}
        self._actions: dict[str, ActionSpec] = {}
        for domain in domains:
            self._register_domain(domain)
        for action in actions:
            self._register_action(action)

    def domains(self) -> tuple[ActionDomainSpec, ...]:
        return tuple(self._domains[name] for name in sorted(self._domains))

    def actions(self) -> tuple[ActionSpec, ...]:
        return tuple(self._actions[name] for name in sorted(self._actions))

    def get_domain(self, domain_name: str) -> ActionDomainSpec:
        try:
            return self._domains[domain_name]
        except KeyError as exc:
            raise ActionContractError(f"Unknown action domain: {domain_name}") from exc

    def get_action(self, action_name: str) -> ActionSpec:
        try:
            return self._actions[action_name]
        except KeyError as exc:
            raise ActionContractError(f"Unknown action: {action_name}") from exc

    def has_domain(self, domain_name: str) -> bool:
        return domain_name in self._domains

    def has_action(self, action_name: str) -> bool:
        return action_name in self._actions

    def actions_in_domain(self, domain_name: str) -> tuple[ActionSpec, ...]:
        self.get_domain(domain_name)
        return tuple(
            action
            for action in self.actions()
            if action.domain == domain_name
        )

    def with_domains(self, domain_names: Iterable[str]) -> "ActionCatalog":
        names = tuple(domain_names)
        domains = tuple(self.get_domain(name) for name in names)
        actions = tuple(
            action
            for action in self.actions()
            if action.domain in set(names)
        )
        return ActionCatalog(domains=domains, actions=actions)

    def with_actions(self, action_names: Iterable[str]) -> "ActionCatalog":
        actions = tuple(self.get_action(name) for name in action_names)
        domain_names = {action.domain for action in actions}
        domains = tuple(self.get_domain(name) for name in sorted(domain_names))
        return ActionCatalog(domains=domains, actions=actions)

    def _register_domain(self, domain: ActionDomainSpec) -> None:
        if domain.name in self._domains:
            raise ActionInvariantError(f"Duplicate action domain: {domain.name}")
        self._domains[domain.name] = domain

    def _register_action(self, action: ActionSpec) -> None:
        if action.name in self._actions:
            raise ActionInvariantError(f"Duplicate action: {action.name}")
        if action.domain not in self._domains:
            raise ActionInvariantError(
                f"Action '{action.name}' references unknown domain: {action.domain}"
            )
        self._actions[action.name] = action
