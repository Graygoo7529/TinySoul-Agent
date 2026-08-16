"""Source-aware project configuration control plane."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import cast

from tinysoul.infra.json import JsonObject, JsonValue, to_json_object, to_json_value

from .dotenv import DotenvDocument, DotenvSource, _env_mapping_to_dotted
from .documents import ConfigDocument, ConfigDocumentSet
from .catalog import ConfigCatalog, load_config_catalog
from .environment import ConfigEnvironment
from .errors import ConfigError
from .source import ConfigSource, ConfigSourceKind
from .toml_file import ConfigFileToml, flatten_mapping
from .transaction import ConfigDocumentWrite, ConfigFileTransaction


type ConfigValue = (
    str | int | float | bool | list[ConfigValue] | dict[str, ConfigValue]
)


@dataclass(frozen=True)
class ConfigMutation:
    source_id: str
    path: str
    op: str
    value: ConfigValue | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise ConfigError("Configuration source id must be non-empty", key="source_id")
        if not isinstance(self.path, str) or not self.path.strip():
            raise ConfigError("Configuration path must be non-empty", key="path")
        if self.op not in {"set", "delete"}:
            raise ConfigError(
                "Configuration mutation operation is invalid",
                key="op",
                expected="set | delete",
            )
        if self.op == "set" and self.value is None:
            raise ConfigError(
                "Configuration set operation requires a value",
                key=self.path,
            )
        if self.op == "delete" and self.value is not None:
            raise ConfigError(
                "Configuration delete operation cannot carry a value",
                key=self.path,
            )


ConfigCandidateValidator = Callable[[ConfigEnvironment], None]


@dataclass(frozen=True)
class PreparedConfigActivation:
    commit: Callable[[], None]
    abort: Callable[[], None] = lambda: None


ConfigCandidateActivator = Callable[
    [ConfigEnvironment], PreparedConfigActivation | None
]


class ConfigController:
    """Read and mutate the project configuration source graph."""

    def __init__(
        self,
        *,
        root: Path,
        environment: ConfigEnvironment | None = None,
        validator: ConfigCandidateValidator | None = None,
        activator: ConfigCandidateActivator | None = None,
        activity: Callable[[], str] | None = None,
        activation_observer: Callable[[str, JsonObject], None] | None = None,
        generation_id: Callable[[], str] | None = None,
        catalog: ConfigCatalog | None = None,
    ) -> None:
        self.root = root.resolve()
        self._environment = environment or ConfigEnvironment.from_project_root(self.root)
        self._validator = validator
        self._activator = activator
        self._activity = activity or (lambda: "idle")
        self._lock = RLock()
        self._activation_observer = activation_observer
        self._generation_id_provider = generation_id
        self._catalog = catalog or load_config_catalog()

    @property
    def environment(self) -> ConfigEnvironment:
        return self._environment

    def status(self) -> JsonObject:
        activity = self._activity()
        can_write = activity == "idle"
        source_items: list[JsonObject] = []
        for source in self._environment.sources:
            source_items.append(
                self._source_json(
                    source,
                    exists=source.path is None or source.path.exists(),
                )
            )
        for document in self._environment.documents:
            source_items.append(self._document_json(document))
        dotenv_path = self._environment.dotenv_path
        if not any(source.source_id == "dotenv" for source in self._environment.sources):
            source_items.append(
                self._source_json(
                    DotenvSource(dotenv_path).load(),
                    exists=dotenv_path.exists(),
                )
            )
        return to_json_object({
            "activity": {
                "state": activity,
                "can_write": can_write,
                "reason": "" if can_write else _activity_reason(activity),
            },
            "sources": source_items,
            "fields": self._effective_fields(),
        })

    def catalog(self) -> JsonObject:
        """Return the package-owned configuration presentation catalog."""

        return self._catalog.to_json()

    def patch(self, mutations: tuple[ConfigMutation, ...]) -> JsonObject:
        with self._lock:
            if not mutations:
                raise ConfigError(
                    "Configuration patch must contain operations",
                    key="operations",
                )
            if self._activity() != "idle":
                raise ConfigError(
                    "Configuration changes require an idle runtime",
                    key="config.activation_unavailable",
                )
            self._observe(
                "started",
                {"operation_count": len(mutations)},
            )
            try:
                candidate, writes = self._candidate(mutations)
                if self._validator is not None:
                    self._validator(candidate)
                prepared = (
                    self._activator(candidate) if self._activator is not None else None
                )
            except BaseException as exc:
                self._observe("failed", {"error_type": type(exc).__name__})
                raise
            try:
                receipt = ConfigFileTransaction(self.root).commit(tuple(writes))
            except BaseException as exc:
                if prepared is not None:
                    prepared.abort()
                self._observe("failed", {"error_type": type(exc).__name__})
                raise
            try:
                if prepared is not None:
                    prepared.commit()
            except BaseException as exc:
                receipt.rollback()
                if prepared is not None:
                    prepared.abort()
                self._observe("failed", {"error_type": type(exc).__name__})
                raise
            receipt.complete()
            self._environment = candidate
            self._observe(
                "completed",
                {"changed_field_count": len({item.path for item in mutations})},
            )
            result = to_json_object({
                "state": "active",
                "changed_sources": sorted(
                    {mutation.source_id for mutation in mutations}
                ),
                "changed_fields": sorted({mutation.path for mutation in mutations}),
            })
            generation_id = self._generation_id()
            if generation_id:
                result["generation_id"] = generation_id
            return result

    def _observe(self, state: str, payload: JsonObject) -> None:
        if self._activation_observer is None:
            return
        try:
            self._activation_observer(state, payload)
        except Exception:
            return

    def _generation_id(self) -> str:
        if self._generation_id_provider is None:
            return ""
        value = self._generation_id_provider()
        return value if isinstance(value, str) else ""

    def _candidate(
        self,
        mutations: tuple[ConfigMutation, ...],
    ) -> tuple[ConfigEnvironment, list[ConfigDocumentWrite]]:
        documents: dict[Path, ConfigFileToml | DotenvDocument] = {}
        source_by_id: dict[str, ConfigSource | ConfigDocument] = {
            source.source_id: source for source in self._environment.sources
        }
        source_by_id.update(
            {document.source_id: document for document in self._environment.documents}
        )
        dotenv_path = self._environment.dotenv_path
        source_by_id.setdefault(
            "dotenv",
            DotenvSource(dotenv_path).load(),
        )
        for mutation in mutations:
            source = source_by_id.get(mutation.source_id)
            if source is None:
                raise ConfigError(
                    "Configuration source does not exist",
                    key=mutation.source_id,
                )
            if isinstance(source, ConfigSource) and source.kind not in {
                ConfigSourceKind.PROJECT_TOML,
                ConfigSourceKind.DOTENV,
            }:
                raise ConfigError(
                    "Configuration source is read-only",
                    key=mutation.source_id,
                )
            if isinstance(source, ConfigSource) and _is_process_owned_mutation(
                source.kind,
                mutation.path,
            ):
                raise ConfigError(
                    "Process shell configuration is read-only at runtime",
                    key=mutation.path,
                    expected="process restart",
                )
            if mutation.op not in {"set", "delete"}:
                raise ConfigError(
                    "Configuration mutation operation is invalid",
                    key=mutation.op,
                    expected="set | delete",
                )
            if (
                isinstance(source, ConfigSource)
                and source.kind is ConfigSourceKind.DOTENV
            ):
                document = documents.setdefault(
                    dotenv_path,
                    DotenvDocument(dotenv_path),
                )
                if not isinstance(document, DotenvDocument):
                    raise ConfigError("Dotenv source document collision")
                if mutation.op == "set":
                    if not isinstance(mutation.value, str):
                        raise ConfigError(
                            "Dotenv values must be strings",
                            key=mutation.path,
                            expected="str",
                        )
                    document.set_value(mutation.path, mutation.value)
                else:
                    document.delete_value(mutation.path)
                continue

            if source.path is None:
                raise ConfigError("Project source has no file path", key=mutation.source_id)
            document = documents.setdefault(source.path, ConfigFileToml(source.path))
            if not isinstance(document, ConfigFileToml):
                raise ConfigError("Project source document collision")
            if mutation.op == "set":
                document.set_value(mutation.path, mutation.value)
            else:
                document.delete_value(mutation.path)

        candidate_sources: list[ConfigSource] = []
        for source in self._environment.sources:
            document = documents.get(source.path) if source.path is not None else None
            if source.kind is ConfigSourceKind.PROJECT_TOML and isinstance(
                document, ConfigFileToml
            ):
                candidate_sources.append(
                    ConfigSource(
                        name=source.name,
                        values=flatten_mapping(document.data),
                        kind=source.kind,
                        path=source.path,
                        source_id=source.source_id,
                    )
                )
            elif source.kind is ConfigSourceKind.DOTENV and isinstance(
                document, DotenvDocument
            ):
                candidate_sources.append(
                    ConfigSource(
                        name=source.name,
                        values=_env_mapping_to_dotted(document.values),
                        kind=source.kind,
                        path=source.path,
                        source_id=source.source_id,
                    )
                )
            else:
                candidate_sources.append(source)

        if not any(source.source_id == "dotenv" for source in candidate_sources):
            candidate_sources.append(DotenvSource(dotenv_path).load())

        candidate_document_sets: list[ConfigDocumentSet] = []
        for document_set in self._environment.document_sets:
            candidate_documents: list[ConfigDocument] = []
            for source in document_set.documents:
                document = documents.get(source.path)
                candidate_documents.append(
                    ConfigDocument(
                        set_id=source.set_id,
                        source_id=source.source_id,
                        path=source.path,
                        data=(
                            document.data
                            if isinstance(document, ConfigFileToml)
                            else source.data
                        ),
                    )
                )
            candidate_document_sets.append(
                ConfigDocumentSet(
                    set_id=document_set.set_id,
                    documents=tuple(candidate_documents),
                )
            )

        project_tree = _project_tree_from_sources(candidate_sources)
        dotenv_document = next(
            (
                document
                for document in documents.values()
                if isinstance(document, DotenvDocument)
            ),
            None,
        )
        runtime_env = (
            {
                **dotenv_document.values,
                **self._environment.process_env,
            }
            if dotenv_document is not None
            else self._environment.runtime_env
        )
        candidate_dotenv_path = _dotenv_path_from_tree(self.root, project_tree)
        if candidate_dotenv_path != dotenv_path:
            dotenv_source = next(
                (source for source in candidate_sources if source.source_id == "dotenv"),
                None,
            )
            candidate_sources = [
                source
                for source in candidate_sources
                if source.source_id != "dotenv"
            ]
            candidate_sources.append(
                ConfigSource.empty(
                    "dotenv",
                    kind=ConfigSourceKind.DOTENV,
                    path=candidate_dotenv_path,
                    source_id="dotenv",
                )
                if dotenv_source is None
                else ConfigSource(
                    name=dotenv_source.name,
                    values=dotenv_source.values,
                    kind=dotenv_source.kind,
                    path=candidate_dotenv_path,
                    source_id="dotenv",
                )
            )

        candidate = ConfigEnvironment(
            project=self._environment.project,
            sources=candidate_sources,
            runtime_env=runtime_env,
            process_env=self._environment.process_env,
            project_tree=project_tree,
            dotenv_path=candidate_dotenv_path,
            document_sets=candidate_document_sets,
        )
        writes = [
            ConfigDocumentWrite(path=path, text=document.render())
            for path, document in documents.items()
        ]
        return candidate, writes

    def _effective_fields(self) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {}
        for key, value in self._environment.effective_values().items():
            result[key] = {
                "value": to_json_value(value),
                "source": self._environment.source_id_for(key),
                "writable": self._is_writable_key(key),
            }
        return result

    def _candidate_fields(self, candidate: ConfigEnvironment) -> JsonObject:
        return {
            key: {
                "value": to_json_value(value),
                "source": candidate.source_id_for(key),
            }
            for key, value in candidate.effective_values().items()
        }

    def _is_writable_key(self, key: str) -> bool:
        if _is_process_owned_key(key):
            return False
        source_id = self._environment.source_id_for(key)
        source = next(
            (item for item in self._environment.sources if item.source_id == source_id),
            None,
        )
        return source is not None and source.kind in {
            ConfigSourceKind.PROJECT_TOML,
            ConfigSourceKind.DOTENV,
        }

    def _source_json(self, source: ConfigSource, *, exists: bool = True) -> JsonObject:
        path = source.path
        relative = ""
        if path is not None:
            try:
                relative = path.resolve().relative_to(self.root).as_posix()
            except ValueError:
                relative = str(path)
        return {
            "id": source.source_id,
            "kind": source.kind.value,
            "path": relative,
            "exists": exists,
            "writable": source.kind
            in {ConfigSourceKind.PROJECT_TOML, ConfigSourceKind.DOTENV},
            "values": self._source_values(source),
        }

    def _source_values(self, source: ConfigSource) -> JsonObject:
        values: Mapping[str, object] = source.values
        if source.kind is ConfigSourceKind.DOTENV and source.path is not None:
            values = DotenvDocument(source.path).values
        return {key: to_json_value(value) for key, value in values.items()}

    def _document_json(self, document: ConfigDocument) -> JsonObject:
        try:
            relative = document.path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            relative = str(document.path)
        return {
            "id": document.source_id,
            "kind": "project_document_toml",
            "document_set": document.set_id,
            "path": relative,
            "exists": document.path.exists(),
            "writable": True,
            "values": {},
        }


def _project_tree_from_sources(sources: list[ConfigSource]) -> dict[str, object]:
    tree: dict[str, object] = {}
    for source in sources:
        if source.kind is not ConfigSourceKind.PROJECT_TOML:
            continue
        for key, value in source.values.items():
            _set_dotted(tree, key, value)
    return tree


def _is_process_owned_key(key: str) -> bool:
    return (
        key == "config"
        or key.startswith("config.")
        or key == "app.interactive"
        or key == "app.retained_outcomes"
        or key == "app.output"
        or key.startswith("app.output.")
        or key == "app.exit_commands"
        or key == "app.stop_turn_commands"
    )


def _is_process_owned_mutation(kind: ConfigSourceKind, key: str) -> bool:
    if kind is ConfigSourceKind.PROJECT_TOML:
        return _is_process_owned_key(key)
    if kind is not ConfigSourceKind.DOTENV:
        return False
    dotted = _env_mapping_to_dotted({key: ""})
    return any(_is_process_owned_key(candidate) for candidate in dotted)


def _activity_reason(activity: str) -> str:
    if activity in {"user_turn", "maintenance_turn", "daily_transition"}:
        return "turn_active"
    if activity == "config_activation":
        return "activation_active"
    return "runtime_active"


def _dotenv_path_from_tree(root: Path, tree: dict[str, object]) -> Path:
    config = tree.get("config")
    value = config.get("env_file") if isinstance(config, Mapping) else None
    if value is None:
        return root / ".env"
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            "Configured dotenv path must be a non-empty string",
            key="config.env_file",
            expected="project-relative path",
        )
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ConfigError(
            "Configured dotenv path must stay within the project root",
            key="config.env_file",
            value=value,
            expected="project-relative path",
        )
    return root / path


def _set_dotted(tree: dict[str, object], dotted: str, value: object) -> None:
    parts = dotted.split(".")
    current = tree
    for part in parts[:-1]:
        existing = current.get(part)
        if not isinstance(existing, dict):
            child: dict[str, object] = {}
            current[part] = child
            current = child
        else:
            current = cast(dict[str, object], existing)
    current[parts[-1]] = value
