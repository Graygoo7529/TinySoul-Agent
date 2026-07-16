from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
from time import monotonic
import zipfile

from pypdf import PdfWriter
from PIL import Image
import pytest

from tinysoul.action import (
    ActionCall,
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutionControl,
    ActionFramework,
    ActionResultStatus,
    builtin_action_catalog_root,
)
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.action.backends import (
    ControlledProcessRunner,
    ProcessOutcome,
    ProcessRequest,
    ProcessStatus,
)
from tinysoul.capabilities import parse_capabilities_settings
from tinysoul.capabilities.resource.actions import (
    RESOURCE_PYPDF_ACTION,
    ResourceConversionExecutor,
    register_resource_actions,
)
from tinysoul.capabilities.resource.config import (
    MarkItDownConversionSettings,
    PdfConversionSettings,
    PdfPageRenderMode,
    ResourceSettings,
)
from tinysoul.capabilities.resource.dependencies import require_resource_dependencies
from tinysoul.capabilities.resource.errors import (
    ResourceContractError,
    ResourceProcessingError,
)
from tinysoul.capabilities.resource.models import (
    ResourceContentStatus,
    ResourceConverter,
)
from tinysoul.capabilities.resource.service import ResourceConversionService
from tinysoul.infra import DependencyCheck, DependencyChecker, DependencyRequirement
from tinysoul.infra.config import ConfigError
from tinysoul.runtime import RunScope, SignalBus
from tinysoul.workspace import WorkspaceEngineBuilder, WorkspaceSettings


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII="
)


def test_resource_config_parses_split_action_settings() -> None:
    settings = parse_capabilities_settings(
        {
            "resource": {
                "max_pdf_pages": 12,
                "convert_with_markitdown": {
                    "enabled": True,
                    "formats": ["docx"],
                    "extract_images": False,
                },
                "convert_with_pypdf": {"enabled": False},
            }
        }
    ).resource

    assert settings.max_pdf_pages == 12
    assert settings.convert_with_markitdown.formats == ("docx",)
    assert settings.convert_with_markitdown.extract_images is False
    assert settings.convert_with_pypdf.enabled is False


def test_resource_config_reports_exact_nested_key() -> None:
    with pytest.raises(ConfigError) as error:
        parse_capabilities_settings(
            {
                "resource": {
                    "convert_with_pypdf": {"extract_images": "yes"},
                }
            }
        )

    assert (
        error.value.key
        == "capabilities.resource.convert_with_pypdf.extract_images"
    )


def test_resource_config_rejects_nested_unknown_key() -> None:
    with pytest.raises(ConfigError) as error:
        parse_capabilities_settings(
            {
                "resource": {
                    "convert_with_markitdown": {"fallback": True},
                }
            }
        )

    assert (
        error.value.key
        == "capabilities.resource.convert_with_markitdown.fallback"
    )


def test_markitdown_conversion_commits_markdown_and_docx_image(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    source = workspace.root / "incoming" / "report.docx"
    _write_docx(source)
    workspace.reconcile()
    service = ResourceConversionService(
        workspace=workspace,
        settings=ResourceSettings(),
    )

    result = service.convert(
        converter=ResourceConverter.MARKITDOWN,
        source_link="workspace:incoming/report.docx",
        target_link="workspace:converted/report.md",
        overwrite=False,
        expected_source_digest="",
        expected_target_digest="",
        owner_turn_id="turn_1",
        control=ActionExecutionControl(deadline=monotonic() + 30),
    )

    markdown = workspace.read_text(
        "workspace:converted/report.md",
        max_chars=10000,
    ).text
    assert "Hello TinySoul" in markdown
    assert "workspace:converted/report.assets/image-001.png" in markdown
    assert workspace.inspect(
        "workspace:converted/report.assets/image-001.png"
    ).media_type == "image/png"
    assert result.content_status is ResourceContentStatus.PARTIAL
    assert result.manifest.revision == 2


def test_pypdf_conversion_renders_blank_page_as_workspace_image(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    source = workspace.root / "incoming" / "blank.pdf"
    source.parent.mkdir(parents=True)
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with source.open("wb") as handle:
        writer.write(handle)
    workspace.reconcile()
    service = ResourceConversionService(
        workspace=workspace,
        settings=ResourceSettings(),
    )

    result = service.convert(
        converter=ResourceConverter.PYPDF,
        source_link="workspace:incoming/blank.pdf",
        target_link="workspace:converted/blank.md",
        overwrite=False,
        expected_source_digest="",
        expected_target_digest="",
        owner_turn_id="turn_1",
        control=ActionExecutionControl(deadline=monotonic() + 30),
    )

    markdown = workspace.read_text(
        "workspace:converted/blank.md",
        max_chars=10000,
    ).text
    assert "No usable text was extracted" in markdown
    assert "workspace:converted/blank.assets/page-001.png" in markdown
    assert result.content_status is ResourceContentStatus.VISUAL_ONLY
    assert result.visual_reference_links == (
        "workspace:converted/blank.assets/page-001.png",
    )


def test_blank_pdf_without_page_rendering_does_not_commit_placeholder_only_output(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    source = workspace.root / "incoming" / "blank.pdf"
    source.parent.mkdir(parents=True)
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with source.open("wb") as handle:
        writer.write(handle)
    workspace.reconcile()
    service = ResourceConversionService(
        workspace=workspace,
        settings=ResourceSettings(render_pdf_pages=PdfPageRenderMode.DISABLED),
    )

    with pytest.raises(ResourceProcessingError) as error:
        service.convert(
            converter=ResourceConverter.PYPDF,
            source_link="workspace:incoming/blank.pdf",
            target_link="workspace:converted/blank.md",
            overwrite=False,
            expected_source_digest="",
            expected_target_digest="",
            owner_turn_id="turn_1",
            control=ActionExecutionControl(deadline=monotonic() + 30),
        )

    assert error.value.reason == "no_usable_output"
    assert not (workspace.root / "converted" / "blank.md").exists()


def test_conversion_target_cannot_claim_its_source_as_a_stale_asset(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    source = workspace.root / "converted" / "report.assets" / "source.pdf"
    source.parent.mkdir(parents=True)
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with source.open("wb") as handle:
        writer.write(handle)
    workspace.reconcile()
    service = ResourceConversionService(
        workspace=workspace,
        settings=ResourceSettings(),
    )

    with pytest.raises(ResourceContractError, match="target asset bundle"):
        service.convert(
            converter=ResourceConverter.PYPDF,
            source_link="workspace:converted/report.assets/source.pdf",
            target_link="workspace:converted/report.md",
            overwrite=True,
            expected_source_digest="",
            expected_target_digest="",
            owner_turn_id="turn_1",
            control=ActionExecutionControl(deadline=monotonic() + 30),
        )

    assert source.is_file()


@pytest.mark.parametrize(
    ("settings", "reason"),
    (
        (
            ResourceSettings(
                max_assets=1,
                render_pdf_pages=PdfPageRenderMode.DISABLED,
            ),
            "asset_count_limit_exceeded",
        ),
        (
            ResourceSettings(
                max_total_asset_bytes=1,
                render_pdf_pages=PdfPageRenderMode.DISABLED,
            ),
            "asset_bytes_limit_exceeded",
        ),
    ),
)
def test_pypdf_asset_limits_fail_without_committing_partial_output(
    local_tmp: Path,
    settings: ResourceSettings,
    reason: str,
) -> None:
    workspace = _workspace(local_tmp)
    source = workspace.root / "incoming" / "images.pdf"
    _write_image_pdf(source)
    before = workspace.reconcile().manifest
    service = ResourceConversionService(workspace=workspace, settings=settings)

    with pytest.raises(ResourceProcessingError) as error:
        service.convert(
            converter=ResourceConverter.PYPDF,
            source_link="workspace:incoming/images.pdf",
            target_link="workspace:converted/images.md",
            overwrite=False,
            expected_source_digest="",
            expected_target_digest="",
            owner_turn_id="turn_1",
            control=ActionExecutionControl(deadline=monotonic() + 30),
        )

    assert error.value.reason == reason
    assert workspace.snapshot() == before
    assert not (workspace.root / "converted" / "images.md").exists()


def test_enabled_resource_dependency_must_be_available() -> None:
    class MissingDependencyChecker(DependencyChecker):
        def check_all(
            self,
            requirements: tuple[DependencyRequirement, ...],
        ) -> tuple[DependencyCheck, ...]:
            requirement = requirements[0]
            return (
                DependencyCheck(
                    requirement_id=requirement.id,
                    available=False,
                    missing_distributions=(requirement.distributions[0],),
                ),
            )

    with pytest.raises(ConfigError) as error:
        require_resource_dependencies(
            ResourceSettings(),
            checker=MissingDependencyChecker(),
        )

    assert error.value.key == "capabilities.dependencies.resource.markitdown"


def test_disabled_resource_actions_are_absent_from_effective_catalog(
    local_tmp: Path,
) -> None:
    catalog_root = local_tmp / "catalog"
    with builtin_action_catalog_root() as package_catalog:
        shutil.copytree(package_catalog / "resource", catalog_root / "resource")
    settings = ResourceSettings(
        convert_with_markitdown=MarkItDownConversionSettings(enabled=False),
        convert_with_pypdf=PdfConversionSettings(enabled=False),
    )
    engine = register_resource_actions(
        ActionEngineBuilder(catalog_root),
        settings=settings,
        workspace=_workspace(local_tmp),
        bus=SignalBus(),
    ).build()

    assert "resource" not in engine.domain_names()
    assert engine.action_identifiers() == ()


def test_resource_executor_returns_metadata_and_emits_one_workspace_signal(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    source = workspace.root / "incoming" / "blank.pdf"
    source.parent.mkdir(parents=True)
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with source.open("wb") as handle:
        writer.write(handle)
    workspace.reconcile()
    bus = SignalBus()
    service = ResourceConversionService(
        workspace=workspace,
        settings=ResourceSettings(),
    )
    executor = ResourceConversionExecutor(
        converter=ResourceConverter.PYPDF,
        service=service,
        bus=bus,
    )
    with builtin_action_catalog_root() as root:
        action = ActionCatalogLoader().load(root).get_action(RESOURCE_PYPDF_ACTION)
    execution = ActionExecution(
        action=action,
        call=ActionCall(
            call_id="call_1",
            action_name=RESOURCE_PYPDF_ACTION,
            params={
                "source_link": "workspace:incoming/blank.pdf",
                "target_link": "workspace:converted/blank.md",
            },
            sequence=1,
        ),
        framework=ActionFramework(
            invoke_id="invoke_1",
            batch_id="batch_1",
            scope=RunScope(),
            domain="resource",
            turn_id="turn_1",
        ),
    )

    result = executor.execute(
        execution,
        ActionExecutionContext(
            control=ActionExecutionControl(deadline=monotonic() + 30),
        ),
    )

    assert result.status is ActionResultStatus.SUCCESS
    assert result.payload["markdown_link"] == "workspace:converted/blank.md"
    assert result.payload["content_status"] == "visual_only"
    assert "markdown" not in result.payload
    signals = bus.consume()
    assert len(signals) == 1
    assert signals[0].name == "context.workspace.sync"
    assert signals[0].source == RESOURCE_PYPDF_ACTION


def test_resource_executor_cancellation_after_worker_prevents_commit_and_signal(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    source = workspace.root / "incoming" / "blank.pdf"
    source.parent.mkdir(parents=True)
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with source.open("wb") as handle:
        writer.write(handle)
    before = workspace.reconcile().manifest
    control = ActionExecutionControl(deadline=monotonic() + 30)
    service = ResourceConversionService(
        workspace=workspace,
        settings=ResourceSettings(),
        process_runner=_CompletedCancellingRunner(),
    )
    bus = SignalBus()
    executor = ResourceConversionExecutor(
        converter=ResourceConverter.PYPDF,
        service=service,
        bus=bus,
    )

    result = executor.execute(
        _resource_execution(),
        ActionExecutionContext(control=control),
    )

    assert result.status is ActionResultStatus.TIMEOUT
    assert result.frame_data["reason"] == "runtime_transfer"
    assert workspace.snapshot() == before
    assert not (workspace.root / "converted" / "blank.md").exists()
    assert bus.consume() == ()


def test_resource_executor_maps_invalid_worker_manifest_to_local_failure(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    source = workspace.root / "incoming" / "blank.pdf"
    source.parent.mkdir(parents=True)
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with source.open("wb") as handle:
        writer.write(handle)
    before = workspace.reconcile().manifest
    bus = SignalBus()
    executor = ResourceConversionExecutor(
        converter=ResourceConverter.PYPDF,
        service=ResourceConversionService(
            workspace=workspace,
            settings=ResourceSettings(),
            process_runner=_InvalidManifestRunner(),
        ),
        bus=bus,
    )

    result = executor.execute(
        _resource_execution(),
        ActionExecutionContext(
            control=ActionExecutionControl(deadline=monotonic() + 30),
        ),
    )

    assert result.status is ActionResultStatus.FAILED
    assert result.frame_data["reason"] == "worker_protocol_invalid"
    assert workspace.snapshot() == before
    assert bus.consume() == ()


class _CompletedCancellingRunner(ControlledProcessRunner):
    def run(
        self,
        request: ProcessRequest,
        control: ActionExecutionControl,
    ) -> ProcessOutcome:
        response = _stage_worker_markdown(request)
        control.request_cancel("runtime_transfer")
        return ProcessOutcome(
            status=ProcessStatus.COMPLETED,
            exit_code=0,
            stdout=json.dumps(response),
        )


class _InvalidManifestRunner(ControlledProcessRunner):
    def run(
        self,
        request: ProcessRequest,
        control: ActionExecutionControl,
    ) -> ProcessOutcome:
        del request, control
        return ProcessOutcome(
            status=ProcessStatus.COMPLETED,
            exit_code=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "markdown_file": "../escape.md",
                    "assets": [],
                    "content_status": "complete",
                    "visual_reference_links": [],
                    "warning_codes": [],
                }
            ),
        )


def _stage_worker_markdown(request: ProcessRequest) -> dict[str, object]:
    assert request.stdin_text is not None
    payload = json.loads(request.stdin_text)
    output = Path(payload["output_path"])
    output.mkdir(parents=True)
    (output / "document.md").write_text("# Converted\n", encoding="utf-8")
    return {
        "ok": True,
        "markdown_file": "document.md",
        "assets": [],
        "content_status": "complete",
        "visual_reference_links": [],
        "warning_codes": [],
    }


def _resource_execution() -> ActionExecution:
    with builtin_action_catalog_root() as root:
        action = ActionCatalogLoader().load(root).get_action(RESOURCE_PYPDF_ACTION)
    return ActionExecution(
        action=action,
        call=ActionCall(
            call_id="call_1",
            action_name=RESOURCE_PYPDF_ACTION,
            params={
                "source_link": "workspace:incoming/blank.pdf",
                "target_link": "workspace:converted/blank.md",
            },
            sequence=1,
        ),
        framework=ActionFramework(
            invoke_id="invoke_1",
            batch_id="batch_1",
            scope=RunScope(),
            domain="resource",
            turn_id="turn_1",
        ),
    )


def _workspace(root: Path):
    return WorkspaceEngineBuilder(
        WorkspaceSettings(root=(root / "workspace").resolve(), max_files=100)
    ).build()


def _write_docx(path: Path) -> None:
    path.parent.mkdir(parents=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
              <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
              <Default Extension="xml" ContentType="application/xml"/>
              <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
            </Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
            </Relationships>""",
        )
        archive.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>Hello TinySoul</w:t></w:r></w:p></w:body>
            </w:document>""",
        )
        archive.writestr("word/media/image1.png", _PNG)


def _write_image_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True)
    first = Image.new("RGB", (10, 10), "red")
    second = Image.new("RGB", (10, 10), "blue")
    try:
        first.save(path, "PDF", save_all=True, append_images=[second])
    finally:
        first.close()
        second.close()
