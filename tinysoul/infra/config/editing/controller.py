"""Source-aware project configuration control plane."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from tinysoul.infra.json import JsonObject, JsonValue, to_json_object, to_json_value
from tinysoul.infra.concurrency import (
    AsyncResourceScope,
    CleanupDiagnostic,
    JoinedOperations,
)

from ..sources.dotenv import DotenvDocument, DotenvSource, _env_mapping_to_dotted
from ..documents import ConfigDocument, ConfigDocumentSet
from tinysoul.infra.config.descriptors import ConfigCatalog, load_config_catalog
from ..environment import ConfigEnvironment
from ..errors import ConfigError
from ..sources.source import ConfigSource, ConfigSourceKind
from ..sources.toml_file import ConfigFileToml, flatten_mapping
from .transaction import ConfigDocumentWrite, ConfigFileTransaction

type ConfigValue = str | int | float | bool | list[ConfigValue] | dict[str, ConfigValue]


@dataclass(frozen=True)
class ConfigMutation:
    source_id: str
    path: str
    op: str
    value: ConfigValue | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise ConfigError(
                "Configuration source id must be non-empty", key="source_id"
            )
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
    commit: Callable[[], Awaitable[None]]
    abort: Callable[[], Awaitable[tuple[CleanupDiagnostic, ...]]] | None = None
    retire: Callable[[], Awaitable[tuple[CleanupDiagnostic, ...]]] | None = None


ConfigCandidateActivator = Callable[
    [ConfigEnvironment], Awaitable[PreparedConfigActivation]
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
        self._environment = environment or ConfigEnvironment.from_project_root(
            self.root
        )
        self._validator = validator
        self._activator = activator
        self._activity = activity or (lambda: "idle")
        self._lock = asyncio.Lock()
        self._activation_observer = activation_observer
        self._generation_id_provider = generation_id
        self._catalog = catalog or load_config_catalog()
        self._pending_reload = False
        self._closed = False

    def stop_accepting(self) -> None:
        self._closed = True

    async def close(self) -> None:
        """Join accepted mutations before the owner retires its resources."""
        self.stop_accepting()
        async with self._lock:
            pass

    def _require_open(self) -> None:
        if self._closed:
            raise ConfigError("Configuration control is closed", key="config.closed")

    @property
    def environment(self) -> ConfigEnvironment:
        return self._environment

    def status(self) -> JsonObject:
        activity = self._activity()
        can_reload = activity == "idle"
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
        if not any(
            source.source_id == "dotenv" for source in self._environment.sources
        ):
            source_items.append(
                self._source_json(
                    DotenvSource(dotenv_path).load(),
                    exists=dotenv_path.exists(),
                )
            )
        return to_json_object(
            {
                "activity": {
                    "state": activity,
                    "can_write": True,
                    "can_reload": can_reload,
                    "reason": "" if can_reload else _activity_reason(activity),
                },
                "pending_reload": self._pending_reload,
                "sources": source_items,
                "fields": self._effective_fields(),
            }
        )

    def catalog(self) -> JsonObject:
        """Return the package-owned configuration presentation catalog."""

        return self._catalog.to_json()

    async def patch(self, mutations: tuple[ConfigMutation, ...]) -> JsonObject:
        """Validate and save a candidate without replacing the active generation."""
        async with self._lock:
            self._require_open()
            if not mutations:
                raise ConfigError(
                    "Configuration patch must contain operations", key="operations"
                )
            operations = JoinedOperations()
            result = await operations.run(lambda: self._save(mutations))
            operations.check_cancelled()
            return result

    def _save(self, mutations: tuple[ConfigMutation, ...]) -> JsonObject:
        # Refresh source contents so an unrelated external file edit is not overwritten.
        environment = self._environment.reload()
        candidate, writes = self._candidate(mutations, environment)
        if self._validator is not None:
            self._validator(candidate)
        receipt = ConfigFileTransaction(self.root).commit(tuple(writes))
        receipt.complete()
        self._environment = candidate
        self._pending_reload = True
        return to_json_object(
            {
                "state": "saved",
                "pending_reload": True,
                "changed_sources": sorted(
                    {mutation.source_id for mutation in mutations}
                ),
                "changed_fields": sorted({mutation.path for mutation in mutations}),
            }
        )

    async def reload(self) -> JsonObject:
        """Activate saved files only when the current generation is idle."""
        async with self._lock:
            self._require_open()
            if self._activity() != "idle" or self._activator is None:
                raise ConfigError(
                    "Configuration activation requires an idle runtime with an activator",
                    key="config.activation_unavailable",
                )
            self._observe("started", {})
            prepared: PreparedConfigActivation | None = None
            try:
                operations = JoinedOperations()
                candidate = await operations.run(self._environment.reload)
                operations.check_cancelled()
                validator = self._validator
                if validator is not None:
                    await operations.run(lambda: validator(candidate))
                    operations.check_cancelled()
                prepared = await self._activator(candidate)
                await operations.run_async(prepared.commit)
            except BaseException as exc:
                await self._abort(prepared)
                self._observe("failed", {"error_type": type(exc).__name__})
                raise
            self._environment = candidate
            self._pending_reload = False
            self._observe("completed", {})
            result: JsonObject = {"state": "active", "pending_reload": False}
            generation_id = self._generation_id()
            if generation_id:
                result["generation_id"] = generation_id
            if prepared.retire is not None:
                retirement = AsyncResourceScope()
                retirement.register("config.retirement", prepared.retire)
                diagnostics = await retirement.close()
                if diagnostics:
                    result["cleanup_diagnostics"] = [
                        {"resource": item.resource, "error_type": item.error_type}
                        for item in diagnostics
                    ]
            operations.check_cancelled()
            return result

    async def _abort(self, prepared: PreparedConfigActivation | None) -> None:
        if prepared is None or prepared.abort is None:
            return
        cleanup = AsyncResourceScope()
        cleanup.register("config.candidate", prepared.abort)
        try:
            await cleanup.close()
        except asyncio.CancelledError:
            # The transaction's primary failure remains authoritative.
            pass
        for diagnostic in cleanup.diagnostics:
            self._observe(
                "cleanup.failed",
                {
                    "resource": diagnostic.resource,
                    "error_type": diagnostic.error_type,
                },
            )

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
        environment: ConfigEnvironment,
    ) -> tuple[ConfigEnvironment, list[ConfigDocumentWrite]]:
        documents: dict[Path, ConfigFileToml | DotenvDocument] = {}
        source_by_id: dict[str, ConfigSource | ConfigDocument] = {
            source.source_id: source for source in environment.sources
        }
        source_by_id.update(
            {document.source_id: document for document in environment.documents}
        )
        dotenv_path = environment.dotenv_path
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
                raise ConfigError(
                    "Project source has no file path", key=mutation.source_id
                )
            document = documents.setdefault(source.path, ConfigFileToml(source.path))
            if not isinstance(document, ConfigFileToml):
                raise ConfigError("Project source document collision")
            if mutation.op == "set":
                document.set_value(mutation.path, mutation.value)
            else:
                document.delete_value(mutation.path)

        candidate_sources: list[ConfigSource] = []
        for source in environment.sources:
            document = documents.get(source.path) if source.path is not None else None
            if source.kind is ConfigSourceKind.PROJECT_TOML and isinstance(
                document, ConfigFileToml
            ):
                candidate_sources.append(
                    ConfigSource(
                        name=source.name,
                        values=flatten_mapping(
                            document.data, source=source.name, catalog=self._catalog
                        ),
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
        for document_set in environment.document_sets:
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
                **environment.process_env,
            }
            if dotenv_document is not None
            else environment.runtime_env
        )
        candidate_dotenv_path = _dotenv_path_from_tree(self.root, project_tree)
        if candidate_dotenv_path != dotenv_path:
            dotenv_source = next(
                (
                    source
                    for source in candidate_sources
                    if source.source_id == "dotenv"
                ),
                None,
            )
            candidate_sources = [
                source for source in candidate_sources if source.source_id != "dotenv"
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
            project=environment.project,
            sources=candidate_sources,
            runtime_env=runtime_env,
            process_env=environment.process_env,
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
        credentials = self._credential_names()
        for key, value in self._environment.effective_values().items():
            result[key] = {
                "value": "<redacted>" if key in credentials else to_json_value(value),
                "source": self._environment.source_id_for(key),
                "writable": self._is_writable_key(key),
                **({"redacted": True} if key in credentials else {}),
            }
        return result

    def _credential_names(self) -> frozenset[str]:
        names: set[str] = set()
        for path, value in self._environment.effective_values().items():
            descriptor = self._catalog.match(path)
            if descriptor is None or not descriptor.credential_reference:
                continue
            values = (
                value.values()
                if isinstance(value, dict)
                else value
                if isinstance(value, list)
                else (value,)
            )
            names.update(item for item in values if isinstance(item, str))
        # Config sources normalize environment names, while dotenv keeps spelling.
        return frozenset(names | {name.lower().replace("__", ".") for name in names})

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
        credentials = self._credential_names()
        return {
            key: "<redacted>" if key in credentials else to_json_value(value)
            for key, value in values.items()
        }

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
        or key == "agent.interactive"
        or key == "agent.retained_outcomes"
        or key == "agent.output"
        or key.startswith("agent.output.")
        or key == "agent.exit_commands"
        or key == "agent.stop_turn_commands"
    )


def _is_process_owned_mutation(kind: ConfigSourceKind, key: str) -> bool:
    if kind is ConfigSourceKind.PROJECT_TOML:
        return _is_process_owned_key(key)
    if kind is not ConfigSourceKind.DOTENV:
        return False
    dotted = _env_mapping_to_dotted({key: ""})
    return any(_is_process_owned_key(candidate) for candidate in dotted)


def _activity_reason(activity: str) -> str:
    if activity in {"user_turn", "reflection_turn", "daily_transition"}:
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
