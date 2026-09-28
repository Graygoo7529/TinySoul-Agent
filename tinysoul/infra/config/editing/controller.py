"""Source-aware project configuration control plane."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from tinysoul.infra.concurrency import (
    AsyncResourceScope,
    CleanupDiagnostic,
    JoinedOperations,
)
from tinysoul.infra.config.descriptors import ConfigCatalog, load_config_catalog
from tinysoul.infra.json import JsonObject, JsonValue, to_json_object, to_json_value

from ..documents import ConfigDocument, ConfigDocumentSet
from ..environment import ConfigEnvironment
from ..errors import ConfigError
from ..sources.dotenv import DotenvDocument, DotenvSource, _env_mapping_to_dotted
from ..sources.source import ConfigSource, ConfigSourceKind
from ..sources.toml_file import ConfigFileToml, flatten_mapping
from .presets import ConfigPreset, ConfigPresetStore, PresetSnapshot
from .transaction import (
    ConfigDocumentWrite,
    ConfigFileTransaction,
    ConfigTransactionReceipt,
)

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
        # Keep the values that were actually published by the active
        # generation.  ``_environment`` is intentionally the saved source
        # graph and may be ahead of the generation after ``patch``.
        self._active_environment = self._environment
        self._active_projection = self._projection(self._environment)
        self._active_generation_id = self._generation_id()
        self._presets = ConfigPresetStore(self.root)
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

    def status(self, *, view: str = "saved") -> JsonObject:
        if view not in {"saved", "active"}:
            raise ConfigError("Configuration view is invalid", key="view")
        activity = self._activity()
        can_reload = activity == "idle"
        saved = self._environment.reload()
        pending = (
            saved.effective_values() != self._active_environment.effective_values()
        )
        return to_json_object(
            {
                **(
                    self._projection(saved)
                    if view == "saved"
                    else self._active_projection
                ),
                "view": view,
                "generation_id": self._active_generation_id,
                "activity": {
                    "state": activity,
                    "can_write": not self._closed,
                    "can_reload": can_reload and not self._closed,
                    "reason": "" if can_reload else _activity_reason(activity),
                },
                "pending_reload": pending,
            }
        )

    def _projection(self, environment: ConfigEnvironment) -> JsonObject:
        effective_values = environment.effective_values()
        credentials = self._credential_names(effective_values)
        source_items: list[JsonObject] = []
        for source in environment.sources:
            source_items.append(
                self._source_json(
                    source,
                    exists=source.path is None or source.path.exists(),
                    credentials=credentials,
                    dotenv_values=environment.dotenv_values,
                )
            )
        for document in environment.documents:
            source_items.append(self._document_json(document))
        dotenv_path = environment.dotenv_path
        if not any(source.source_id == "dotenv" for source in environment.sources):
            source_items.append(
                self._source_json(
                    ConfigSource.empty(
                        "dotenv",
                        kind=ConfigSourceKind.DOTENV,
                        path=dotenv_path,
                        source_id="dotenv",
                    ),
                    exists=dotenv_path.exists(),
                    credentials=credentials,
                )
            )
        result = to_json_object(
            {
                "sources": source_items,
                "fields": self._effective_fields(
                    effective_values, credentials, environment
                ),
            }
        )
        return result

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
        """Activate saved files through the same publication path as apply."""
        async with self._lock:
            return await self._activate()

    async def apply(
        self,
        mutations: tuple[ConfigMutation, ...] = (),
        *,
        preset_id: str | None = None,
    ) -> JsonObject:
        if bool(mutations) == (preset_id is not None):
            raise ConfigError("Apply requires exactly one candidate", key="apply")
        async with self._lock:
            return await self._activate(mutations, preset_id=preset_id)

    async def _activate(
        self,
        mutations: tuple[ConfigMutation, ...] = (),
        *,
        preset_id: str | None = None,
    ) -> JsonObject:
        self._require_open()
        if self._activity() != "idle" or self._activator is None:
            raise ConfigError(
                "Configuration activation requires an idle runtime with an activator",
                key="config.activation_unavailable",
            )
        # Join the whole publication boundary before propagating cancellation.
        operations = JoinedOperations()
        result = await operations.run_async(
            lambda: self._publish(mutations, preset_id=preset_id)
        )
        operations.check_cancelled()
        return result

    async def _publish(
        self, mutations: tuple[ConfigMutation, ...], *, preset_id: str | None
    ) -> JsonObject:
        self._observe("started", {})
        prepared: PreparedConfigActivation | None = None
        receipt: ConfigTransactionReceipt | None = None
        try:
            source = self._environment.reload()
            preset = self._presets.get(preset_id) if preset_id is not None else None
            if preset is not None:
                mutations = self._preset_mutations(source, preset.snapshot)
            candidate, writes = self._candidate(mutations, source)
            if self._validator is not None:
                self._validator(candidate)
            if (
                preset is not None
                and PresetSnapshot.capture(
                    candidate, include_budgets=preset.snapshot.include_budgets
                )
                != preset.snapshot
            ):
                raise ConfigError(
                    "Read-only configuration prevents the requested preset",
                    key="preset.source_conflict",
                )
            projection = self._projection(candidate)
            matching_presets = [
                item.id
                for item in self._presets.list()
                if PresetSnapshot.capture(
                    candidate, include_budgets=item.snapshot.include_budgets
                )
                == item.snapshot
            ]
            assert self._activator is not None
            prepared = await self._activator(candidate)
            receipt = ConfigFileTransaction(self.root).commit(tuple(writes))
            await prepared.commit()
        except BaseException as exc:
            await self._abort(prepared)
            if receipt is not None:
                receipt.rollback()
            self._observe("failed", {"error_type": type(exc).__name__})
            raise
        receipt.complete()
        self._environment = candidate
        self._active_environment = candidate
        self._active_projection = projection
        self._active_generation_id = self._generation_id()
        self._observe("completed", {})
        result = to_json_object(
            {
                "state": "active",
                "generation_id": self._active_generation_id,
                "pending_reload": False,
                "changed_fields": sorted({mutation.path for mutation in mutations}),
                "changed_sources": sorted(
                    {mutation.source_id for mutation in mutations}
                ),
                "matching_presets": matching_presets,
            }
        )
        if prepared.retire is not None:
            retirement = AsyncResourceScope()
            retirement.register("config.retirement", prepared.retire)
            diagnostics = await retirement.close()
            if diagnostics:
                result["cleanup_diagnostics"] = [
                    {"resource": item.resource, "error_type": item.error_type}
                    for item in diagnostics
                ]
        return result

    def _preset_mutations(
        self, environment: ConfigEnvironment, snapshot: PresetSnapshot
    ) -> tuple[ConfigMutation, ...]:
        replacements = snapshot.replacements(environment)
        writable = tuple(
            source
            for source in environment.sources
            if source.kind is ConfigSourceKind.PROJECT_TOML
        )
        if not writable:
            raise ConfigError(
                "Preset needs a writable project source", key="preset.source_conflict"
            )
        result: list[ConfigMutation] = []
        for path, value in replacements.items():
            owners = tuple(
                source
                for source in writable
                if any(
                    key == path or key.startswith(path + ".") for key in source.values
                )
            )
            # Delete the group at every writable source so stale members cannot
            # survive in an earlier include. Then replace at its existing owner.
            for source in owners:
                result.append(ConfigMutation(source.source_id, path, "delete"))
            if value is not None:
                target = owners[-1] if owners else writable[-1]
                result.append(
                    ConfigMutation(target.source_id, path, "set", _config_value(value))
                )
        return tuple(result)

    def presets(self) -> tuple[JsonObject, ...]:
        saved = self._environment.reload()
        return tuple(
            {
                key: value
                for key, value in self._preset_projection(item, saved).items()
                if key != "snapshot"
            }
            for item in self._presets.list()
        )

    def preset(self, preset_id: str) -> JsonObject:
        return self._preset_projection(
            self._presets.get(preset_id), self._environment.reload()
        )

    def _preset_projection(
        self, preset: ConfigPreset, saved: ConfigEnvironment
    ) -> JsonObject:
        issues: list[JsonValue] = []
        try:
            mutations = self._preset_mutations(saved, preset.snapshot)
            candidate, _ = self._candidate(mutations, saved)
            if self._validator is not None:
                self._validator(candidate)
            if (
                PresetSnapshot.capture(
                    candidate, include_budgets=preset.snapshot.include_budgets
                )
                != preset.snapshot
            ):
                raise ConfigError(
                    "Read-only source prevents preset", key="preset.source_conflict"
                )
        except ConfigError as exc:
            issues.append(
                {"key": exc.key, "source": exc.source, "message": exc.message}
            )
        return {
            **preset.to_json(),
            "active_match": PresetSnapshot.capture(
                self._active_environment,
                include_budgets=preset.snapshot.include_budgets,
            )
            == preset.snapshot,
            "saved_match": PresetSnapshot.capture(
                saved, include_budgets=preset.snapshot.include_budgets
            )
            == preset.snapshot,
            "validation_issues": issues,
        }

    def _capture_preset(
        self, source: str, mutations: tuple[ConfigMutation, ...], include_budgets: bool
    ) -> PresetSnapshot:
        if source not in {"saved", "active"}:
            raise ConfigError("Preset source is invalid", key="source")
        environment = (
            self._active_environment
            if source == "active"
            else self._environment.reload()
        )
        candidate, _ = (
            self._candidate(mutations, environment, from_snapshot=source == "active")
            if mutations
            else (environment, [])
        )
        if self._validator is not None:
            self._validator(candidate)
        return PresetSnapshot.capture(candidate, include_budgets=include_budgets)

    async def save_preset(
        self,
        *,
        name: str,
        description: str = "",
        source: str = "saved",
        mutations: tuple[ConfigMutation, ...] = (),
        include_budgets: bool = True,
    ) -> JsonObject:
        async with self._lock:
            self._require_open()
            snapshot = self._capture_preset(source, mutations, include_budgets)
            record = self._presets.save(
                name=name, description=description, snapshot=snapshot
            )
            return self._preset_projection(record, self._environment.reload())

    async def update_preset(
        self,
        preset_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        capture_source: str | None = None,
        mutations: tuple[ConfigMutation, ...] = (),
        include_budgets: bool = True,
    ) -> JsonObject:
        async with self._lock:
            self._require_open()
            previous = self._presets.get(preset_id)
            snapshot = (
                self._capture_preset(capture_source, mutations, include_budgets)
                if capture_source is not None
                else previous.snapshot
            )
            record = self._presets.save(
                name=name if name is not None else previous.name,
                description=description
                if description is not None
                else previous.description,
                snapshot=snapshot,
                previous=previous,
            )
            return self._preset_projection(record, self._environment.reload())

    async def delete_preset(self, preset_id: str) -> None:
        async with self._lock:
            self._require_open()
            self._presets.delete(preset_id)

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
        *,
        from_snapshot: bool = False,
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
                if dotenv_path not in documents:
                    document = DotenvDocument(
                        dotenv_path, text="" if from_snapshot else None
                    )
                    if from_snapshot:
                        for key, value in environment.dotenv_values.items():
                            document.set_value(key, value)
                    documents[dotenv_path] = document
                document = documents[dotenv_path]
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
            if source.path not in documents:
                data = (
                    (
                        source.data
                        if isinstance(source, ConfigDocument)
                        else _project_tree_from_sources([source])
                    )
                    if from_snapshot
                    else None
                )
                documents[source.path] = ConfigFileToml(source.path, data=data)
            document = documents[source.path]
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
            dotenv_values=dotenv_document.values
            if dotenv_document is not None
            else environment.dotenv_values,
            document_sets=candidate_document_sets,
        )
        writes = [
            ConfigDocumentWrite(path=path, text=document.render())
            for path, document in documents.items()
        ]
        return candidate, writes

    def _effective_fields(
        self,
        effective_values: Mapping[str, object],
        credentials: frozenset[str],
        environment: ConfigEnvironment,
    ) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {}
        for key, value in effective_values.items():
            result[key] = {
                "value": "<redacted>" if key in credentials else to_json_value(value),
                "source": environment.source_id_for(key),
                "writable": self._is_writable_key(key, environment),
                **({"redacted": True} if key in credentials else {}),
            }
        return result

    def _credential_names(
        self, effective_values: Mapping[str, object]
    ) -> frozenset[str]:
        names: set[str] = set()

        def collect(path: str, value: object) -> None:
            descriptor = self._catalog.match(path)
            if descriptor is not None and descriptor.credential_reference:
                values = (
                    value.values()
                    if isinstance(value, dict)
                    else value
                    if isinstance(value, list)
                    else (value,)
                )
                names.update(item for item in values if isinstance(item, str))
            elif isinstance(value, dict):
                for key, item in value.items():
                    collect(f"{path}.{key}", item)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    collect(f"{path}.{index}", item)

        for path, value in effective_values.items():
            collect(path, value)
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

    def _is_writable_key(self, key: str, environment: ConfigEnvironment) -> bool:
        if _is_process_owned_key(key):
            return False
        source_id = environment.source_id_for(key)
        source = next(
            (item for item in environment.sources if item.source_id == source_id),
            None,
        )
        return source is not None and source.kind in {
            ConfigSourceKind.PROJECT_TOML,
            ConfigSourceKind.DOTENV,
        }

    def _source_json(
        self,
        source: ConfigSource,
        *,
        exists: bool = True,
        credentials: frozenset[str],
        dotenv_values: Mapping[str, str] | None = None,
    ) -> JsonObject:
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
            "values": self._source_values(source, credentials, dotenv_values),
        }

    def _source_values(
        self,
        source: ConfigSource,
        credentials: frozenset[str],
        dotenv_values: Mapping[str, str] | None = None,
    ) -> JsonObject:
        values: Mapping[str, object] = source.values
        if source.kind is ConfigSourceKind.DOTENV and dotenv_values is not None:
            values = dotenv_values
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


def _config_value(value: JsonValue) -> ConfigValue:
    if value is None:
        raise ConfigError(
            "Configuration values cannot contain null", key="preset.snapshot"
        )
    if isinstance(value, dict):
        return {key: _config_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_config_value(item) for item in value]
    return value


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
