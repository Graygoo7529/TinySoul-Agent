"""Resolved interpreter policy and launch adaptation shared by run and start."""

from base64 import b64encode
from dataclasses import dataclass
from pathlib import Path

from tinysoul.infra.network import ResolvedNetwork
from tinysoul.infra.process import (
    OutputEncoding,
    ProcessContractError,
    ProcessEncodingError,
    WindowsCommandLine,
    cmd_command,
    cmd_script,
    text_encoding,
)
from tinysoul.prompts.plugins import execution as prompt_text

from .config import Interpreter
from .failures import ExecutionRequestError


@dataclass(frozen=True)
class InterpreterAdapter:
    name: Interpreter
    executable: str
    network: ResolvedNetwork
    output_encoding: str

    @property
    def suffix(self) -> str:
        return {
            Interpreter.PYTHON: ".py",
            Interpreter.BASH: ".sh",
            Interpreter.POWERSHELL: ".ps1",
            Interpreter.CMD: ".cmd",
        }[self.name]

    def encode_source(self, text: str) -> bytes:
        if self.name is Interpreter.CMD:
            text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
        if self.name is Interpreter.POWERSHELL:
            encoding = "utf-8-sig"
        elif self.name is Interpreter.CMD:
            encoding = text_encoding(OutputEncoding.PLATFORM)
        else:
            encoding = "utf-8"
        try:
            return text.encode(encoding)
        except UnicodeError as exc:
            raise ExecutionRequestError(
                prompt_text.source_encoding_unavailable(
                    interpreter=self.name.value, encoding=encoding
                )
            ) from exc

    def resolve_output_encoding(self, override: str | None) -> str:
        try:
            return text_encoding(self.output_encoding if override is None else override)
        except ProcessEncodingError as exc:
            raise ExecutionRequestError(prompt_text.INVALID_OUTPUT_ENCODING) from exc

    def command(
        self, command: str | None, source: Path | None, args: tuple[str, ...]
    ) -> tuple[str, ...] | WindowsCommandLine:
        if self.name is Interpreter.CMD:
            try:
                if source is not None:
                    return cmd_script(self.executable, str(source), args)
                assert command is not None
                return cmd_command(self.executable, command)
            except ProcessContractError as exc:
                raise ExecutionRequestError(
                    prompt_text.CMD_SCRIPT_ARGUMENTS_UNSUPPORTED
                ) from exc
        if self.name is Interpreter.POWERSHELL:
            prefix = (
                self.executable, "-NoLogo", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass",
            )
            if source is not None:
                return (*prefix, "-File", str(source), *args)
            assert command is not None
            encoded = b64encode(command.encode("utf-16-le")).decode("ascii")
            return (*prefix, "-EncodedCommand", encoded)
        if source is not None:
            return self.executable, str(source), *args
        assert command is not None
        return self.executable, "--noprofile", "--norc", "-c", command
