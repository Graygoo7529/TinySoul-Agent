"""Project configuration document support."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import glob
from typing import cast

from ..filesystem import FilesystemBoundaryError, resolve_under_root
from .documents import ConfigDocument, ConfigDocumentSet, ConfigDocumentSetSpec
from .errors import ConfigError
from .source import ConfigSource, ConfigSourceKind
from .toml_file import ConfigFileToml, deep_copy_mapping, flatten_mapping, merge_trees
from .validation import reject_unknown_keys


class ProjectConfig:
    """Merged project configuration tree from a main TOML file and includes."""

    def __init__(self, root: Path, main_file_name: str = "tinysoul.toml") -> None:
        self.root = root
        self.main_path = root / main_file_name
        self._data, self._sources, self._document_sets = self._load()

    @property
    def data(self) -> dict[str, object]:
        return deep_copy_mapping(self._data)

    @property
    def sources(self) -> tuple[ConfigSource, ...]:
        """Return main and included files in effective merge order."""

        return self._sources

    @property
    def source_paths(self) -> tuple[Path, ...]:
        return tuple(
            source.path for source in self._sources if source.path is not None
        )

    @property
    def document_sets(self) -> tuple[ConfigDocumentSet, ...]:
        return self._document_sets

    def to_source(self) -> ConfigSource:
        return ConfigSource(
            name=str(self.main_path),
            values=flatten_mapping(self._data),
            kind=ConfigSourceKind.PROJECT_TOML,
            path=self.main_path,
            source_id="project:merged",
        )

    def env_file_path(self, default_name: str = ".env") -> Path:
        configured = _get_config_string(self._data, "env_file")
        value = configured or default_name
        return _project_path(
            self.root,
            value,
            key="config.env_file",
            source=str(self.main_path),
        )

    def _load(
        self,
    ) -> tuple[
        dict[str, object],
        tuple[ConfigSource, ...],
        tuple[ConfigDocumentSet, ...],
    ]:
        main_file = ConfigFileToml(self.main_path)
        main = main_file.data
        _validate_config_table(main, source=str(self.main_path))
        result = deep_copy_mapping(main)
        sources = [_with_project_identity(self.root, main_file.to_source())]
        include_paths = _expand_include_paths(
            self.root,
            _get_config_string_list(main, "include"),
            source=str(self.main_path),
            key="config.include",
        )
        for include_path in include_paths:
            include_file = ConfigFileToml(include_path)
            include_data = include_file.data
            _validate_config_table(include_data, source=str(include_path))
            if _get_config_string_list(include_data, "include"):
                raise ConfigError(
                    "Nested configuration includes are not supported",
                    key="config.include",
                    source=str(include_path),
                    value=str(include_path),
                )
            if _has_config_key(include_data, "document_sets"):
                raise ConfigError(
                    "Configuration document sets may only be declared in tinysoul.toml",
                    key="config.document_sets",
                    source=str(include_path),
                    value=str(include_path),
                )
            result = merge_trees(result, include_data)
            sources.append(_with_project_identity(self.root, include_file.to_source()))
        document_sets = _load_document_sets(
            self.root,
            _get_config_document_set_specs(main, source=str(self.main_path)),
            merged_paths={
                self.main_path.resolve(),
                *(path.resolve() for path in include_paths),
            },
            source=str(self.main_path),
        )
        return result, tuple(sources), document_sets


def _validate_config_table(data: Mapping[str, object], *, source: str) -> None:
    value = data.get("config")
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ConfigError(
            "Project configuration section must be a table",
            key="config",
            source=source,
            value=value,
            expected="table",
        )
    if any(not isinstance(name, str) for name in value):
        raise ConfigError(
            "Project configuration keys must be strings",
            key="config",
            source=source,
            value=value,
            expected="table with string keys",
        )
    table = cast(Mapping[str, object], value)
    try:
        reject_unknown_keys(
            table,
            {"include", "env_file", "document_sets"},
            key="config",
        )
    except ConfigError as exc:
        raise ConfigError(
            exc.message,
            key=exc.key,
            source=source,
            value=exc.value,
            expected=exc.expected,
        ) from exc


def _expand_include_paths(
    root: Path,
    includes: list[str],
    *,
    source: str,
    key: str,
) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for include in includes:
        matches = _include_matches(root, include, source=source, key=key)
        for path in matches:
            normalized = path.resolve()
            if normalized in seen:
                continue
            seen.add(normalized)
            result.append(path)
    return result


def _with_project_identity(root: Path, source: ConfigSource) -> ConfigSource:
    if source.path is None:
        relative = source.name
    else:
        try:
            relative = source.path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            relative = source.name
    return ConfigSource(
        name=source.name,
        values=source.values,
        kind=ConfigSourceKind.PROJECT_TOML,
        path=source.path,
        source_id=f"project:{relative}",
    )


def _include_matches(
    root: Path,
    include: str,
    *,
    source: str,
    key: str,
) -> list[Path]:
    _validate_relative_project_path(
        include,
        key=key,
        source=source,
    )
    if _has_glob_pattern(include):
        matches = sorted(root.glob(include), key=lambda path: path.as_posix())
        if not matches:
            raise ConfigError(
                "Configuration include pattern did not match any files",
                key=key,
                source=source,
                value=include,
            )
        paths = matches
    else:
        path = _project_path(
            root,
            include,
            key=key,
            source=source,
        )
        if not path.exists():
            raise ConfigError(
                "Included configuration file does not exist",
                key=key,
                source=source,
                value=include,
            )
        paths = [path]
    for path in paths:
        _ensure_under_project_root(
            root,
            path,
            value=include,
            key=key,
            source=source,
        )
        if not path.is_file():
            raise ConfigError(
                "Configuration include must reference TOML files",
                key=key,
                source=source,
                value=include,
            )
    return paths


def _load_document_sets(
    root: Path,
    specs: tuple[ConfigDocumentSetSpec, ...],
    *,
    merged_paths: set[Path],
    source: str,
) -> tuple[ConfigDocumentSet, ...]:
    result: list[ConfigDocumentSet] = []
    owned_paths = set(merged_paths)
    for spec in specs:
        documents: list[ConfigDocument] = []
        seen: set[Path] = set()
        key = f"config.document_sets.{spec.set_id}.include"
        for include in spec.includes:
            for path in _include_matches(root, include, source=source, key=key):
                normalized = path.resolve()
                if normalized in seen:
                    continue
                if normalized in owned_paths:
                    raise ConfigError(
                        "Configuration document is already owned by another source",
                        key=key,
                        source=source,
                        value=path.as_posix(),
                    )
                seen.add(normalized)
                relative = normalized.relative_to(root.resolve()).as_posix()
                documents.append(
                    ConfigDocument(
                        set_id=spec.set_id,
                        source_id=f"project-document:{spec.set_id}:{relative}",
                        path=path,
                        data=ConfigFileToml(path).data,
                    )
                )
        owned_paths.update(seen)
        result.append(
            ConfigDocumentSet(
                set_id=spec.set_id,
                documents=tuple(sorted(documents, key=lambda item: item.source_id)),
            )
        )
    return tuple(result)


def _get_config_document_set_specs(
    data: Mapping[str, object],
    *,
    source: str,
) -> tuple[ConfigDocumentSetSpec, ...]:
    config = data.get("config")
    if not isinstance(config, Mapping):
        return ()
    value = config.get("document_sets")
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(
            "Configuration document sets must be a list of tables",
            key="config.document_sets",
            source=source,
            value=value,
            expected="list[table]",
        )
    specs: list[ConfigDocumentSetSpec] = []
    for index, item in enumerate(value):
        key = f"config.document_sets.{index}"
        if not isinstance(item, Mapping) or any(
            not isinstance(name, str) for name in item
        ):
            raise ConfigError(
                "Configuration document set must be a string-keyed table",
                key=key,
                source=source,
                value=item,
                expected="table",
            )
        table = cast(Mapping[str, object], item)
        try:
            reject_unknown_keys(table, {"id", "include"}, key=key)
        except ConfigError as exc:
            raise ConfigError(
                exc.message,
                key=exc.key,
                source=source,
                value=exc.value,
                expected=exc.expected,
            ) from exc
        set_id = table.get("id")
        includes = table.get("include")
        if not isinstance(set_id, str) or not set_id.strip():
            raise ConfigError(
                "Configuration document set id must be non-empty",
                key=f"{key}.id",
                source=source,
                value=set_id,
                expected="non-empty string",
            )
        if not isinstance(includes, list) or not includes or any(
            not isinstance(include, str) or not include.strip()
            for include in includes
        ):
            raise ConfigError(
                "Configuration document set include must be a list of strings",
                key=f"{key}.include",
                source=source,
                value=includes,
                expected="non-empty list[str]",
            )
        specs.append(
            ConfigDocumentSetSpec(
                set_id,
                tuple(cast(list[str], includes)),
            )
        )
    ids = tuple(spec.set_id for spec in specs)
    if len(ids) != len(set(ids)):
        raise ConfigError(
            "Configuration document set ids must be unique",
            key="config.document_sets",
            source=source,
        )
    return tuple(specs)


def _has_config_key(data: Mapping[str, object], name: str) -> bool:
    config = data.get("config")
    return isinstance(config, Mapping) and name in config


def _project_path(
    root: Path,
    value: str,
    *,
    key: str,
    source: str,
) -> Path:
    _validate_relative_project_path(value, key=key, source=source)
    candidate = root / value
    try:
        resolve_under_root(root, value)
    except FilesystemBoundaryError as exc:
        raise ConfigError(
            "Project configuration path must stay within the project root",
            key=key,
            source=source,
            value=value,
            expected="project-relative path",
        ) from exc
    return candidate


def _validate_relative_project_path(value: str, *, key: str, source: str) -> None:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ConfigError(
            "Project configuration path must stay within the project root",
            key=key,
            source=source,
            value=value,
            expected="project-relative path without '..'",
        )


def _ensure_under_project_root(
    root: Path,
    path: Path,
    *,
    value: str,
    key: str,
    source: str,
) -> None:
    try:
        resolved_root = root.resolve()
        resolved_path = path.resolve()
        if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
            raise FilesystemBoundaryError(
                f"Path escapes root: {value}",
                root=resolved_root,
                path=resolved_path,
            )
    except FilesystemBoundaryError as exc:
        raise ConfigError(
            "Project configuration path must stay within the project root",
            key=key,
            source=source,
            value=value,
            expected="project-relative path",
        ) from exc


def _has_glob_pattern(value: str) -> bool:
    return glob.has_magic(value)


def _get_config_string(data: Mapping[str, object], key: str) -> str | None:
    config = data.get("config")
    if not isinstance(config, Mapping):
        return None
    value = config.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(
            "Project configuration value must be a string",
            key=f"config.{key}",
            value=value,
            expected="str",
        )
    return value


def _get_config_string_list(data: Mapping[str, object], key: str) -> list[str]:
    config = data.get("config")
    if not isinstance(config, Mapping):
        return []
    value = config.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(
            "Project configuration value must be a list of strings",
            key=f"config.{key}",
            value=value,
            expected="list[str]",
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ConfigError(
                "Project configuration value must be a list of strings",
                key=f"config.{key}",
                value=value,
                expected="list[str]",
            )
        result.append(item)
    return result
