"""Agent Home module assembly facade."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from tinysoul.infra.filesystem import TextPrefixRead, read_text_prefix

from .config import AgentHomeSettings
from .errors import (
    AgentHomeContractError,
    AgentHomeIOError,
    AgentHomeInvariantError,
    AgentHomeRuntimeCopyRequired,
)
from .layout import AgentHomeLayout
from .links import (
    HomeLink,
    HomePromptMountLink,
    HomeResourceLink,
    HomeTopLink,
    HomeWhatKind,
    parse_home_link,
)
from .overlay import HomeOverlayManager, HomeOverlayRecord, HomeOverlayState


@dataclass(frozen=True)
class HomeBackgroundEntry:
    """A background entry provided by Agent Home."""

    link: str
    content: str


@dataclass(frozen=True)
class HomeResourceRead:
    """A bounded read result for an Agent Home resource."""

    link: str
    text: str
    truncated: bool
    digest: str


@dataclass(frozen=True)
class HomeResourceMutation:
    """Metadata-only result of an active Home overlay mutation."""

    link: str
    state: HomeOverlayState
    digest: str
    baseline_digest: str
    size: int


class AgentHomeEngine:
    """Own effective Home lookup, runtime mutation, and prompt mount state."""

    def __init__(
        self,
        *,
        layout: AgentHomeLayout,
        overlay: HomeOverlayManager,
        max_read_chars: int,
        max_write_chars: int,
    ) -> None:
        self._layout = layout
        self._overlay = overlay
        self._max_read_chars = max_read_chars
        self._max_write_chars = max_write_chars
        self._prompt_mount_links: frozenset[HomePromptMountLink] | None = None

    @property
    def layout(self) -> AgentHomeLayout:
        return self._layout

    @property
    def original_root(self) -> Path:
        return self._layout.settings.original_root

    @property
    def runtime_root(self) -> Path:
        return self._layout.settings.runtime_root

    def reconcile(self) -> None:
        self._overlay.reconcile()
        self._validate_overlay_semantics()

    def parse_link(self, value: str) -> HomeLink:
        return parse_home_link(value)

    def default_background_entries(self) -> tuple[HomeBackgroundEntry, ...]:
        core = HomeTopLink("agent", "core")
        return (HomeBackgroundEntry(link=str(core), content=self.read_top(core)),)

    def loadable_background_links(self) -> tuple[str, ...]:
        """Return the effective top catalog without materializing runtime copies."""

        self._validate_overlay_semantics()
        relatives = set(self._layout.actual_top_relatives())
        relatives.update(record.relative_path for record in self._overlay.records())
        links = {
            link
            for relative in relatives
            if (link := self._layout.top_link_for_relative(relative)) is not None
            and self._resolve_top_relative(link) is not None
        }
        return tuple(str(link) for link in sorted(links, key=str))

    def read_top(self, link: HomeTopLink | str) -> str:
        parsed = HomeTopLink.parse(link) if isinstance(link, str) else link
        relative = self._resolve_top_relative(parsed)
        if relative is None:
            raise AgentHomeContractError(
                f"Home top-level entry does not exist: {parsed}"
            )
        source = self._layout.source_for_relative(relative)
        if parsed.space == "memory":
            return _read_text(source)
        return _read_text(self._runtime_read_path(str(parsed), relative))

    def read_prompt_mount(self, link: HomePromptMountLink | str) -> str:
        parsed = HomePromptMountLink.parse(link) if isinstance(link, str) else link
        self._require_prompt_mount(parsed)
        relative = self._layout.relative_for_prompt_mount(parsed)
        record = self._overlay.record_for(relative)
        if record is not None and record.state is not HomeOverlayState.DELETED:
            return _read_text(self._layout.runtime_for_relative(relative))
        source = self._layout.source_for_relative(relative)
        if record is not None and record.state is HomeOverlayState.DELETED:
            return ""
        if not source.exists():
            return ""
        if source.is_symlink() or not source.is_file():
            raise AgentHomeInvariantError(
                f"Home prompt mount is not a regular file: {source}"
            )
        return _read_text(self._runtime_read_path(str(parsed), relative))

    def read_resource(
        self,
        link: HomeResourceLink | str,
        *,
        max_chars: int | None = None,
    ) -> HomeResourceRead:
        parsed = self._resource_link(link)
        limit = self._max_read_chars if max_chars is None else max_chars
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise AgentHomeContractError("Home resource read limit must be positive")
        relative = self._layout.relative_for_resource(parsed)
        path = self._runtime_read_path(str(parsed), relative)
        record = self._overlay.record_for(relative)
        if record is None or record.state is HomeOverlayState.DELETED:
            raise AgentHomeInvariantError(
                f"Home resource did not resolve through overlay: {parsed}"
            )
        read = _read_text_prefix(path, limit)
        return HomeResourceRead(
            link=str(parsed),
            text=read.text,
            truncated=read.truncated,
            digest=record.runtime_digest,
        )

    def guidance_for_domain(self, domain: str) -> str | None:
        if not domain:
            return None
        return self._read_optional_prompt_mount(
            HomePromptMountLink("how_domain", domain)
        )

    def guidance_for_action(self, domain: str, action_name: str) -> str | None:
        if not domain or not action_name:
            return None
        action_key = action_name
        prefix = f"{domain}."
        if action_name.startswith(prefix):
            action_key = action_name[len(prefix) :]
        return self._read_optional_prompt_mount(
            HomePromptMountLink("how_action", f"{domain}/{action_key}")
        )

    def reconcile_prompt_mounts(
        self,
        *,
        domains: tuple[str, ...],
        actions: tuple[tuple[str, str], ...],
    ) -> None:
        """Derive logical prompt mounts from the loaded Action Catalog."""

        domain_names = _validated_names(domains, label="Action Catalog domains")
        action_identifiers = _validated_action_identifiers(actions)
        expected = {
            HomePromptMountLink("how_domain", domain)
            for domain in domain_names
        }
        for domain, action_name in action_identifiers:
            if domain not in domain_names or not action_name.startswith(f"{domain}."):
                raise AgentHomeContractError(
                    f"Action Catalog action/domain identity is inconsistent: {action_name}"
                )
            action_key = action_name[len(domain) + 1 :]
            expected.add(
                HomePromptMountLink("how_action", f"{domain}/{action_key}")
            )

        existing_relatives = set(self._layout.actual_prompt_mount_relatives())
        existing_relatives.update(
            record.relative_path
            for record in self._overlay.records()
            if self._layout.prompt_mount_link_for_relative(record.relative_path)
            is not None
        )
        for relative in sorted(existing_relatives):
            link = self._layout.prompt_mount_link_for_relative(relative)
            if link is None or link in expected:
                continue
            record = self._overlay.record_for(relative)
            if record is not None and record.state is HomeOverlayState.DELETED:
                continue
            source = self._layout.source_for_relative(relative)
            if record is not None or source.is_file():
                self._overlay.delete(relative, expected_digest="")

        for link in sorted(expected, key=str):
            relative = self._layout.relative_for_prompt_mount(link)
            record = self._overlay.record_for(relative)
            source = self._layout.source_for_relative(relative)
            if (
                record is not None
                and record.state is HomeOverlayState.DELETED
                and source.is_file()
                and not source.is_symlink()
            ):
                self._overlay.reset_to_actual_copy(relative)

        self._prompt_mount_links = frozenset(expected)
        self._validate_overlay_semantics()

    def ensure_runtime_copy(self, link: HomeLink) -> bool:
        """Materialize one missing runtime file and report whether disk changed."""

        if isinstance(link, HomeTopLink):
            if link.space == "memory":
                return False
            runtime_before = {
                relative: self._layout.runtime_for_relative(relative).is_file()
                for relative in self._layout.relative_candidates_for_top(link)
            }
            relative = self._resolve_top_relative(link)
            if relative is None:
                raise AgentHomeContractError(f"Home top-level entry does not exist: {link}")
            materialized = not runtime_before[relative]
        elif isinstance(link, HomeResourceLink):
            parsed = self._resource_link(link)
            relative = self._layout.relative_for_resource(parsed)
            materialized = not self._layout.runtime_for_relative(relative).is_file()
        else:
            self._require_prompt_mount(link)
            relative = self._layout.relative_for_prompt_mount(link)
            materialized = not self._layout.runtime_for_relative(relative).is_file()
            record = self._overlay.record_for(relative)
            source = self._layout.source_for_relative(relative)
            if (
                (record is not None and record.state is HomeOverlayState.DELETED)
                or (record is None and not source.exists())
            ):
                return False
        self._overlay.ensure_copy(relative)
        return materialized

    def write_resource(
        self,
        link: HomeResourceLink | str,
        text: str,
        *,
        overwrite: bool = False,
        expected_digest: str = "",
    ) -> HomeResourceMutation:
        parsed = self._mutable_resource_link(link)
        self._validate_write_text(text)
        relative = self._layout.relative_for_resource(parsed)
        record = self._overlay.write(
            relative,
            text,
            overwrite=overwrite,
            expected_digest=expected_digest,
        )
        return _mutation(str(parsed), record)

    def patch_resource(
        self,
        link: HomeResourceLink | str,
        *,
        old_text: str,
        new_text: str,
        expected_digest: str = "",
    ) -> HomeResourceMutation:
        parsed = self._mutable_resource_link(link)
        relative = self._layout.relative_for_resource(parsed)
        record = self._overlay.patch(
            relative,
            old_text=old_text,
            new_text=new_text,
            expected_digest=expected_digest,
            max_chars=self._max_write_chars,
        )
        return _mutation(str(parsed), record)

    def delete_resource(
        self,
        link: HomeResourceLink | str,
        *,
        expected_digest: str = "",
    ) -> HomeResourceMutation:
        parsed = self._mutable_resource_link(link)
        relative = self._layout.relative_for_resource(parsed)
        record = self._overlay.delete(relative, expected_digest=expected_digest)
        return _mutation(str(parsed), record)

    def write_top(
        self,
        link: HomeTopLink | str,
        text: str,
        *,
        overwrite: bool = False,
        expected_digest: str = "",
        what_kind: HomeWhatKind | str | None = None,
    ) -> HomeResourceMutation:
        parsed = self._mutable_top_link(link)
        self._validate_write_text(text)
        parsed_kind = _parse_what_kind(what_kind)
        existing = self._resolve_top_relative(parsed)
        if existing is None:
            relative = self._layout.relative_for_new_top(
                parsed,
                what_kind=parsed_kind,
            )
        else:
            if parsed.space != "what" and parsed_kind is not None:
                raise AgentHomeContractError(
                    "Home WHAT classification is valid only for WHAT entries"
                )
            if parsed.space == "what" and parsed_kind is not None:
                current_kind = _what_kind_for_relative(existing)
                if current_kind is not parsed_kind:
                    raise AgentHomeContractError(
                        "Home WHAT classification cannot relocate an existing entry"
                    )
            relative = existing
        record = self._overlay.write(
            relative,
            text,
            overwrite=overwrite,
            expected_digest=expected_digest,
        )
        return _mutation(str(parsed), record)

    def patch_top(
        self,
        link: HomeTopLink | str,
        *,
        old_text: str,
        new_text: str,
        expected_digest: str = "",
    ) -> HomeResourceMutation:
        parsed = self._mutable_top_link(link)
        relative = self._require_top_relative(parsed)
        record = self._overlay.patch(
            relative,
            old_text=old_text,
            new_text=new_text,
            expected_digest=expected_digest,
            max_chars=self._max_write_chars,
        )
        return _mutation(str(parsed), record)

    def delete_top(
        self,
        link: HomeTopLink | str,
        *,
        expected_digest: str = "",
    ) -> HomeResourceMutation:
        parsed = self._mutable_top_link(link)
        if parsed == HomeTopLink("agent", "core"):
            raise AgentHomeContractError("home:agent@core cannot be deleted")
        relative = self._require_top_relative(parsed)
        record = self._overlay.delete(relative, expected_digest=expected_digest)
        return _mutation(str(parsed), record)

    def write_prompt_mount(
        self,
        link: HomePromptMountLink | str,
        text: str,
        *,
        overwrite: bool = False,
        expected_digest: str = "",
    ) -> HomeResourceMutation:
        parsed = HomePromptMountLink.parse(link) if isinstance(link, str) else link
        self._require_prompt_mount(parsed)
        self._validate_write_text(text)
        relative = self._layout.relative_for_prompt_mount(parsed)
        record = self._overlay.write(
            relative,
            text,
            overwrite=overwrite,
            expected_digest=expected_digest,
        )
        return _mutation(str(parsed), record)

    def patch_prompt_mount(
        self,
        link: HomePromptMountLink | str,
        *,
        old_text: str,
        new_text: str,
        expected_digest: str = "",
    ) -> HomeResourceMutation:
        parsed = HomePromptMountLink.parse(link) if isinstance(link, str) else link
        self._require_prompt_mount(parsed)
        relative = self._layout.relative_for_prompt_mount(parsed)
        record = self._overlay.patch(
            relative,
            old_text=old_text,
            new_text=new_text,
            expected_digest=expected_digest,
            max_chars=self._max_write_chars,
        )
        return _mutation(str(parsed), record)

    def _runtime_read_path(self, link: str, relative: str) -> Path:
        record = self._overlay.record_for(relative)
        if record is not None:
            if record.state is HomeOverlayState.DELETED:
                raise AgentHomeContractError(
                    f"Home content was deleted in the active overlay: {link}"
                )
            return self._layout.runtime_for_relative(relative)
        source = self._layout.source_for_relative(relative)
        if source.is_symlink():
            raise AgentHomeInvariantError(
                f"Actual Home content cannot be a symlink: {source}"
            )
        if not source.is_file():
            raise AgentHomeContractError(f"Home content does not exist: {link}")
        raise AgentHomeRuntimeCopyRequired(
            link,
            source_path=source,
            runtime_path=self._layout.runtime_for_relative(relative),
        )

    def _read_optional_prompt_mount(self, link: HomePromptMountLink) -> str | None:
        content = self.read_prompt_mount(link)
        return content if content else None

    def _resolve_top_relative(self, link: HomeTopLink) -> str | None:
        records = {record.relative_path: record for record in self._overlay.records()}
        effective: list[str] = []
        for relative in self._layout.relative_candidates_for_top(link):
            record = records.get(relative)
            source = self._layout.source_for_relative(relative)
            if link.space == "memory":
                if record is not None:
                    raise AgentHomeInvariantError(
                        f"Home MEMORY cannot exist in runtime overlay: {relative}"
                    )
                if source.is_symlink():
                    raise AgentHomeInvariantError(
                        f"Actual Home MEMORY cannot be a symlink: {relative}"
                    )
                if source.is_file():
                    effective.append(relative)
                continue
            if record is not None:
                if record.state is not HomeOverlayState.DELETED:
                    effective.append(relative)
                continue
            if source.is_symlink():
                raise AgentHomeInvariantError(
                    f"Actual Home top content cannot be a symlink: {relative}"
                )
            if source.is_file():
                effective.append(relative)
            elif source.exists():
                raise AgentHomeInvariantError(
                    f"Home top candidate is not a regular file: {relative}"
                )
        if len(effective) > 1:
            raise AgentHomeInvariantError(
                f"Home top-level link has multiple effective files: {link}"
            )
        return effective[0] if effective else None

    def _require_top_relative(self, link: HomeTopLink) -> str:
        relative = self._resolve_top_relative(link)
        if relative is None:
            raise AgentHomeContractError(f"Home top-level entry does not exist: {link}")
        return relative

    def _mutable_top_link(self, link: HomeTopLink | str) -> HomeTopLink:
        parsed = HomeTopLink.parse(link) if isinstance(link, str) else link
        if parsed.space == "memory":
            raise AgentHomeContractError(
                "Historical Home MEMORY is read-only outside Memory Maintenance"
            )
        return parsed

    def _resource_link(
        self,
        link: HomeResourceLink | str,
    ) -> HomeResourceLink:
        parsed_link = parse_home_link(link) if isinstance(link, str) else link
        if not isinstance(parsed_link, HomeResourceLink):
            raise AgentHomeContractError(
                "Home resource operation requires a progressive resource link"
            )
        self._validate_resource_semantics(parsed_link)
        return parsed_link

    def _mutable_resource_link(
        self,
        link: HomeResourceLink | str,
    ) -> HomeResourceLink:
        parsed = self._resource_link(link)
        if _is_top_entry_resource(parsed):
            raise AgentHomeContractError(
                "Top-level Home entries require home.top mutation actions"
            )
        return parsed

    def _validate_resource_semantics(self, link: HomeResourceLink) -> None:
        path = PurePosixPath(link.relative_path)
        memory_name = path.name.upper()
        if memory_name.endswith("_MEMORY.MD"):
            if not (
                link.space == "how"
                and path.name == "SKILL_MEMORY.md"
                and len(path.parts) == 2
            ):
                raise AgentHomeContractError(
                    "Only how/<skill>/SKILL_MEMORY.md runtime memory is allowed"
                )
            skill = HomeTopLink("how", path.parts[0])
            if self._resolve_top_relative(skill) is None:
                raise AgentHomeContractError(
                    f"SKILL_MEMORY.md requires an existing general HOW skill: {skill}"
                )

    def _require_prompt_mount(self, link: HomePromptMountLink) -> None:
        if self._prompt_mount_links is None:
            raise AgentHomeInvariantError(
                "Home prompt mounts have not been bound to the Action Catalog"
            )
        if link not in self._prompt_mount_links:
            raise AgentHomeContractError(
                f"Home prompt mount is not defined by the Action Catalog: {link}"
            )

    def _validate_write_text(self, text: str) -> None:
        if not isinstance(text, str):
            raise AgentHomeContractError("Home write text must be a string")
        if len(text) > self._max_write_chars:
            raise AgentHomeContractError(
                f"Home write exceeds {self._max_write_chars} characters"
            )

    def _validate_overlay_semantics(self) -> None:
        self._validate_actual_special_files()
        for record in self._overlay.records():
            relative = record.relative_path
            parts = PurePosixPath(relative).parts
            if parts and parts[0] == "memory":
                raise AgentHomeInvariantError(
                    f"Home MEMORY cannot exist in runtime overlay: {relative}"
                )
            name = PurePosixPath(relative).name
            if name.upper().endswith("_MEMORY.MD"):
                if not (
                    len(parts) == 3
                    and parts[0] == "how"
                    and parts[2] == "SKILL_MEMORY.md"
                ):
                    raise AgentHomeInvariantError(
                        f"Invalid runtime Home memory file: {relative}"
                    )
                if self._resolve_top_relative(HomeTopLink("how", parts[1])) is None:
                    raise AgentHomeInvariantError(
                        f"Runtime SKILL_MEMORY has no general HOW skill: {relative}"
                    )
            if parts and parts[0] in {"how_domain", "how_action"}:
                if self._layout.prompt_mount_link_for_relative(relative) is None:
                    raise AgentHomeInvariantError(
                        f"Invalid runtime Home prompt mount path: {relative}"
                    )

    def _validate_actual_special_files(self) -> None:
        for path in self.original_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(self.original_root).as_posix()
            parts = PurePosixPath(relative).parts
            if (
                parts
                and parts[0] == "memory"
                and self._layout.top_link_for_relative(relative) is None
            ):
                raise AgentHomeInvariantError(
                    f"Actual Home MEMORY path is invalid: {relative}"
                )
            if path.name.upper().endswith("_MEMORY.MD"):
                raise AgentHomeInvariantError(
                    f"Runtime-only Home memory cannot exist in actual Home: {relative}"
                )


class AgentHomeEngineBuilder:
    """Build an AgentHomeEngine from parsed settings."""

    def __init__(self, settings: AgentHomeSettings) -> None:
        self._settings = settings

    def build(self) -> AgentHomeEngine:
        if not self._settings.original_root.exists():
            raise AgentHomeIOError("Agent Home root does not exist")
        if not self._settings.original_root.is_dir():
            raise AgentHomeIOError("Agent Home root must be a directory")
        overlay = HomeOverlayManager(
            original_root=self._settings.original_root,
            runtime_root=self._settings.runtime_root,
        )
        overlay.initialize()
        engine = AgentHomeEngine(
            layout=AgentHomeLayout(self._settings),
            overlay=overlay,
            max_read_chars=self._settings.max_read_chars,
            max_write_chars=self._settings.max_write_chars,
        )
        engine.reconcile()
        return engine


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise AgentHomeContractError(
            f"Agent Home file is not readable as UTF-8 text: {path}"
        ) from exc
    except OSError as exc:
        raise AgentHomeIOError(f"Failed to read Agent Home file: {exc}") from exc


def _read_text_prefix(path: Path, max_chars: int) -> TextPrefixRead:
    try:
        return read_text_prefix(path, max_chars=max_chars)
    except UnicodeDecodeError as exc:
        raise AgentHomeContractError(
            f"Agent Home file is not readable as UTF-8 text: {path}"
        ) from exc
    except OSError as exc:
        raise AgentHomeIOError(f"Failed to read Agent Home file: {exc}") from exc


def _mutation(link: str, record: HomeOverlayRecord) -> HomeResourceMutation:
    return HomeResourceMutation(
        link=link,
        state=record.state,
        digest=record.runtime_digest,
        baseline_digest=record.baseline_digest,
        size=record.size,
    )


def _is_top_entry_resource(link: HomeResourceLink) -> bool:
    path = PurePosixPath(link.relative_path)
    if link.space in {"agent", "what", "why"} and path.suffix.lower() == ".md":
        return True
    return link.space == "how" and path.name == "SKILL.md"


def _parse_what_kind(value: HomeWhatKind | str | None) -> HomeWhatKind | None:
    if value is None or isinstance(value, HomeWhatKind):
        return value
    if not isinstance(value, str):
        raise AgentHomeContractError("Home WHAT classification must be entity or concept")
    try:
        return HomeWhatKind(value)
    except ValueError as exc:
        raise AgentHomeContractError(
            "Home WHAT classification must be entity or concept"
        ) from exc


def _what_kind_for_relative(relative: str) -> HomeWhatKind | None:
    parts = PurePosixPath(relative).parts
    if len(parts) >= 3 and parts[0] == "what":
        try:
            return HomeWhatKind(parts[1])
        except ValueError:
            return None
    return None


def _validated_names(values: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or any(
        not isinstance(value, str) or not value for value in values
    ):
        raise AgentHomeContractError(f"{label} must contain non-empty strings")
    if len(values) != len(set(values)):
        raise AgentHomeContractError(f"{label} must be unique")
    return values


def _validated_action_identifiers(
    values: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    if not isinstance(values, tuple):
        raise AgentHomeContractError("Action Catalog actions must be a tuple")
    result: list[tuple[str, str]] = []
    for value in values:
        if (
            not isinstance(value, tuple)
            or len(value) != 2
            or any(not isinstance(item, str) or not item for item in value)
        ):
            raise AgentHomeContractError(
                "Action Catalog actions must contain domain/name string pairs"
            )
        result.append(value)
    if len(result) != len(set(result)):
        raise AgentHomeContractError("Action Catalog actions must be unique")
    return tuple(result)
