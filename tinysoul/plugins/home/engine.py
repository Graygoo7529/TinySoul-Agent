"""Agent Home module assembly facade."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath

from tinysoul.infra.filesystem import TextPrefixRead, file_digest, read_text_prefix
from tinysoul.infra.json import JsonObject
from tinysoul.infra.paging import PageOptions
from tinysoul.infra.references import (
    ReferenceError,
    ReferenceResolver,
    ResourceTarget,
    markdown_references,
    relative_reference,
)
from tinysoul.kernel.retrieval.contracts import (
    AttributeField,
    AttributeFilters,
    AttributeKind,
    BacklinksSource,
    ContentCoverage,
    ContentUnit,
    DirectorySource,
    DocumentQuery,
    EvidenceKind,
    QuerySource,
    RefsSource,
    RetrievalRequest,
    SearchCandidate,
    SearchEvidence,
    SearchFailure,
    SearchFailureKind,
    TextQuery,
)
from tinysoul.kernel.retrieval.disclosure import (
    DisclosureHint,
    InspectPage,
    content_units,
    fragment_range,
    inspect_document,
    range_evidence,
)
from tinysoul.kernel.retrieval.operations import SearchCorpus
from tinysoul.prompts.plugins import home as prompt_text

HOME_SEARCH_FILTERS = AttributeFilters(
    (
        AttributeField("space"),
        AttributeField("file_type"),
        AttributeField("resource_types", AttributeKind.TEXT_SET),
    )
)

from .config import AgentHomeSettings, HomeSearchSettings
from .content.layout import AgentHomeLayout
from .errors import (
    AgentHomeContractError,
    AgentHomeInvariantError,
    AgentHomeIOError,
    AgentHomeNotFoundError,
    AgentHomeRuntimeCopyRequired,
)
from .overlay import HomeOverlayManager, HomeOverlayRecord, HomeOverlayState
from .refs import (
    HomePromptMountRef,
    HomeRef,
    HomeResourceRef,
    HomeTopRef,
    parse_home_ref,
)
from .review import (
    HomeReviewPending,
    HomeReviewResolution,
    HomeReviewResolveOutcome,
    HomeReviewService,
    HomeReviewSnapshot,
)
from .skills.metadata import (
    SKILL_FRONTMATTER_MAX_CHARS,
    HomeSkillMetadata,
    parse_home_skill_metadata,
)

_DEFAULT_BACKGROUND_TOP_REFS = (
    HomeTopRef("agent", "AGENT"),
    HomeTopRef("agent", "identity/identity"),
    HomeTopRef("agent", "identity/soul"),
    HomeTopRef("agent", "context/background"),
    HomeTopRef("agent", "context/turn-trace"),
    HomeTopRef("agent", "context/working"),
    HomeTopRef("agent", "user/user"),
)


@dataclass(frozen=True)
class HomeBackgroundEntry:
    """A background entry provided by Agent Home."""

    ref: str
    content: str


@dataclass(frozen=True)
class HomeResourceRead:
    """A bounded read result for an Agent Home resource."""

    ref: str
    text: str
    truncated: bool
    digest: str


@dataclass(frozen=True)
class HomeResourceMutation:
    """Metadata-only result of an active Home overlay mutation."""

    ref: str
    state: HomeOverlayState
    digest: str
    baseline_digest: str
    size: int


class AgentHomeEngine:
    """Own effective Home lookup, runtime mutation, review, and prompt mounts."""

    def __init__(
        self,
        *,
        layout: AgentHomeLayout,
        overlay: HomeOverlayManager,
        max_read_chars: int,
        max_write_chars: int,
        skill_catalog_max_chars: int,
        search_settings: HomeSearchSettings,
    ) -> None:
        self._layout = layout
        self._overlay = overlay
        self._max_read_chars = max_read_chars
        self._max_write_chars = max_write_chars
        self._skill_catalog_max_chars = skill_catalog_max_chars
        self._prompt_mount_refs: frozenset[HomePromptMountRef] | None = None
        self._review = HomeReviewService(
            layout=layout,
            overlay=overlay,
            max_preview_chars=max_read_chars,
            max_write_chars=max_write_chars,
        )
        self._search_settings = search_settings

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

    def review_pending(self) -> HomeReviewPending:
        """Return reviewable Home work without cleaning active records."""

        self._validate_overlay_semantics()
        return self._review.pending()

    def review_snapshot(self) -> HomeReviewSnapshot:
        """Return bounded, token-bound active Home reviews."""

        self._validate_overlay_semantics()
        return self._review.snapshot()

    def resolve_review(
        self,
        token: str,
        resolution: HomeReviewResolution,
        *,
        rewrite_text: str | None = None,
    ) -> HomeReviewResolveOutcome:
        """Resolve one current Home review through the owner boundary."""

        self._validate_overlay_semantics()
        outcome = self._review.resolve(
            token,
            resolution,
            rewrite_text=rewrite_text,
        )
        self._validate_overlay_semantics()
        return outcome

    def remove_resolved_overlay(self) -> bool:
        """Remove the runtime Home after all current differences are resolved."""

        self._validate_overlay_semantics()
        if self._review.pending().pending:
            raise AgentHomeContractError(
                "Home review cannot remove the overlay while differences remain"
            )
        return self._overlay.remove_if_empty()

    def parse_ref(self, value: str) -> HomeRef:
        return parse_home_ref(value)

    def default_background_refs(self) -> tuple[str, ...]:
        """Return the effective, explicitly allowlisted default Agent tops."""

        core = _DEFAULT_BACKGROUND_TOP_REFS[0]
        if self._resolve_top_relative(core) is None:
            raise AgentHomeContractError("Agent Home core background is missing")
        return tuple(
            str(ref)
            for ref in _DEFAULT_BACKGROUND_TOP_REFS
            if self._resolve_top_relative(ref) is not None
        )

    def default_background_entries(self) -> tuple[HomeBackgroundEntry, ...]:
        return tuple(
            HomeBackgroundEntry(ref=ref, content=self.read_top(ref))
            for ref in self.default_background_refs()
        )

    def loadable_background_refs(self) -> tuple[str, ...]:
        """Return the effective top catalog without materializing runtime copies."""

        self._validate_overlay_semantics()
        return tuple(str(ref) for ref in self._effective_top_refs())

    def skill_metadata(self) -> tuple[HomeSkillMetadata, ...]:
        """Return bounded discovery metadata for all effective general skills."""

        return self._skill_metadata_catalog()

    def _effective_top_refs(self) -> tuple[HomeTopRef, ...]:
        relatives = set(self._layout.actual_top_relatives())
        relatives.update(record.relative_path for record in self._overlay.records())
        refs = {
            ref
            for relative in relatives
            if (ref := self._layout.top_ref_for_relative(relative)) is not None
            and self._resolve_top_relative(ref) is not None
        }
        return tuple(sorted(refs, key=str))

    def actual_top_refs(self) -> tuple[str, ...]:
        """Return canonical top refs backed by current actual Home files."""

        result: dict[str, str] = {}
        for relative in self._layout.actual_top_relatives():
            ref = self._layout.top_ref_for_relative(relative)
            if ref is None:
                continue
            value = str(ref)
            previous = result.get(value)
            if previous is not None and previous != relative:
                raise AgentHomeInvariantError(
                    f"Actual Home top ref has multiple paths: {value}"
                )
            result[value] = relative
        return tuple(sorted(result))

    def actual_default_background_refs(self) -> tuple[str, ...]:
        """Return default Background refs backed only by actual Home."""

        actual = set(self.actual_top_refs())
        core = str(_DEFAULT_BACKGROUND_TOP_REFS[0])
        if core not in actual:
            raise AgentHomeContractError("Actual Home core background is missing")
        return tuple(
            str(ref) for ref in _DEFAULT_BACKGROUND_TOP_REFS if str(ref) in actual
        )

    def read_actual_top(self, ref: HomeTopRef | str) -> str:
        """Read one top-level entry without consulting the runtime overlay."""

        parsed = HomeTopRef.parse(ref) if isinstance(ref, str) else ref
        relative = self._layout.relative_for_top(parsed)
        source = self._layout.source_for_relative(relative)
        if source.is_symlink() or not source.is_file():
            raise AgentHomeContractError(
                f"Actual Home top-level entry does not exist: {parsed}"
            )
        return _read_text(source)

    def actual_skill_metadata(self) -> tuple[HomeSkillMetadata, ...]:
        """Return general skill metadata parsed only from actual Home."""

        items: list[HomeSkillMetadata] = []
        for value in self.actual_top_refs():
            ref = HomeTopRef.parse(value)
            if ref.space != "skills":
                continue
            relative = self._layout.relative_for_top(ref)
            prefix = _read_text_prefix(
                self._layout.source_for_relative(relative),
                SKILL_FRONTMATTER_MAX_CHARS + 1,
            )
            items.append(parse_home_skill_metadata(prefix.text, ref=ref))
        result = tuple(sorted(items, key=lambda item: str(item.ref)))
        self._validate_skill_catalog_budget(result)
        return result

    def read_top(self, ref: HomeTopRef | str) -> str:
        parsed = HomeTopRef.parse(ref) if isinstance(ref, str) else ref
        relative = self._resolve_top_relative(parsed)
        if relative is None:
            raise AgentHomeContractError(
                f"Home top-level entry does not exist: {parsed}"
            )
        source = self._layout.source_for_relative(relative)
        return _read_text(self._runtime_read_path(str(parsed), relative))

    def canonical_reference(
        self, resource: str, fragment: str = "", source_day: date | None = None
    ) -> ResourceTarget:
        try:
            parsed = parse_home_ref(resource)
            if isinstance(parsed, HomePromptMountRef):
                raise AgentHomeContractError(
                    "Prompt mounts are not public resource identities"
                )
            relative = (
                self._layout.relative_for_top(parsed)
                if isinstance(parsed, HomeTopRef)
                else self._layout.relative_for_resource(parsed)
            )
            return ResourceTarget("home:resource/" + relative, fragment)
        except AgentHomeContractError as exc:
            raise ReferenceError("Invalid Home reference") from exc

    def resolve_relative(self, reference: str, origin_ref: str) -> str:
        parsed = parse_home_ref(origin_ref.partition("#")[0])
        path = (
            self._layout.relative_for_prompt_mount(parsed)
            if isinstance(parsed, HomePromptMountRef)
            else self._layout.relative_for_top(parsed)
            if isinstance(parsed, HomeTopRef)
            else self._layout.relative_for_resource(parsed)
        )
        value = relative_reference(reference, source_path=path, prefix="home:resource/")
        resource, marker, fragment = value.partition("#")
        if resource.startswith("home:"):
            try:
                absolute = parse_home_ref(resource)
            except AgentHomeContractError:
                absolute = None
            if isinstance(absolute, (HomeTopRef, HomePromptMountRef)):
                return str(absolute) + ("#" + fragment if marker else "")
            mapped = self._layout.ref_for_relative(
                resource.removeprefix("home:resource/")
            )
            if mapped is not None:
                return str(mapped) + ("#" + fragment if marker else "")
        return value

    def _search_paths(self, *, actual: bool) -> tuple[tuple[str, Path], ...]:
        return self._content_paths(actual=actual, spaces=("agent", "skills"))

    def _content_paths(
        self, *, actual: bool, spaces: tuple[str, ...]
    ) -> tuple[tuple[str, Path], ...]:
        relatives = {
            path.relative_to(self.original_root).as_posix()
            for space in spaces
            for path in (self.original_root / space).rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        records = (
            {}
            if actual
            else {record.relative_path: record for record in self._overlay.records()}
        )
        relatives.update(
            relative for relative in records if relative.split("/")[0] in spaces
        )
        result = []
        for relative in sorted(relatives):
            record = records.get(relative)
            if record and record.state is HomeOverlayState.DELETED:
                continue
            path = (
                self._layout.runtime_for_relative(relative)
                if record
                else self._layout.source_for_relative(relative)
            )
            if path.is_file() and not path.is_symlink():
                result.append((relative, path))
        return tuple(result)

    def _browse_paths(
        self, *, view: str, spaces: tuple[str, ...]
    ) -> tuple[tuple[str, Path], ...]:
        """Return the side-effect-free collection exposed by Home browse APIs."""

        if view == "actual":
            return self._content_paths(actual=True, spaces=spaces)
        records = {record.relative_path: record for record in self._overlay.records()}
        result = []
        for relative, record in sorted(records.items()):
            if relative.split("/")[0] not in spaces:
                continue
            if record.state is HomeOverlayState.DELETED:
                continue
            path = self._layout.runtime_for_relative(relative)
            if path.is_file() and not path.is_symlink():
                result.append((relative, path))
        return tuple(result)

    def browse_catalog(
        self,
        *,
        view: str = "effective",
        space: str | None = None,
        query: str | None = None,
        page: PageOptions = PageOptions(),
    ) -> JsonObject:
        self._validate_view(view)
        spaces = ("agent", "skills", "skills_domain", "skills_action")
        if space is not None and space not in spaces:
            raise AgentHomeContractError("Unknown Home space")
        values: list[JsonObject] = []
        for relative, path in self._browse_paths(
            view=view, spaces=(space,) if space else spaces
        ):
            ref = self._layout.ref_for_relative(relative)
            if ref is None or query and query.casefold() not in str(ref).casefold():
                continue
            values.append(
                {
                    "ref": str(ref),
                    "locator": {"ref": str(ref), "view": view},
                    "title": str(ref).removeprefix("home:"),
                    "kind": "guidance"
                    if isinstance(ref, HomePromptMountRef)
                    else "top"
                    if isinstance(ref, HomeTopRef)
                    else "resource",
                    "size": path.stat().st_size,
                }
            )
        return page.render(
            tuple(values),
            owner="home",
            ref=f"catalog:{view}:{space}:{query}",
            base={"view": view},
        )

    def browse_content(
        self, ref: str, *, view: str = "effective", page: PageOptions = PageOptions()
    ) -> JsonObject:
        self._validate_view(view)
        resource = ref.partition("#")[0]
        parsed = parse_home_ref(resource)
        relative = (
            self._layout.relative_for_prompt_mount(parsed)
            if isinstance(parsed, HomePromptMountRef)
            else self._layout.relative_for_top(parsed)
            if isinstance(parsed, HomeTopRef)
            else self._layout.relative_for_resource(parsed)
        )
        paths = dict(self._browse_paths(view=view, spaces=(parsed.space,)))
        if relative not in paths:
            raise AgentHomeNotFoundError("Home content is unavailable in this view")
        text = _read_text(paths[relative])
        return inspect_document(
            owner=f"home.{view}",
            ref=ref,
            text=text,
            direct_refs=self._direct_refs(text, relative),
            continuation=page.continuation,
            max_chars=page.max_chars,
            metadata={
                "locator": {"ref": resource, "view": view},
                "title": paths[relative].name,
            },
        ).to_json()

    def _direct_refs(self, text: str, relative: str) -> tuple[DisclosureHint, ...]:
        refs: list[DisclosureHint] = []
        for item in markdown_references(text):
            try:
                target = self._canonical_markdown_reference(item.target, relative)
                refs.append(
                    DisclosureHint(
                        target,
                        item.label or Path(item.target).name,
                        f"Line {item.line}",
                    )
                )
            except ReferenceError:
                continue
        return tuple(dict.fromkeys(refs))

    def _canonical_markdown_reference(self, target: str, relative: str) -> str:
        """Map a Markdown edge through Home's canonical logical layout."""
        origin = self._layout.ref_for_relative(relative)
        if origin is None:
            raise ReferenceError("Home source has no canonical origin")
        return self.resolve_relative(target, str(origin))

    def browse_changes(self, page: PageOptions = PageOptions()) -> JsonObject:
        return self._review.read_changes(page)

    def browse_diff(self, ref: str, page: PageOptions = PageOptions()) -> JsonObject:
        return self._review.read_diff(ref, page)

    @staticmethod
    def _validate_view(view: str) -> None:
        if view not in {"actual", "effective"}:
            raise AgentHomeContractError("Home view must be actual or effective")

    def inspect(
        self,
        ref: str,
        *,
        view: str = "content",
        continuation: str | None = None,
        max_chars: int | None = None,
        actual: bool = False,
    ) -> InspectPage:
        resource, _, fragment = ref.partition("#")
        identity = self.canonical_reference(resource)
        relative = identity.resource.removeprefix("home:resource/")
        available = dict(self._search_paths(actual=actual))
        path = available.get(relative)
        if path is None:
            raise AgentHomeContractError("Home resource is not available in this view")
        text = _read_text(path)
        direct_refs = self._direct_refs(text, relative)
        if max_chars is not None and (type(max_chars) is not int or max_chars < 512):
            raise AgentHomeContractError("Inspect max_chars must be at least 512")
        return inspect_document(
            owner="home.actual" if actual else "home.effective",
            ref=ref,
            text=text,
            metadata={
                "title": next(
                    (
                        line.lstrip("# ")
                        for line in text.splitlines()
                        if line.startswith("# ")
                    ),
                    path.name,
                )
            },
            direct_refs=tuple(dict.fromkeys(direct_refs)),
            view=view,
            continuation=continuation,
            max_chars=min(
                max_chars if max_chars is not None else self._max_read_chars,
                self._max_read_chars,
            ),
        )

    def search_corpus(
        self,
        request: RetrievalRequest,
        *,
        references: ReferenceResolver,
        actual: bool = False,
    ) -> SearchCorpus:
        source = request.source
        scope = getattr(source, "scope", "all")
        if scope not in {"all", "agent", "skills"}:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                prompt_text.HOME_SCOPE_MUST_BE_ALL_AGENT_OR_SKILLS,
            )
        predicates = HOME_SEARCH_FILTERS.parse(getattr(source, "where", {}))
        paths = dict(self._search_paths(actual=actual))
        available = set(paths)

        def identity(ref: str) -> tuple[str, str]:
            resource, _, fragment = ref.partition("#")
            return self.canonical_reference(resource).resource, fragment

        excluded = {identity(ref) for ref in request.exclude_refs}
        # A source group establishes the candidate's identity before reading any body.
        groups: list[tuple[str, tuple[str, ...], str]] = []
        if isinstance(source, RefsSource):
            seen: set[tuple[str, str]] = set()
            for ref in source.refs:
                key = identity(ref)
                if key in seen or key in excluded:
                    continue
                seen.add(key)
                resource, fragment = key
                relative = resource.removeprefix("home:resource/")
                if relative not in paths:
                    raise SearchFailure(
                        SearchFailureKind.INVALID_REQUEST,
                        prompt_text.HOME_REF_IS_UNAVAILABLE_IN_THIS_VIEW,
                    )
                groups.append((ref, (relative,), fragment))
        else:
            grouped: dict[str, list[str]] = {}
            for relative in paths:
                parts = PurePosixPath(relative).parts
                if scope != "all" and parts[0] != scope:
                    continue
                skill = (
                    parts[1]
                    if parts[0] == "skills"
                    and len(parts) >= 3
                    and f"skills/{parts[1]}/SKILL.md" in available
                    else None
                )
                candidate_ref = (
                    f"home:top/skills/{skill}"
                    if skill and not isinstance(source, BacklinksSource)
                    else "home:resource/" + relative
                )
                grouped.setdefault(candidate_ref, []).append(relative)
            groups = [
                (ref, tuple(resources), "")
                for ref, resources in grouped.items()
                if identity(ref) not in excluded
            ]
        if isinstance(source, QuerySource) and isinstance(source.query, DocumentQuery):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                prompt_text.HOME_DISCOVERY_ACCEPTS_TEXT_QUERY_ONLY,
            )
        query = (
            source.query.text
            if isinstance(source, QuerySource) and isinstance(source.query, TextQuery)
            else ""
        )
        anchor = (
            references.resolve(source.anchor_ref)
            if isinstance(source, BacklinksSource)
            else None
        )
        candidates: list[SearchCandidate] = []
        scanned, complete = 0, True
        for ref, resources, fragment in groups:
            types = sorted({paths[relative].suffix.lower() for relative in resources})
            attributes: JsonObject = {
                "space": resources[0].split("/")[0],
                "resource_types": [value for value in types],
            }
            if len(resources) == 1:
                attributes["file_type"] = types[0]
                parts = PurePosixPath(resources[0]).parts
                if (
                    parts[0] == "skills"
                    and len(parts) >= 3
                    and f"skills/{parts[1]}/SKILL.md" in available
                ):
                    attributes["top_ref"] = f"home:top/skills/{parts[1]}"
            if not all(predicate.matches(attributes) for predicate in predicates):
                continue
            units: list[ContentUnit] = []
            hits: list[SearchEvidence] = []
            coverage = ContentCoverage.FULL
            title = (
                ref.removeprefix("home:top/")
                if ref.startswith("home:top/")
                else PurePosixPath(resources[0]).name
            )
            for relative in resources:
                if scanned >= self._search_settings.scan_limit:
                    complete = False
                    break
                scanned += 1
                path, resource = paths[relative], "home:resource/" + relative
                try:
                    read = read_text_prefix(
                        path, max_chars=self._search_settings.resource_max_chars
                    )
                    text = read.text
                    if ref.startswith("home:top/") and relative.endswith("/SKILL.md"):
                        title = parse_home_skill_metadata(
                            text[: SKILL_FRONTMATTER_MAX_CHARS + 1],
                            ref=HomeTopRef.parse(ref.partition("#")[0]),
                        ).title
                    if "\x00" in text:
                        raise UnicodeError("Binary resource")
                    if read.truncated:
                        coverage = ContentCoverage.EXCERPT
                        complete = complete and isinstance(source, DirectorySource)
                    first, last = fragment_range(text, fragment)
                    selected = "".join(text.splitlines(keepends=True)[first - 1 : last])
                    resource_units = content_units(resource, selected, first_line=first)
                except UnicodeError:
                    if fragment:
                        raise SearchFailure(
                            SearchFailureKind.INVALID_REQUEST,
                            prompt_text.NON_TEXT_HOME_RESOURCE_HAS_NO_TEXT_FRAGMENT,
                        )
                    resource_units = (
                        ContentUnit(resource, resource, path.name, "metadata"),
                    )
                    coverage = (
                        ContentCoverage.METADATA
                        if len(resources) == 1
                        else ContentCoverage.EXCERPT
                    )
                    text = ""
                except OSError as exc:
                    raise AgentHomeIOError("Home search source cannot be read") from exc
                units.extend(resource_units)
                if anchor is not None:
                    lines = text.splitlines(keepends=True)
                    for resource in markdown_references(text):
                        try:
                            target = references.resolve(
                                self._canonical_markdown_reference(
                                    resource.target, relative
                                )
                            )
                        except ReferenceError:
                            continue
                        if target.matches(anchor):
                            start = sum(
                                len(line) for line in lines[: resource.line - 1]
                            )
                            hits.extend(
                                range_evidence(
                                    resource_units,
                                    start,
                                    start + len(lines[resource.line - 1]),
                                    kind=EvidenceKind.REFERENCE,
                                    relation="markdown_reference",
                                )
                            )
            if not complete:
                break
            if anchor is not None and not hits:
                continue
            candidates.append(
                SearchCandidate(
                    ref, title, tuple(units), attributes, tuple(hits), coverage
                )
            )
        return SearchCorpus(tuple(candidates), query, scanned, complete)

    def read_prompt_mount(self, ref: HomePromptMountRef | str) -> str:
        parsed = HomePromptMountRef.parse(ref) if isinstance(ref, str) else ref
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
        ref: HomeResourceRef | str,
        *,
        max_chars: int | None = None,
    ) -> HomeResourceRead:
        parsed = self._resource_ref(ref)
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
            ref=str(parsed),
            text=read.text,
            truncated=read.truncated,
            digest=record.runtime_digest,
        )

    def resource_exists(self, ref: HomeResourceRef | str) -> bool:
        """Report whether one validated progressive resource currently exists."""

        parsed = self._resource_ref(ref)
        relative = self._layout.relative_for_resource(parsed)
        record = self._overlay.record_for(relative)
        if record is not None:
            return record.state is not HomeOverlayState.DELETED
        source = self._layout.source_for_relative(relative)
        if source.is_symlink():
            raise AgentHomeInvariantError(
                f"Actual Home resource cannot be a symlink: {relative}"
            )
        if source.exists() and not source.is_file():
            raise AgentHomeInvariantError(
                f"Actual Home resource is not a regular file: {relative}"
            )
        return source.is_file()

    def guidance_for_domain(self, domain: str) -> str | None:
        if not domain:
            return None
        return self._read_optional_prompt_mount(
            HomePromptMountRef("skills_domain", domain)
        )

    def guidance_for_action(self, domain: str, action_name: str) -> str | None:
        if not domain or not action_name:
            return None
        action_key = action_name
        prefix = f"{domain}."
        if action_name.startswith(prefix):
            action_key = action_name[len(prefix) :]
        return self._read_optional_prompt_mount(
            HomePromptMountRef("skills_action", f"{domain}/{action_key}")
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
            HomePromptMountRef("skills_domain", domain) for domain in domain_names
        }
        for domain, action_name in action_identifiers:
            if domain not in domain_names or not action_name.startswith(f"{domain}."):
                raise AgentHomeContractError(
                    f"Action Catalog action/domain identity is inconsistent: {action_name}"
                )
            action_key = action_name[len(domain) + 1 :]
            expected.add(HomePromptMountRef("skills_action", f"{domain}/{action_key}"))

        existing_relatives = set(self._layout.actual_prompt_mount_relatives())
        existing_relatives.update(
            record.relative_path
            for record in self._overlay.records()
            if self._layout.prompt_mount_ref_for_relative(record.relative_path)
            is not None
        )
        for relative in sorted(existing_relatives):
            ref = self._layout.prompt_mount_ref_for_relative(relative)
            if ref is None or ref in expected:
                continue
            record = self._overlay.record_for(relative)
            if record is not None and record.state is HomeOverlayState.DELETED:
                continue
            source = self._layout.source_for_relative(relative)
            if record is not None or source.is_file():
                self._overlay.delete(relative, expected_digest="")

        for ref in sorted(expected, key=str):
            relative = self._layout.relative_for_prompt_mount(ref)
            record = self._overlay.record_for(relative)
            source = self._layout.source_for_relative(relative)
            if (
                record is not None
                and record.state is HomeOverlayState.DELETED
                and source.is_file()
                and not source.is_symlink()
            ):
                self._overlay.reset_to_actual_copy(relative)

        self._prompt_mount_refs = frozenset(expected)
        self._validate_overlay_semantics()

    def ensure_runtime_copy(self, ref: HomeRef) -> bool:
        """Materialize one missing runtime file and report whether disk changed."""

        if isinstance(ref, HomeTopRef):
            relative = self._layout.relative_for_top(ref)
            materialized = not self._layout.runtime_for_relative(relative).is_file()
            relative = self._require_top_relative(ref)
        elif isinstance(ref, HomeResourceRef):
            parsed = self._resource_ref(ref)
            relative = self._layout.relative_for_resource(parsed)
            materialized = not self._layout.runtime_for_relative(relative).is_file()
        else:
            self._require_prompt_mount(ref)
            relative = self._layout.relative_for_prompt_mount(ref)
            materialized = not self._layout.runtime_for_relative(relative).is_file()
            record = self._overlay.record_for(relative)
            source = self._layout.source_for_relative(relative)
            if (record is not None and record.state is HomeOverlayState.DELETED) or (
                record is None and not source.exists()
            ):
                return False
        self._overlay.ensure_copy(relative)
        return materialized

    def write_resource(
        self,
        ref: HomeResourceRef | str,
        text: str,
        *,
        overwrite: bool = False,
        expected_digest: str = "",
    ) -> HomeResourceMutation:
        parsed = self._mutable_resource_ref(ref)
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
        ref: HomeResourceRef | str,
        *,
        old_text: str,
        new_text: str,
        expected_digest: str = "",
    ) -> HomeResourceMutation:
        parsed = self._mutable_resource_ref(ref)
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
        ref: HomeResourceRef | str,
        *,
        expected_digest: str = "",
    ) -> HomeResourceMutation:
        parsed = self._mutable_resource_ref(ref)
        relative = self._layout.relative_for_resource(parsed)
        record = self._overlay.delete(relative, expected_digest=expected_digest)
        return _mutation(str(parsed), record)

    def write_top(
        self,
        ref: HomeTopRef | str,
        text: str,
        *,
        overwrite: bool = False,
        expected_digest: str = "",
    ) -> HomeResourceMutation:
        parsed = self._mutable_top_ref(ref)
        self._validate_write_text(text)
        if parsed.space == "skills":
            self._validate_projected_skill_catalog(
                parsed,
                parse_home_skill_metadata(text, ref=parsed),
            )
        existing = self._resolve_top_relative(parsed)
        if existing is None:
            relative = self._layout.relative_for_top(parsed)
        else:
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
        ref: HomeTopRef | str,
        *,
        old_text: str,
        new_text: str,
        expected_digest: str = "",
    ) -> HomeResourceMutation:
        parsed = self._mutable_top_ref(ref)
        relative = self._require_top_relative(parsed)
        if parsed.space == "skills":
            current = _read_text(self._effective_top_path(parsed, relative))
            if not isinstance(old_text, str) or not old_text:
                raise AgentHomeContractError("Home patch old_text must be non-empty")
            if not isinstance(new_text, str):
                raise AgentHomeContractError("Home patch new_text must be a string")
            count = current.count(old_text)
            if count != 1:
                detail = "not found" if count == 0 else "not unique"
                raise AgentHomeContractError(
                    f"Home patch old_text is {detail}: {relative}"
                )
            updated = current.replace(old_text, new_text, 1)
            self._validate_projected_skill_catalog(
                parsed,
                parse_home_skill_metadata(updated, ref=parsed),
            )
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
        ref: HomeTopRef | str,
        *,
        expected_digest: str = "",
    ) -> HomeResourceMutation:
        parsed = self._mutable_top_ref(ref)
        if parsed == HomeTopRef("agent", "AGENT"):
            raise AgentHomeContractError("home:top/agent/AGENT cannot be deleted")
        relative = self._require_top_relative(parsed)
        record = self._overlay.delete(relative, expected_digest=expected_digest)
        return _mutation(str(parsed), record)

    def write_prompt_mount(
        self,
        ref: HomePromptMountRef | str,
        text: str,
        *,
        overwrite: bool = False,
        expected_digest: str = "",
    ) -> HomeResourceMutation:
        parsed = HomePromptMountRef.parse(ref) if isinstance(ref, str) else ref
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
        ref: HomePromptMountRef | str,
        *,
        old_text: str,
        new_text: str,
        expected_digest: str = "",
    ) -> HomeResourceMutation:
        parsed = HomePromptMountRef.parse(ref) if isinstance(ref, str) else ref
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

    def _runtime_read_path(self, ref: str, relative: str) -> Path:
        record = self._overlay.record_for(relative)
        if record is not None:
            if record.state is HomeOverlayState.DELETED:
                raise AgentHomeContractError(
                    f"Home content was deleted in the active overlay: {ref}"
                )
            return self._layout.runtime_for_relative(relative)
        source = self._layout.source_for_relative(relative)
        if source.is_symlink():
            raise AgentHomeInvariantError(
                f"Actual Home content cannot be a symlink: {source}"
            )
        if not source.is_file():
            raise AgentHomeContractError(f"Home content does not exist: {ref}")
        raise AgentHomeRuntimeCopyRequired(
            ref,
            source_path=source,
            runtime_path=self._layout.runtime_for_relative(relative),
        )

    def _read_optional_prompt_mount(self, ref: HomePromptMountRef) -> str | None:
        content = self.read_prompt_mount(ref)
        return content if content else None

    def _resolve_top_relative(self, ref: HomeTopRef) -> str | None:
        relative = self._layout.relative_for_top(ref)
        record = self._overlay.record_for(relative)
        if record is not None:
            if record.state is HomeOverlayState.DELETED:
                return None
            return relative
        source = self._layout.source_for_relative(relative)
        if source.is_symlink():
            raise AgentHomeInvariantError(
                f"Actual Home top content cannot be a symlink: {relative}"
            )
        if source.is_file():
            return relative
        if source.exists():
            raise AgentHomeInvariantError(
                f"Home top path is not a regular file: {relative}"
            )
        return None

    def _require_top_relative(self, ref: HomeTopRef) -> str:
        relative = self._resolve_top_relative(ref)
        if relative is None:
            raise AgentHomeContractError(f"Home top-level entry does not exist: {ref}")
        return relative

    def _mutable_top_ref(self, ref: HomeTopRef | str) -> HomeTopRef:
        return HomeTopRef.parse(ref) if isinstance(ref, str) else ref

    def _resource_ref(
        self,
        ref: HomeResourceRef | str,
    ) -> HomeResourceRef:
        parsed_ref = parse_home_ref(ref) if isinstance(ref, str) else ref
        if not isinstance(parsed_ref, HomeResourceRef):
            raise AgentHomeContractError(
                "Home resource operation requires a progressive resource ref"
            )
        self._validate_resource_semantics(parsed_ref)
        if _is_top_entry_resource(parsed_ref):
            raise AgentHomeContractError(
                "Home resource operation cannot address a top-level Home file"
            )
        return parsed_ref

    def _mutable_resource_ref(
        self,
        ref: HomeResourceRef | str,
    ) -> HomeResourceRef:
        return self._resource_ref(ref)

    def _validate_resource_semantics(self, ref: HomeResourceRef) -> None:
        path = PurePosixPath(ref.relative_path)
        memory_name = path.name.upper()
        if memory_name.endswith("_MEMORY.MD"):
            if not (
                ref.space == "skills"
                and path.name == "SKILL_MEMORY.md"
                and len(path.parts) == 2
            ):
                raise AgentHomeContractError(
                    "Only skills/<skill>/SKILL_MEMORY.md runtime memory is allowed"
                )
            skill = HomeTopRef("skills", path.parts[0])
            if self._resolve_top_relative(skill) is None:
                raise AgentHomeContractError(
                    f"SKILL_MEMORY.md requires an existing general skill: {skill}"
                )

    def _require_prompt_mount(self, ref: HomePromptMountRef) -> None:
        if self._prompt_mount_refs is None:
            raise AgentHomeInvariantError(
                "Home prompt mounts have not been bound to the Action Catalog"
            )
        if ref not in self._prompt_mount_refs:
            raise AgentHomeContractError(
                f"Home prompt mount is not defined by the Action Catalog: {ref}"
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
        self._validate_runtime_special_files()
        for record in self._overlay.records():
            relative = record.relative_path
            parts = PurePosixPath(relative).parts
            if (
                relative == "agent/AGENT.md"
                and record.state is HomeOverlayState.DELETED
            ):
                raise AgentHomeInvariantError(
                    "home:top/agent/AGENT cannot be deleted in the runtime overlay"
                )
            name = PurePosixPath(relative).name
            if name.upper().endswith("_MEMORY.MD"):
                if not (
                    len(parts) == 3
                    and parts[0] == "skills"
                    and parts[2] == "SKILL_MEMORY.md"
                ):
                    raise AgentHomeInvariantError(
                        f"Invalid runtime Home memory file: {relative}"
                    )
                if record.baseline_digest or record.state is HomeOverlayState.COPIED:
                    raise AgentHomeInvariantError(
                        f"Runtime-only SKILL_MEMORY has an actual baseline: {relative}"
                    )
                if self._resolve_top_relative(HomeTopRef("skills", parts[1])) is None:
                    raise AgentHomeInvariantError(
                        f"Runtime SKILL_MEMORY has no general skill: {relative}"
                    )
            if parts and parts[0] in {"skills_domain", "skills_action"}:
                if self._layout.prompt_mount_ref_for_relative(relative) is None:
                    raise AgentHomeInvariantError(
                        f"Invalid runtime Home prompt mount path: {relative}"
                    )
        self._skill_metadata_catalog()

    def _skill_metadata_catalog(
        self,
        *,
        exclude: frozenset[HomeTopRef] = frozenset(),
    ) -> tuple[HomeSkillMetadata, ...]:
        items = tuple(
            self._skill_metadata_for_ref(ref)
            for ref in self._effective_skill_refs()
            if ref not in exclude
        )
        self._validate_skill_catalog_budget(items)
        return items

    def _effective_skill_refs(self) -> tuple[HomeTopRef, ...]:
        relatives = set(self._layout.actual_top_relatives())
        relatives.update(record.relative_path for record in self._overlay.records())
        refs = {
            ref
            for relative in relatives
            if (ref := self._layout.top_ref_for_relative(relative)) is not None
            and ref.space == "skills"
            and self._resolve_top_relative(ref) is not None
        }
        return tuple(sorted(refs, key=str))

    def _skill_metadata_for_ref(self, ref: HomeTopRef) -> HomeSkillMetadata:
        relative = self._require_top_relative(ref)
        prefix = _read_text_prefix(
            self._effective_top_path(ref, relative),
            SKILL_FRONTMATTER_MAX_CHARS + 1,
        )
        return parse_home_skill_metadata(prefix.text, ref=ref)

    def _effective_top_path(self, ref: HomeTopRef, relative: str) -> Path:
        record = self._overlay.record_for(relative)
        if record is None:
            return self._layout.source_for_relative(relative)
        if record.state is HomeOverlayState.DELETED:
            raise AgentHomeInvariantError(
                f"Deleted Home top entry entered effective catalog: {ref}"
            )
        return self._layout.runtime_for_relative(relative)

    def _validate_projected_skill_catalog(
        self,
        ref: HomeTopRef,
        metadata: HomeSkillMetadata,
    ) -> None:
        items = (*self._skill_metadata_catalog(exclude=frozenset({ref})), metadata)
        self._validate_skill_catalog_budget(
            tuple(sorted(items, key=lambda item: str(item.ref)))
        )

    def _validate_skill_catalog_budget(
        self,
        items: tuple[HomeSkillMetadata, ...],
    ) -> None:
        total = sum(item.catalog_chars for item in items)
        if total > self._skill_catalog_max_chars:
            raise AgentHomeContractError(
                "General skill metadata catalog exceeds "
                f"{self._skill_catalog_max_chars} characters"
            )

    def _validate_actual_special_files(self) -> None:
        for path in self.original_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(self.original_root).as_posix()
            parts = PurePosixPath(relative).parts
            if parts and parts[0] == "memory":
                raise AgentHomeInvariantError(
                    f"Memory content cannot exist inside Agent Home: {relative}"
                )
            if path.name.upper().endswith("_MEMORY.MD"):
                raise AgentHomeInvariantError(
                    f"Runtime-only Home memory cannot exist in actual Home: {relative}"
                )

    def _validate_runtime_special_files(self) -> None:
        if not self.runtime_root.is_dir():
            return
        for path in self.runtime_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(self.runtime_root).as_posix()
            parts = PurePosixPath(relative).parts
            if parts and parts[0] == "memory":
                raise AgentHomeInvariantError(
                    f"Memory content cannot exist in the Home runtime overlay: {relative}"
                )


class AgentHomeEngineBuilder:
    """Build an AgentHomeEngine from parsed settings."""

    def __init__(
        self,
        settings: AgentHomeSettings,
    ) -> None:
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
            skill_catalog_max_chars=self._settings.skill_catalog_max_chars,
            search_settings=self._settings.search,
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


def _file_digest(path: Path) -> str:
    try:
        return file_digest(path)
    except OSError as exc:
        raise AgentHomeIOError(f"Failed to digest Agent Home file: {exc}") from exc


def _mutation(ref: str, record: HomeOverlayRecord) -> HomeResourceMutation:
    return HomeResourceMutation(
        ref=ref,
        state=record.state,
        digest=record.runtime_digest,
        baseline_digest=record.baseline_digest,
        size=record.size,
    )


def _is_top_entry_resource(ref: HomeResourceRef) -> bool:
    path = PurePosixPath(ref.relative_path)
    if ref.space == "agent" and path.suffix.lower() == ".md":
        return True
    return ref.space == "skills" and path.name == "SKILL.md"


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
