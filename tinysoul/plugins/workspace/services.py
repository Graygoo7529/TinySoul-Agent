"""Current-day Workspace capabilities, excluding lifecycle and physical paths."""

from tinysoul.infra.services import ScopedService, ServiceScope
from .engine import WorkspaceEngine


class WorkspaceService(ScopedService[WorkspaceEngine]):
    def __init__(
        self, owner: WorkspaceEngine, scope: ServiceScope = ServiceScope()
    ) -> None:
        super().__init__(owner, scope)
        self.max_read_chars = owner.settings.max_read_chars
        self.max_write_chars = owner.settings.max_write_chars
        self.analysis_settings = owner.settings.analysis
        self.snapshot = scope.local(owner.snapshot)
        self.inspect = scope.local(owner.inspect)
        self.read_image = scope.local(owner.read_image)
        self.read_document = scope.local(owner.read_document)
        self.set_description = scope.local(owner.set_description)
        self.reconcile = scope.local(owner.reconcile)
        self.load_manifest = scope.local(owner.load_manifest)
        self.read_text = scope.local(owner.read_text)
        self.read_text_range = scope.local(owner.read_text_range)
        self.read_bytes = scope.local(owner.read_bytes)
        self.search = scope.local(owner.search)
        self.write_text = scope.local(owner.write_text)
        self.write_bundle = scope.local(owner.write_bundle)
        self.edit_text = scope.local(owner.edit_text)
        self.mkdir = scope.local(owner.mkdir)
        self.move = scope.local(owner.move)
        self.tag = scope.local(owner.tag)
        self.append_text = scope.local(owner.append_text)
        self.trash_resource = scope.local(owner.trash_resource)
        self.restore_resource = scope.local(owner.restore_resource)
        self.trash_items = scope.local(owner.trash_items)
        self.write_target_exists = scope.local(owner.write_target_exists)
        self.prepare_task_input = scope.local(owner.prepare_task_input)
        self.prepare_analysis_references = scope.local(
            owner.prepare_analysis_references
        )
