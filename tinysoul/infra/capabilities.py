"""Environment capabilities and action dependency models.

ActionDependency declares what an action needs to run.
EnvironmentCapabilities probes the current system to see what is available.
Neither is exposed to the LLM — they are framework-level runtime concerns.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class ActionDependency:
    """Declare an external dependency required by an action. LLM-invisible."""

    type: str
    name: str
    constraint: str | None = None
    optional: bool = False

    def __post_init__(self):
        object.__setattr__(
            self, "type", self.type.lower().replace("-", "_")
        )


@dataclass
class EnvironmentCapabilities:
    """Capabilities of the current execution environment.

    Probed at startup (or injected explicitly) and used by ActionRegistry
    to filter out actions whose required dependencies are missing.
    """

    executables: set[str] = field(default_factory=set)
    python_packages: set[str] = field(default_factory=set)
    env_vars: set[str] = field(default_factory=set)
    files: set[str] = field(default_factory=set)

    @classmethod
    def probe(cls) -> EnvironmentCapabilities:
        """Probe the current environment for common tools and capabilities."""
        common_executables = [
            "git",
            "docker",
            "npm",
            "node",
            "python",
            "python3",
            "kimi-cli",
            "claude-code",
            "cursor",
            "gh",
            "aws",
            "kubectl",
        ]

        caps = cls()
        for cmd in common_executables:
            if shutil.which(cmd):
                caps.executables.add(cmd)

        import os

        caps.env_vars = set(os.environ.keys())

        return caps

    def satisfies(self, dep: ActionDependency) -> bool:
        """Check whether the current environment satisfies a single dependency."""
        if dep.type == "executable":
            return dep.name in self.executables
        if dep.type == "python_package":
            return dep.name in self.python_packages
        if dep.type == "env_var":
            return dep.name in self.env_vars
        if dep.type == "file":
            return dep.name in self.files
        return False

    def unsatisfied(self, deps: Iterable[ActionDependency]) -> list[ActionDependency]:
        """Return required dependencies that are not satisfied by the environment."""
        return [
            d for d in deps if not d.optional and not self.satisfies(d)
        ]
