"""Resolve Script sources through Workspace and effective Agent Home."""

from __future__ import annotations

from pathlib import PurePosixPath

from tinysoul.home import AgentHomeEngine, HomeResourceLink, HomeTopLink
from tinysoul.workspace import WorkspaceEngine, WorkspaceLink

from .errors import ScriptContractError
from .models import ScriptLanguage, ScriptMutation, ScriptSource


class ScriptSourceResolver:
    def __init__(
        self,
        *,
        workspace: WorkspaceEngine,
        home: AgentHomeEngine,
        max_source_chars: int,
    ) -> None:
        self._workspace = workspace
        self._home = home
        self._max_source_chars = max_source_chars

    def read(
        self,
        link: str,
        *,
        language: ScriptLanguage | None = None,
    ) -> ScriptSource:
        parsed_language = language or _language_for_link(link)
        _require_script_link(link, language=parsed_language)
        if link.startswith("workspace:"):
            result = self._workspace.read_text(
                link,
                max_chars=self._max_source_chars,
            )
        else:
            _require_existing_skill(self._home, link)
            result = self._home.read_resource(
                link,
                max_chars=self._max_source_chars,
            )
        if result.truncated:
            raise ScriptContractError(
                f"Script source exceeds {self._max_source_chars} characters: {link}"
            )
        return ScriptSource(
            link=link,
            text=result.text,
            digest=result.digest,
            language=parsed_language,
        )

    def write(
        self,
        link: str,
        text: str,
        *,
        overwrite: bool,
        expected_digest: str,
        owner_turn_id: str,
    ) -> ScriptMutation:
        _require_script_link(link)
        if link.startswith("workspace:"):
            result = self._workspace.write_text(
                link,
                text,
                overwrite=overwrite,
                expected_digest=expected_digest,
                owner_turn_id=owner_turn_id,
            )
            return ScriptMutation(
                link=result.link,
                digest=result.digest,
                size=result.size,
                state="written",
            )
        _require_existing_skill(self._home, link)
        result = self._home.write_resource(
            link,
            text,
            overwrite=overwrite,
            expected_digest=expected_digest,
        )
        return ScriptMutation(
            link=result.link,
            digest=result.digest,
            size=result.size,
            state=result.state.value,
        )

    def patch(
        self,
        link: str,
        *,
        old_text: str,
        new_text: str,
        expected_digest: str,
    ) -> ScriptMutation:
        _require_script_link(link)
        if link.startswith("workspace:"):
            result = self._workspace.patch_text(
                link,
                old_text=old_text,
                new_text=new_text,
                expected_digest=expected_digest,
            )
            return ScriptMutation(
                link=result.link,
                digest=result.digest,
                size=result.size,
                state="modified",
            )
        _require_existing_skill(self._home, link)
        result = self._home.patch_resource(
            link,
            old_text=old_text,
            new_text=new_text,
            expected_digest=expected_digest,
        )
        return ScriptMutation(
            link=result.link,
            digest=result.digest,
            size=result.size,
            state=result.state.value,
        )

    def promote(
        self,
        source_link: str,
        target_link: str,
        *,
        expected_source_digest: str,
        overwrite: bool,
        expected_target_digest: str,
    ) -> ScriptMutation:
        if not source_link.startswith("workspace:"):
            raise ScriptContractError("Script promote source must be a Workspace Link")
        if not target_link.startswith("home:how/"):
            raise ScriptContractError(
                "Script promote target must be a general HOW scripts resource"
            )
        source = self.read(source_link)
        if expected_source_digest and source.digest != expected_source_digest:
            raise ScriptContractError("Script promote source digest mismatch")
        if _language_for_link(target_link) is not source.language:
            raise ScriptContractError("Script promote source and target languages differ")
        return self.write(
            target_link,
            source.text,
            overwrite=overwrite,
            expected_digest=expected_target_digest,
            owner_turn_id="",
        )


def _require_script_link(
    link: str,
    *,
    language: ScriptLanguage | None = None,
) -> None:
    detected = _language_for_link(link)
    if language is not None and detected is not language:
        raise ScriptContractError(
            f"Script link extension does not match {language.value}: {link}"
        )
    if link.startswith("workspace:"):
        path = WorkspaceLink.parse(link).path
        if len(path.parts) < 2 or path.parts[0] != "scripts":
            raise ScriptContractError(
                "Workspace scripts must live under workspace:scripts/"
            )
        return
    parsed = HomeResourceLink.parse(link)
    path = PurePosixPath(parsed.relative_path)
    if parsed.space != "how" or len(path.parts) < 3 or path.parts[1] != "scripts":
        raise ScriptContractError(
            "Long-term scripts must use home:how/<skill>/scripts/..."
        )


def _require_existing_skill(home: AgentHomeEngine, link: str) -> None:
    parsed = HomeResourceLink.parse(link)
    skill = PurePosixPath(parsed.relative_path).parts[0]
    top = str(HomeTopLink("how", skill))
    if top not in home.loadable_background_links():
        raise ScriptContractError(f"Script target HOW skill does not exist: {top}")


def _language_for_link(link: str) -> ScriptLanguage:
    if link.endswith(".py"):
        return ScriptLanguage.PYTHON
    if link.endswith(".sh"):
        return ScriptLanguage.BASH
    raise ScriptContractError("Script link must end with .py or .sh")
