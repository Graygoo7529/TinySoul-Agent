"""Workspace configuration parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from tinysoul.infra.config import ConfigError, reject_unknown_keys

DEFAULT_IGNORE_DIRS = (
    ".agents",
    ".codex",
    ".git",
    ".pytest-local-tmp",
    ".pytest_cache",
    ".test-tmp",
    ".tinysoul",
    "__pycache__",
)
DEFAULT_MAX_FILES = 100
DEFAULT_MAX_READ_CHARS = 4000
DEFAULT_MAX_IMAGE_BYTES = 5 * 1024 * 1024
DEFAULT_SEARCH_MAX_QUERY_CHARS = 256
DEFAULT_SEARCH_MAX_SCAN_CHARS = 1_000_000
DEFAULT_SEARCH_CANDIDATE_LIMIT = 100
DEFAULT_SEARCH_TOP_K = 8
DEFAULT_SEARCH_MAX_TOP_K = 16
DEFAULT_SEARCH_CONTEXT_LINES = 2
DEFAULT_SEARCH_MAX_EXCERPT_CHARS = 600
DEFAULT_SEARCH_MAX_RESULT_CHARS = 8000
DEFAULT_ANALYSIS_MAX_INTENT_CHARS = 2000
DEFAULT_ANALYSIS_MAX_REFERENCE_LINKS = 8
DEFAULT_ANALYSIS_MAX_SOURCE_CHARS = 24_000
DEFAULT_ANALYSIS_MAX_CHARS_PER_REFERENCE = 12_000
DEFAULT_ANALYSIS_MAX_ANSWER_CHARS = 4000


@dataclass(frozen=True)
class WorkspaceSearchSettings:
    """Bounded deterministic Workspace text search settings."""

    max_query_chars: int = DEFAULT_SEARCH_MAX_QUERY_CHARS
    max_scan_chars: int = DEFAULT_SEARCH_MAX_SCAN_CHARS
    candidate_limit: int = DEFAULT_SEARCH_CANDIDATE_LIMIT
    default_top_k: int = DEFAULT_SEARCH_TOP_K
    max_top_k: int = DEFAULT_SEARCH_MAX_TOP_K
    context_lines: int = DEFAULT_SEARCH_CONTEXT_LINES
    max_excerpt_chars: int = DEFAULT_SEARCH_MAX_EXCERPT_CHARS
    max_result_chars: int = DEFAULT_SEARCH_MAX_RESULT_CHARS

    def __post_init__(self) -> None:
        for name in (
            "max_query_chars",
            "max_scan_chars",
            "candidate_limit",
            "default_top_k",
            "max_top_k",
            "max_excerpt_chars",
            "max_result_chars",
        ):
            _require_positive(getattr(self, name), key=f"workspace.search.{name}")
        if (
            isinstance(self.context_lines, bool)
            or not isinstance(self.context_lines, int)
            or self.context_lines < 0
        ):
            raise ConfigError(
                "Workspace search context_lines must be non-negative",
                key="workspace.search.context_lines",
                value=self.context_lines,
                expected="non-negative int",
            )
        if self.default_top_k > self.max_top_k:
            raise ConfigError(
                "Workspace search default_top_k cannot exceed max_top_k",
                key="workspace.search.default_top_k",
                value=self.default_top_k,
                expected="int <= max_top_k",
            )
        if self.max_top_k > self.candidate_limit:
            raise ConfigError(
                "Workspace search max_top_k cannot exceed candidate_limit",
                key="workspace.search.max_top_k",
                value=self.max_top_k,
                expected="int <= candidate_limit",
            )
        if self.max_excerpt_chars > self.max_result_chars:
            raise ConfigError(
                "Workspace search excerpt budget cannot exceed result budget",
                key="workspace.search.max_excerpt_chars",
                value=self.max_excerpt_chars,
                expected="int <= max_result_chars",
            )
        if self.max_excerpt_chars < self.max_query_chars:
            raise ConfigError(
                "Workspace search excerpt budget must contain the largest query",
                key="workspace.search.max_excerpt_chars",
                value=self.max_excerpt_chars,
                expected="int >= max_query_chars",
            )


@dataclass(frozen=True)
class WorkspaceAnalysisSettings:
    """Bounded Workspace reference analysis settings."""

    max_intent_chars: int = DEFAULT_ANALYSIS_MAX_INTENT_CHARS
    max_reference_links: int = DEFAULT_ANALYSIS_MAX_REFERENCE_LINKS
    max_source_chars: int = DEFAULT_ANALYSIS_MAX_SOURCE_CHARS
    max_chars_per_reference: int = DEFAULT_ANALYSIS_MAX_CHARS_PER_REFERENCE
    max_answer_chars: int = DEFAULT_ANALYSIS_MAX_ANSWER_CHARS

    def __post_init__(self) -> None:
        for name in (
            "max_intent_chars",
            "max_reference_links",
            "max_source_chars",
            "max_chars_per_reference",
            "max_answer_chars",
        ):
            _require_positive(getattr(self, name), key=f"workspace.analysis.{name}")
        if self.max_chars_per_reference > self.max_source_chars:
            raise ConfigError(
                "Workspace analysis per-reference budget cannot exceed source budget",
                key="workspace.analysis.max_chars_per_reference",
                value=self.max_chars_per_reference,
                expected="int <= max_source_chars",
            )


@dataclass(frozen=True)
class WorkspaceSettings:
    """Workspace module settings."""

    root: Path
    manifest_path: Path = Path()
    trash_root: Path = Path()
    max_files: int = DEFAULT_MAX_FILES
    max_read_chars: int = DEFAULT_MAX_READ_CHARS
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES
    ignore_dirs: tuple[str, ...] = DEFAULT_IGNORE_DIRS
    search: WorkspaceSearchSettings = field(default_factory=WorkspaceSearchSettings)
    analysis: WorkspaceAnalysisSettings = field(
        default_factory=WorkspaceAnalysisSettings
    )

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise ConfigError(
                "Workspace root must be a path",
                key="workspace.root",
                value=self.root,
                expected="path",
            )
        if not isinstance(self.manifest_path, Path):
            raise ConfigError(
                "Workspace manifest_path must be a path",
                key="workspace.manifest_path",
                value=self.manifest_path,
                expected="path",
            )
        if not isinstance(self.trash_root, Path):
            raise ConfigError(
                "Workspace trash_root must be a path",
                key="workspace.trash_root",
                value=self.trash_root,
                expected="path",
            )
        if self.manifest_path == Path():
            object.__setattr__(
                self,
                "manifest_path",
                self.root / ".tinysoul" / "workspace_manifest.json",
            )
        if self.trash_root == Path():
            object.__setattr__(
                self,
                "trash_root",
                self.root / ".tinysoul" / "trash",
            )
        root = self.root.resolve()
        trash_root = self.trash_root.resolve()
        if root == trash_root or root not in trash_root.parents:
            raise ConfigError(
                "Workspace trash_root must be inside the active workspace root",
                key="workspace.trash_root",
                value=str(self.trash_root),
                expected="path under workspace.root",
            )
        manifest_path = self.manifest_path.resolve()
        if root == manifest_path or root not in manifest_path.parents:
            raise ConfigError(
                "Workspace manifest_path must be inside the active workspace root",
                key="workspace.manifest_path",
                value=str(self.manifest_path),
                expected="path under workspace.root",
            )
        if (
            isinstance(self.max_files, bool)
            or not isinstance(self.max_files, int)
            or self.max_files <= 0
        ):
            raise ConfigError(
                "Workspace max_files must be positive",
                key="workspace.max_files",
                value=self.max_files,
                expected="positive int",
            )
        if (
            isinstance(self.max_read_chars, bool)
            or not isinstance(self.max_read_chars, int)
            or self.max_read_chars <= 0
        ):
            raise ConfigError(
                "Workspace max_read_chars must be positive",
                key="workspace.max_read_chars",
                value=self.max_read_chars,
                expected="positive int",
            )
        if (
            isinstance(self.max_image_bytes, bool)
            or not isinstance(self.max_image_bytes, int)
            or self.max_image_bytes <= 0
        ):
            raise ConfigError(
                "Workspace max_image_bytes must be positive",
                key="workspace.max_image_bytes",
                value=self.max_image_bytes,
                expected="positive int",
            )
        if not isinstance(self.ignore_dirs, tuple):
            raise ConfigError(
                "Workspace ignore_dirs must be a tuple",
                key="workspace.ignore_dirs",
                value=self.ignore_dirs,
                expected="tuple[str, ...]",
            )
        for name in self.ignore_dirs:
            if not isinstance(name, str) or not name:
                raise ConfigError(
                    "Workspace ignore_dirs must contain non-empty strings",
                    key="workspace.ignore_dirs",
                    value=list(self.ignore_dirs),
                    expected="list[str]",
                )
        if not isinstance(self.search, WorkspaceSearchSettings):
            raise ConfigError(
                "Workspace search settings are invalid",
                key="workspace.search",
                value=type(self.search).__name__,
                expected="WorkspaceSearchSettings",
            )
        if not isinstance(self.analysis, WorkspaceAnalysisSettings):
            raise ConfigError(
                "Workspace analysis settings are invalid",
                key="workspace.analysis",
                value=type(self.analysis).__name__,
                expected="WorkspaceAnalysisSettings",
            )


def parse_workspace_settings(
    tree: Mapping[str, object],
    *,
    project_root: Path,
) -> WorkspaceSettings:
    reject_unknown_keys(
        tree,
        {
            "root",
            "max_files",
            "max_read_chars",
            "max_image_bytes",
            "ignore_dirs",
            "search",
            "analysis",
        },
        key="workspace",
    )
    root = _optional_path(
        tree,
        "root",
        default=project_root / "runtime" / "workspace",
        project_root=project_root,
    )
    return WorkspaceSettings(
        root=root,
        max_files=_optional_int(tree, "max_files", default=DEFAULT_MAX_FILES),
        max_read_chars=_optional_int(
            tree,
            "max_read_chars",
            default=DEFAULT_MAX_READ_CHARS,
        ),
        max_image_bytes=_optional_int(
            tree,
            "max_image_bytes",
            default=DEFAULT_MAX_IMAGE_BYTES,
        ),
        ignore_dirs=_optional_str_tuple(
            tree,
            "ignore_dirs",
            default=DEFAULT_IGNORE_DIRS,
        ),
        search=_parse_search(_optional_table(tree, "search", key="workspace")),
        analysis=_parse_analysis(_optional_table(tree, "analysis", key="workspace")),
    )


def _parse_search(tree: Mapping[str, object]) -> WorkspaceSearchSettings:
    reject_unknown_keys(
        tree,
        {
            "max_query_chars",
            "max_scan_chars",
            "candidate_limit",
            "default_top_k",
            "max_top_k",
            "context_lines",
            "max_excerpt_chars",
            "max_result_chars",
        },
        key="workspace.search",
    )
    defaults = WorkspaceSearchSettings()
    return WorkspaceSearchSettings(
        max_query_chars=_optional_int(
            tree, "max_query_chars", default=defaults.max_query_chars, key="workspace.search"
        ),
        max_scan_chars=_optional_int(
            tree, "max_scan_chars", default=defaults.max_scan_chars, key="workspace.search"
        ),
        candidate_limit=_optional_int(
            tree, "candidate_limit", default=defaults.candidate_limit, key="workspace.search"
        ),
        default_top_k=_optional_int(
            tree, "default_top_k", default=defaults.default_top_k, key="workspace.search"
        ),
        max_top_k=_optional_int(
            tree, "max_top_k", default=defaults.max_top_k, key="workspace.search"
        ),
        context_lines=_optional_int(
            tree, "context_lines", default=defaults.context_lines, key="workspace.search"
        ),
        max_excerpt_chars=_optional_int(
            tree,
            "max_excerpt_chars",
            default=defaults.max_excerpt_chars,
            key="workspace.search",
        ),
        max_result_chars=_optional_int(
            tree, "max_result_chars", default=defaults.max_result_chars, key="workspace.search"
        ),
    )


def _parse_analysis(tree: Mapping[str, object]) -> WorkspaceAnalysisSettings:
    reject_unknown_keys(
        tree,
        {
            "max_intent_chars",
            "max_reference_links",
            "max_source_chars",
            "max_chars_per_reference",
            "max_answer_chars",
        },
        key="workspace.analysis",
    )
    defaults = WorkspaceAnalysisSettings()
    return WorkspaceAnalysisSettings(
        max_intent_chars=_optional_int(
            tree,
            "max_intent_chars",
            default=defaults.max_intent_chars,
            key="workspace.analysis",
        ),
        max_reference_links=_optional_int(
            tree,
            "max_reference_links",
            default=defaults.max_reference_links,
            key="workspace.analysis",
        ),
        max_source_chars=_optional_int(
            tree,
            "max_source_chars",
            default=defaults.max_source_chars,
            key="workspace.analysis",
        ),
        max_chars_per_reference=_optional_int(
            tree,
            "max_chars_per_reference",
            default=defaults.max_chars_per_reference,
            key="workspace.analysis",
        ),
        max_answer_chars=_optional_int(
            tree,
            "max_answer_chars",
            default=defaults.max_answer_chars,
            key="workspace.analysis",
        ),
    )


def _optional_path(
    tree: Mapping[str, object],
    name: str,
    *,
    default: Path,
    project_root: Path,
) -> Path:
    value = tree.get(name)
    if value is None:
        return default
    if not isinstance(value, str) or not value:
        raise ConfigError(
            "Workspace configuration value must be a non-empty path string",
            key=f"workspace.{name}",
            value=value,
            expected="str",
        )
    path = Path(value)
    if path.is_absolute():
        return path
    return project_root / path


def _optional_int(
    tree: Mapping[str, object],
    name: str,
    *,
    default: int,
    key: str = "workspace",
) -> int:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Workspace configuration value must be an integer",
            key=f"{key}.{name}",
            value=value,
            expected="int",
        )
    return value


def _optional_table(
    tree: Mapping[str, object],
    name: str,
    *,
    key: str,
) -> Mapping[str, object]:
    value = tree.get(name)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(
            "Workspace configuration value must be a table",
            key=f"{key}.{name}",
            value=value,
            expected="table",
        )
    normalized: dict[str, object] = {}
    for item_key, item_value in value.items():
        if not isinstance(item_key, str):
            raise ConfigError(
                "Workspace configuration table keys must be strings",
                key=f"{key}.{name}",
                value=item_key,
                expected="str",
            )
        normalized[item_key] = item_value
    return normalized


def _require_positive(value: object, *, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(
            "Workspace setting must be positive",
            key=key,
            value=value,
            expected="positive int",
        )


def _optional_str_tuple(
    tree: Mapping[str, object],
    name: str,
    *,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    value = tree.get(name)
    if value is None:
        return default
    if not isinstance(value, list):
        raise ConfigError(
            "Workspace configuration value must be a list of strings",
            key=f"workspace.{name}",
            value=value,
            expected="list[str]",
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ConfigError(
                "Workspace configuration value must contain non-empty strings",
                key=f"workspace.{name}",
                value=value,
                expected="list[str]",
            )
        result.append(item)
    return tuple(result)
