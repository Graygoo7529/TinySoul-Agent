"""Configuration presentation models and package resource loading."""

from .models import (
    ConfigFieldImportance,
    ConfigCollectionDeletePolicy,
    ConfigValueKind,
    ConfigChoiceDescriptor,
    ConfigReferenceDescriptor,
    ConfigCollectionIdentityDescriptor,
    ConfigFieldGroupDescriptor,
    ConfigFieldDescriptor,
    ConfigDocumentFieldDescriptor,
    ConfigSurfaceDescriptor,
    ConfigCollectionDescriptor,
    ConfigCatalog,
)
from .loader import load_config_catalog
