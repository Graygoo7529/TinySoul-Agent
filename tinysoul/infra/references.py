"""Markdown syntax and explicit owner identity ports; no resource store or graph."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
import posixpath
from types import MappingProxyType
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt


class ReferenceError(Exception):
    """A local reference cannot be interpreted by its declared owner."""


@dataclass(frozen=True)
class MarkdownReference:
    target: str
    line: int
    label: str


@dataclass(frozen=True)
class ResourceTarget:
    resource: str
    fragment: str = ""
    day: date | None = None

    def matches(self, anchor: ResourceTarget) -> bool:
        return (
            self.resource == anchor.resource
            and self.day == anchor.day
            and (not anchor.fragment or self.fragment == anchor.fragment)
        )


IdentityPort = Callable[[str, str, date | None], ResourceTarget]


class ReferenceResolver:
    """Generation assembly installs each target owner's narrow identity function once."""

    def __init__(self) -> None:
        self._ports: Mapping[str, IdentityPort] | None = None

    def bind(self, ports: Mapping[str, IdentityPort]) -> None:
        if self._ports is not None:
            raise ReferenceError("Reference identity ports are already bound")
        self._ports = MappingProxyType(dict(ports))

    def resolve(self, value: str, *, source_day: date | None = None) -> ResourceTarget:
        resource, _, fragment = value.partition("#")
        scheme, separator, _ = resource.partition(":")
        if not separator or self._ports is None or scheme not in self._ports:
            raise ReferenceError("Reference has no supported resource owner")
        return self._ports[scheme](resource, unquote(fragment), source_day)


def markdown_references(text: str) -> tuple[MarkdownReference, ...]:
    """CommonMark inline and reference links; code spans/fences are not links."""
    parser = MarkdownIt("commonmark")
    result: list[MarkdownReference] = []
    for token in parser.parse(text):
        if token.type != "inline" or not token.children:
            continue
        line = token.map[0] + 1 if token.map else 1
        children = token.children
        for index, child in enumerate(children):
            if child.type == "softbreak" or child.type == "hardbreak":
                line += 1
            if child.type != "link_open":
                continue
            target = child.attrGet("href")
            if (
                not isinstance(target, str)
                or not target
                or urlsplit(target).scheme in {"http", "https", "mailto", "data"}
            ):
                continue
            label = []
            for following in children[index + 1 :]:
                if following.type == "link_close":
                    break
                if following.type in {"text", "code_inline"}:
                    label.append(following.content)
            result.append(MarkdownReference(unquote(target), line, "".join(label)))
    return tuple(result)


def relative_reference(target: str, *, source_path: str, prefix: str) -> str:
    """Resolve syntax against a source-owner path; the target owner still validates."""
    resource, marker, fragment = target.partition("#")
    if ":" in resource:
        return target
    if resource.startswith(("/", "\\")) or "\\" in resource:
        raise ReferenceError("Relative reference is outside its source root")
    path = (
        posixpath.normpath(posixpath.join(posixpath.dirname(source_path), resource))
        if resource
        else source_path
    )
    if path == ".." or path.startswith("../"):
        raise ReferenceError("Relative reference is outside its source root")
    return prefix + path + ("#" + fragment if marker else "")
