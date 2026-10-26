from dataclasses import replace

import pytest

from tinysoul.infra.config.descriptors.models import (
    ConfigCatalog,
    ConfigFieldDescriptor,
    ConfigFieldGroupDescriptor,
    ConfigSurfaceDescriptor,
    ConfigValueKind,
)
from tinysoul.infra.config.errors import ConfigCatalogError


def _catalog(*paths: str) -> ConfigCatalog:
    return ConfigCatalog(
        surfaces=(ConfigSurfaceDescriptor("test", "Test", "Test settings"),),
        field_groups=(ConfigFieldGroupDescriptor("group", "test", "Group", "Fields"),),
        collections=(),
        fields=tuple(
            ConfigFieldDescriptor(
                path, "test", "group", "Value", "Value", ConfigValueKind.STRING
            )
            for path in paths
        ),
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    (
        ("models.a.name", "models.*.name"),
        ("models.b.name", "models.*.name"),
        ("owner.limit", "owner.*"),
        ("fixed.value", "fixed.value"),
        ("other.a.name", None),
        ("models.a.extra.name", None),
        ("models.a", None),
    ),
)
def test_catalog_matches_path_components(path: str, expected: str | None) -> None:
    catalog = _catalog("models.*.name", "owner.*", "fixed.value")
    matched = catalog.match(path)
    assert (matched.path if matched else None) == expected


def test_catalog_rejects_ambiguous_matches_and_rebuilds_for_new_fields() -> None:
    original = _catalog("models.*.name")
    changed = replace(
        original, fields=(*original.fields, *_catalog("models.a.*").fields)
    )
    with pytest.raises(ConfigCatalogError):
        changed.match("models.a.name")
    assert original.match("models.a.name") is original.fields[0]
    assert changed.match("models.a.limit") is changed.fields[1]
