"""Memory capabilities selected by the consumer's execution scenario."""

from tinysoul.infra.services import ScopedService, ServiceScope
from .engine import MemoryEngine


class MemoryReadService(ScopedService[MemoryEngine]):
    """Memory discovery and Context projection without persistence changes."""

    def __init__(self, owner: MemoryEngine, scope: ServiceScope = ServiceScope()) -> None:
        super().__init__(owner, scope)
        self.active_day = scope.local(owner.active_day)
        self.read_active = scope.local(owner.read_active)
        self.inspect = scope.remote(owner.inspect)
        self.recall = scope.local(owner.recall)
        self.latest_daily_before = scope.local(owner.latest_daily_before)


class MemoryService(MemoryReadService):
    """Normal work can additionally patch active memory."""

    def __init__(self, owner: MemoryEngine, scope: ServiceScope = ServiceScope()) -> None:
        super().__init__(owner, scope)
        self.patch_active = scope.local(owner.patch_active)


class MemoryKnowledgeService(ScopedService[MemoryEngine]):
    """Persistent writes granted to Memory Reflection only."""

    def __init__(self, owner: MemoryEngine, scope: ServiceScope = ServiceScope()) -> None:
        super().__init__(owner, scope)
        self.write_document = scope.local(owner.write_document)
        self.write_markdown = scope.local(owner.write_markdown)
