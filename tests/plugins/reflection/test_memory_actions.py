from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from tinysoul.kernel.action import ActionCall, ActionExecution, ActionExecutionContext, ActionFramework, ActionResultStatus
from tinysoul.kernel.action.core.loader import ActionCatalogLoader
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import CalendarDay
from tinysoul.plugins.reflection.memory import MemoryReflectionActionController
from tinysoul.plugins.reflection.memory.actions import MemoryReflectionWriteExecutor
from tinysoul.plugins.reflection.resources import maintenance_action_catalog_root
from tinysoul.plugins.memory import MemoryEngine, MemorySettings, EntityMemoryDocument, MemoryStatus
from tinysoul.runtime import RunLevel, RunScope

DAY = CalendarDay.parse("2026-08-05")


async def test_reflection_commits_one_document_and_preserves_it_after_rejected_write(tmp_path: Path) -> None:
    memory = MemoryEngine(settings=MemorySettings(root=tmp_path / "memory"))
    controller = MemoryReflectionActionController(memory=memory)
    controller.begin(target_day=DAY)
    executor = MemoryReflectionWriteExecutor(controller)
    result = await executor.execute(_execution("write_daily", {"markdown": "## Events\n\nReviewed Memory."}), ActionExecutionContext())
    assert result.status is ActionResultStatus.SUCCESS
    assert result.payload["link"] == "memory:daily/2026-08-05"

    invalid = await executor.execute(_execution("write", {
        "memory_link": "memory:entity/missing", "markdown": "invalid document",
    }), ActionExecutionContext())
    assert invalid.status is ActionResultStatus.FAILED
    controller.abort()
    reopened = MemoryEngine(settings=memory.settings)
    assert reopened.read_daily(DAY) is not None
    assert not (memory.root / ".tinysoul" / "transactions").exists()


async def test_reflection_writes_target_before_redirect_and_rejects_redirect_cycle(tmp_path: Path) -> None:
    memory = MemoryEngine(settings=MemorySettings(root=tmp_path / "memory"))
    controller = MemoryReflectionActionController(memory=memory)
    controller.begin(target_day=DAY)
    executor = MemoryReflectionWriteExecutor(controller)
    source = EntityMemoryDocument(cite="source", status=MemoryStatus.ACTIVE,
        created_on=DAY.value, updated_on=DAY.value, content="Original source.")
    target = replace(source, cite="target", content="Replacement entity.")
    redirected = replace(source, status=MemoryStatus.MERGED,
        redirect_to=target.link, content="Merged into memory:entity/target.")
    async def write(document: EntityMemoryDocument):
        return await executor.execute(_execution("write", {
            "memory_link": str(document.link), "markdown": memory.render_document(document),
        }), ActionExecutionContext())

    assert (await write(source)).status is ActionResultStatus.SUCCESS
    assert (await write(redirected)).status is ActionResultStatus.FAILED
    assert memory.read_document(source.link).document == source
    assert (await write(target)).status is ActionResultStatus.SUCCESS
    assert (await write(redirected)).status is ActionResultStatus.SUCCESS
    cycle = replace(target, status=MemoryStatus.MERGED,
        redirect_to=source.link, content="Merged into memory:entity/source.")
    assert (await write(cycle)).status is ActionResultStatus.FAILED
    assert memory.recall(source.link).resolution_chain == (str(source.link), str(target.link))


def _execution(action: str, params: JsonObject) -> ActionExecution:
    name = f"memory_reflection.{action}"
    with maintenance_action_catalog_root() as root:
        spec = ActionCatalogLoader().load(root).get_action(name)
    return ActionExecution(
        action=spec, call=ActionCall("call", name, params, 1),
        framework=ActionFramework("invoke", "batch",
            RunScope().push(RunLevel.TURN, "turn"), "memory_reflection"),
    )
