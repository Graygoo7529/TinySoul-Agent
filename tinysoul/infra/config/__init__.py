"""Configuration loading facilities."""

from .sources.dotenv import DotenvDocument, DotenvSource, parse_dotenv
from .environment import ConfigEnvironment
from tinysoul.infra.config.descriptors import (
    ConfigCatalog,
    ConfigDocumentFieldDescriptor,
    load_config_catalog,
)
from .errors import ConfigCatalogError, ConfigError
from .sources.project import ProjectConfig
from .sources.source import ConfigSource, ConfigSourceKind
from .sources.toml_file import ConfigFileToml
from .editing.transaction import (
    ConfigDocumentWrite,
    ConfigFileTransaction,
    ConfigTransactionReceipt,
)
from .editing.controller import (
    ConfigController,
    ConfigMutation,
    ConfigValue,
    PreparedConfigActivation,
)
from .documents import ConfigDocument, ConfigDocumentSet, ConfigDocumentSetSpec
from .validation import reject_unknown_keys

__all__ = [
    "ConfigEnvironment",
    "ConfigCatalog",
    "ConfigCatalogError",
    "ConfigDocumentFieldDescriptor",
    "ConfigError",
    "ConfigSource",
    "ConfigSourceKind",
    "ConfigFileToml",
    "ConfigDocumentWrite",
    "ConfigFileTransaction",
    "ConfigTransactionReceipt",
    "ConfigController",
    "ConfigDocument",
    "ConfigDocumentSet",
    "ConfigDocumentSetSpec",
    "ConfigMutation",
    "ConfigValue",
    "PreparedConfigActivation",
    "DotenvDocument",
    "DotenvSource",
    "ProjectConfig",
    "reject_unknown_keys",
    "parse_dotenv",
    "load_config_catalog",
]
