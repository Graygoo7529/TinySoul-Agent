"""Action handlers package for TinySoul.

Provides built-in and plugin action handlers organized by cluster type.
All handlers are registered explicitly via ``bootstrap(registry)``.
"""

import importlib
import logging
import pkgutil

from tinysoul.action.framework.registry import ActionRegistry
from tinysoul.infra.capabilities import EnvironmentCapabilities


def bootstrap(
    registry: ActionRegistry | None = None,
    env_caps: EnvironmentCapabilities | None = None,
) -> ActionRegistry:
    """
    Register all built-in action handlers to the given *registry*.

    Discovers action modules under ``tinysoul.action.handlers`` sub-packages
    (internal, cli, script) and invokes their ``register_to(registry)`` function.

    Args:
        registry: Optional registry to use. If None, a new one is created.
        env_caps: Optional environment capabilities. If None, auto-probed.

    Returns:
        The populated registry.
    """
    if registry is None:
        registry = ActionRegistry(env_caps=env_caps)

    import tinysoul.action.handlers as _handlers_pkg

    for _, modname, ispkg in pkgutil.walk_packages(
        _handlers_pkg.__path__, _handlers_pkg.__name__ + "."
    ):
        if ispkg:
            continue
        mod = importlib.import_module(modname)
        register = getattr(mod, "register_to", None)
        if register is not None:
            register(registry)

    skipped = registry.get_skipped()
    if skipped:
        logger = logging.getLogger("tinysoul")
        for name, deps in skipped:
            dep_str = ", ".join(f"{d.type}:{d.name}" for d in deps)
            logger.info("Action '%s' skipped: missing dependencies [%s]", name, dep_str)

    return registry


__all__ = ["bootstrap"]
