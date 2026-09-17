"""Memory services and one profile's protected background binding."""

from functools import partial

from tinysoul.kernel.registration import PluginDeclaration, Service
from tinysoul.plugins.session.services import SessionService

from .actions import register_memory_actions
from .background import TargetMemoryBinding, memory_segment_registration
from .engine import MemoryEngine
from .services import MemoryReadService, MemoryService
from .runtime_bridge import RuntimeMemoryBridge


def declare_memory(memory: MemoryEngine, *, target: TargetMemoryBinding | None = None) -> PluginDeclaration:
    service = MemoryService(memory) if target is None else MemoryReadService(memory)
    return PluginDeclaration(
        "memory", services=(Service(type(service), service),), requires=(SessionService,),
        segments=(memory_segment_registration(service, target=target),),
        actions=partial(register_memory_actions, memory=service, runtime_bridge=RuntimeMemoryBridge()),
    )
