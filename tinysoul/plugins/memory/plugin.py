"""Memory services and one profile's protected background binding."""

from functools import partial

from tinysoul.kernel.registration import PluginDeclaration, Service
from tinysoul.plugins.session import SessionEngine

from .actions import register_memory_actions
from .background import TargetMemoryBinding, memory_segment_registration
from .engine import MemoryEngine
from .runtime_bridge import RuntimeMemoryBridge


def declare_memory(memory: MemoryEngine, *, target: TargetMemoryBinding | None = None) -> PluginDeclaration:
    return PluginDeclaration(
        "memory", services=(Service(MemoryEngine, memory),), requires=(SessionEngine,),
        segments=(memory_segment_registration(memory, target=target),),
        actions=partial(register_memory_actions, memory=memory, runtime_bridge=RuntimeMemoryBridge()),
    )
