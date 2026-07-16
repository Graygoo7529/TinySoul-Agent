"""Resource conversion orchestration across worker and Workspace boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import sys
from tempfile import TemporaryDirectory
from typing import cast

from tinysoul.action.backends import (
    ControlledProcessRunner,
    ProcessRequest,
    ProcessStatus,
)
from tinysoul.action import ActionExecutionControl
from tinysoul.infra import (
    FilesystemBoundaryError,
    JsonObject,
    dumps_json,
    resolve_under_root,
    to_json_object,
)
from tinysoul.workspace import (
    WorkspaceBundleWrite,
    WorkspaceEngine,
    WorkspaceLink,
    WorkspaceRetention,
)

from .config import ResourceSettings
from .errors import (
    ResourceContractError,
    ResourceInvariantError,
    ResourceProcessingError,
    ResourceProcessTimeout,
)
from .models import (
    ResourceContentStatus,
    ResourceConversionResult,
    ResourceConverter,
)


_MAX_WORKER_STDOUT = 64_000
_MAX_WORKER_STDERR = 8_000
_MAX_RESULT_LINKS = 16
_MAX_WARNINGS = 20


@dataclass(frozen=True)
class _WorkerAsset:
    file: str
    link: str
    size: int


@dataclass(frozen=True)
class _WorkerResult:
    markdown_file: str
    assets: tuple[_WorkerAsset, ...]
    content_status: ResourceContentStatus
    visual_reference_links: tuple[str, ...]
    warning_codes: tuple[str, ...]


class ResourceConversionService:
    """Convert one Workspace document through a fixed local worker."""

    def __init__(
        self,
        *,
        workspace: WorkspaceEngine,
        settings: ResourceSettings,
        process_runner: ControlledProcessRunner | None = None,
    ) -> None:
        self._workspace = workspace
        self._settings = settings
        self._process_runner = process_runner or ControlledProcessRunner()

    def convert(
        self,
        *,
        converter: ResourceConverter,
        source_link: str,
        target_link: str,
        overwrite: bool,
        expected_source_digest: str,
        expected_target_digest: str,
        owner_turn_id: str,
        control: ActionExecutionControl,
    ) -> ResourceConversionResult:
        self._validate_params(
            source_link=source_link,
            target_link=target_link,
            overwrite=overwrite,
            expected_source_digest=expected_source_digest,
            expected_target_digest=expected_target_digest,
            owner_turn_id=owner_turn_id,
        )
        source = self._workspace.read_document(
            source_link,
            max_bytes=self._settings.max_source_bytes,
        )
        if expected_source_digest and source.digest != expected_source_digest:
            raise ResourceProcessingError(
                "Workspace source digest does not match the requested conversion",
                reason="source_digest_mismatch",
                payload={"source_link": source.link},
            )
        self._validate_converter_source(converter, source.suffix)
        target = WorkspaceLink.parse(target_link)
        if target.path.suffix.lower() != ".md":
            raise ResourceContractError("Resource conversion target must end with .md")
        if source.link == str(target):
            raise ResourceContractError("Resource source and target links must differ")
        asset_prefix = _asset_prefix(target)
        if source.link.startswith(asset_prefix + "/"):
            raise ResourceContractError(
                "Resource source cannot be owned by the target asset bundle"
            )
        current_assets = tuple(
            record.link
            for record in self._workspace.snapshot().resources
            if record.link.startswith(asset_prefix + "/")
        )
        if current_assets and not overwrite:
            raise ResourceProcessingError(
                "Resource conversion asset target already exists",
                reason="target_exists",
                payload={"target_link": target_link},
            )

        with TemporaryDirectory(prefix="tinysoul_resource_") as directory:
            root = Path(directory)
            source_path = root / f"source{source.suffix}"
            output_path = root / "output"
            source_path.write_bytes(source.data)
            request = self._worker_request(
                converter=converter,
                source_path=source_path,
                source_suffix=source.suffix,
                output_path=output_path,
                asset_prefix=asset_prefix,
            )
            outcome = self._process_runner.run(
                ProcessRequest(
                    argv=(
                        sys.executable,
                        "-m",
                        "tinysoul.capabilities.resource.worker",
                    ),
                    stdin_text=dumps_json(request),
                    stdout_limit=_MAX_WORKER_STDOUT,
                    stderr_limit=_MAX_WORKER_STDERR,
                ),
                control,
            )
            if outcome.status is ProcessStatus.TIMED_OUT:
                raise ResourceProcessTimeout(
                    "Resource conversion worker timed out",
                    reason="process_timeout",
                )
            if outcome.status is ProcessStatus.CANCELLED:
                raise ResourceProcessTimeout(
                    "Resource conversion worker was cancelled",
                    reason=control.cancel_reason or "cancelled",
                )
            if outcome.status is ProcessStatus.START_FAILED:
                raise ResourceProcessingError(
                    "Resource conversion worker failed to start",
                    reason="process_start_failed",
                    payload={"error_type": outcome.error_type},
                )
            response = _worker_response(outcome.stdout)
            if outcome.exit_code != 0 or not _required_bool(response, "ok"):
                reason = _optional_string(response, "reason") or "worker_failed"
                raise ResourceProcessingError(
                    _optional_string(response, "message")
                    or "Resource conversion worker failed",
                    reason=reason,
                    payload={"converter": converter.value},
                )
            worker = _parse_worker_result(
                response,
                output_path=output_path,
                asset_prefix=asset_prefix,
                settings=self._settings,
            )
            writes = self._bundle_writes(
                worker,
                output_path=output_path,
                target_link=str(target),
                overwrite=overwrite,
                expected_target_digest=expected_target_digest,
                retention=source.retention,
                owner_turn_id=owner_turn_id,
            )
            observed = self._workspace.inspect(source.link)
            if observed.digest != source.digest:
                raise ResourceProcessingError(
                    "Workspace source changed during conversion",
                    reason="source_changed",
                    payload={"source_link": source.link},
                )
            new_links = {item.link for item in writes[1:]}
            stale_assets = (
                tuple(link for link in current_assets if link not in new_links)
                if overwrite
                else ()
            )
            committed = self._workspace.write_bundle(
                writes,
                delete_links=stale_assets,
            )

        return ResourceConversionResult(
            source_link=source.link,
            markdown_link=str(target),
            converter=converter,
            content_status=worker.content_status,
            manifest=committed.manifest,
            records=committed.records,
            visual_reference_links=worker.visual_reference_links,
            warning_codes=worker.warning_codes,
        )

    def _worker_request(
        self,
        *,
        converter: ResourceConverter,
        source_path: Path,
        source_suffix: str,
        output_path: Path,
        asset_prefix: str,
    ) -> JsonObject:
        action_settings = (
            self._settings.convert_with_markitdown
            if converter is ResourceConverter.MARKITDOWN
            else self._settings.convert_with_pypdf
        )
        return {
            "converter": converter.value,
            "source_path": str(source_path),
            "source_suffix": source_suffix,
            "output_path": str(output_path),
            "asset_link_prefix": asset_prefix,
            "max_output_chars": self._settings.max_output_chars,
            "max_assets": self._settings.max_assets,
            "max_total_asset_bytes": self._settings.max_total_asset_bytes,
            "max_pdf_pages": self._settings.max_pdf_pages,
            "render_pdf_pages": self._settings.render_pdf_pages.value,
            "extract_images": action_settings.extract_images,
            "extract_attachments": action_settings.extract_attachments,
        }

    def _bundle_writes(
        self,
        worker: _WorkerResult,
        *,
        output_path: Path,
        target_link: str,
        overwrite: bool,
        expected_target_digest: str,
        retention: WorkspaceRetention,
        owner_turn_id: str,
    ) -> tuple[WorkspaceBundleWrite, ...]:
        markdown_path = _worker_path(output_path, worker.markdown_file)
        try:
            markdown = markdown_path.read_bytes()
        except OSError as exc:
            raise ResourceInvariantError("Worker Markdown output is unreadable") from exc
        try:
            text = markdown.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ResourceInvariantError("Worker Markdown output is not UTF-8") from exc
        if not text.strip() or len(text) > self._settings.max_output_chars:
            raise ResourceInvariantError("Worker Markdown output violates limits")
        writes = [
            WorkspaceBundleWrite(
                link=target_link,
                data=markdown,
                overwrite=overwrite,
                expected_digest=expected_target_digest,
                retention=retention,
                owner_turn_id=owner_turn_id,
            )
        ]
        total_asset_bytes = 0
        for asset in worker.assets:
            path = _worker_path(output_path, asset.file)
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise ResourceInvariantError("Worker asset is unreadable") from exc
            if len(data) != asset.size:
                raise ResourceInvariantError("Worker asset size does not match manifest")
            total_asset_bytes += len(data)
            if total_asset_bytes > self._settings.max_total_asset_bytes:
                raise ResourceInvariantError("Worker assets exceed configured byte limit")
            writes.append(
                WorkspaceBundleWrite(
                    link=asset.link,
                    data=data,
                    overwrite=overwrite,
                    retention=retention,
                    owner_turn_id=owner_turn_id,
                )
            )
        return tuple(writes)

    def _validate_converter_source(
        self,
        converter: ResourceConverter,
        suffix: str,
    ) -> None:
        normalized = suffix.removeprefix(".").lower()
        if converter is ResourceConverter.PYPDF and normalized != "pdf":
            raise ResourceProcessingError(
                "pypdf conversion only accepts PDF documents",
                reason="unsupported_format",
                payload={"suffix": suffix},
            )
        if (
            converter is ResourceConverter.MARKITDOWN
            and normalized not in self._settings.convert_with_markitdown.formats
        ):
            raise ResourceProcessingError(
                "MarkItDown format is disabled or unsupported",
                reason="unsupported_format",
                payload={"suffix": suffix},
            )

    @staticmethod
    def _validate_params(
        *,
        source_link: str,
        target_link: str,
        overwrite: bool,
        expected_source_digest: str,
        expected_target_digest: str,
        owner_turn_id: str,
    ) -> None:
        WorkspaceLink.parse(source_link)
        WorkspaceLink.parse(target_link)
        if not isinstance(overwrite, bool):
            raise ResourceContractError("Resource overwrite must be boolean")
        if not isinstance(expected_source_digest, str) or not isinstance(
            expected_target_digest, str
        ):
            raise ResourceContractError("Resource digest guards must be strings")
        if expected_target_digest and not overwrite:
            raise ResourceContractError(
                "Expected target digest requires overwrite=true"
            )
        if not isinstance(owner_turn_id, str):
            raise ResourceContractError("Resource owner turn id must be a string")


def _asset_prefix(target: WorkspaceLink) -> str:
    path = target.path
    stem = path.stem
    parent = path.parent
    relative = PurePosixPath(f"{stem}.assets")
    if str(parent) != ".":
        relative = parent / relative
    return str(WorkspaceLink.from_relative_path(relative.as_posix()))


def _worker_response(value: str) -> JsonObject:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ResourceProcessingError(
            "Resource worker returned invalid JSON",
            reason="invalid_worker_response",
        ) from exc
    try:
        return to_json_object(parsed)
    except (TypeError, ValueError) as exc:
        raise ResourceProcessingError(
            "Resource worker response must be a JSON object",
            reason="invalid_worker_response",
        ) from exc


def _parse_worker_result(
    value: JsonObject,
    *,
    output_path: Path,
    asset_prefix: str,
    settings: ResourceSettings,
) -> _WorkerResult:
    markdown_file = _required_string(value, "markdown_file")
    _worker_path(output_path, markdown_file)
    raw_assets = value.get("assets")
    if not isinstance(raw_assets, list) or len(raw_assets) > settings.max_assets:
        raise ResourceInvariantError("Worker asset manifest is invalid")
    assets: list[_WorkerAsset] = []
    for item in raw_assets:
        if not isinstance(item, dict):
            raise ResourceInvariantError("Worker asset entry is invalid")
        typed = cast(dict[str, object], item)
        file = _required_string(typed, "file")
        link = _required_string(typed, "link")
        size = typed.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ResourceInvariantError("Worker asset size is invalid")
        _worker_path(output_path, file)
        parsed_link = WorkspaceLink.parse(link)
        if not str(parsed_link).startswith(asset_prefix + "/"):
            raise ResourceInvariantError("Worker asset link escapes target prefix")
        assets.append(_WorkerAsset(file=file, link=link, size=size))
    try:
        status = ResourceContentStatus(_required_string(value, "content_status"))
    except ValueError as exc:
        raise ResourceInvariantError("Worker content status is invalid") from exc
    visual = _bounded_strings(
        value.get("visual_reference_links"),
        limit=_MAX_RESULT_LINKS,
        label="visual links",
    )
    asset_links = {asset.link for asset in assets}
    if any(link not in asset_links for link in visual):
        raise ResourceInvariantError("Worker visual link is not a generated asset")
    warnings = _bounded_strings(
        value.get("warning_codes"),
        limit=_MAX_WARNINGS,
        label="warnings",
    )
    return _WorkerResult(
        markdown_file=markdown_file,
        assets=tuple(assets),
        content_status=status,
        visual_reference_links=visual,
        warning_codes=warnings,
    )


def _worker_path(root: Path, relative: str) -> Path:
    if Path(relative).is_absolute():
        raise ResourceInvariantError("Worker output path must be relative")
    try:
        return resolve_under_root(root, relative)
    except FilesystemBoundaryError as exc:
        raise ResourceInvariantError("Worker output path escapes staging root") from exc


def _required_string(value: Mapping[str, object], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise ResourceInvariantError(f"Worker response field is invalid: {name}")
    return item


def _optional_string(value: JsonObject, name: str) -> str:
    item = value.get(name, "")
    return item if isinstance(item, str) else ""


def _required_bool(value: JsonObject, name: str) -> bool:
    item = value.get(name)
    if not isinstance(item, bool):
        raise ResourceProcessingError(
            "Resource worker response is missing completion status",
            reason="invalid_worker_response",
        )
    return item


def _bounded_strings(value: object, *, limit: int, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > limit:
        raise ResourceInvariantError(f"Worker {label} are invalid")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ResourceInvariantError(f"Worker {label} are invalid")
        if item not in result:
            result.append(item)
    return tuple(result)
