"""
Script sandbox for controlled Python script execution.

Provides AST-based validation and restricted execution environment
for LLM-generated Python scripts.
"""

import ast
import io
import os
import pickle
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from tinysoul.action.framework.run_config import RunConfig
from tinysoul.infra.process import ManagedProcessRunner
from .config import settings
from tinysoul.trap import ActionExecutionError, ActionInputError

# Disallowed AST node types — these enable dangerous capabilities
_DISALLOWED_NODES: set[str] = {
    "Delete",
    "Global",
    "Nonlocal",
    "ClassDef",
    "AsyncFunctionDef",
    "Await",
    "AsyncFor",
    "AsyncWith",
    "Yield",
    "YieldFrom",
}

# Disallowed built-in functions
_DISALLOWED_BUILTINS: set[str] = {
    "__import__",
    "exec",
    "eval",
    "compile",
    "input",
    "exit",
    "quit",
    "help",
    "dir",
    "globals",
    "locals",
    "vars",
    "breakpoint",
}

# Allowed module imports — everything else is rejected
_ALLOWED_MODULES: set[str] = {
    "json",
    "re",
    "math",
    "random",
    "datetime",
    "time",
    "collections",
    "itertools",
    "statistics",
    "functools",
    "decimal",
    "fractions",
    "hashlib",
    "string",
    "typing",
    "inspect",
    "textwrap",
    "enum",
    "dataclasses",
    "copy",
    "numbers",
    "operator",
    "pathlib",
    "csv",
    "io",
}

# Safe built-in names allowed in sandboxed scripts
_ALLOWED_BUILTIN_NAMES: set[str] = {
    "abs",
    "all",
    "any",
    "ascii",
    "bin",
    "bool",
    "bytearray",
    "bytes",
    "chr",
    "dict",
    "divmod",
    "enumerate",
    "filter",
    "float",
    "format",
    "frozenset",
    "getattr",
    "hasattr",
    "hash",
    "hex",
    "id",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "map",
    "max",
    "memoryview",
    "min",
    "next",
    "object",
    "oct",
    "ord",
    "pow",
    "print",
    "property",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "slice",
    "sorted",
    "str",
    "sum",
    "tuple",
    "type",
    "zip",
    "True",
    "False",
    "None",
    # Exceptions
    "ArithmeticError",
    "AssertionError",
    "AttributeError",
    "BaseException",
    "BlockingIOError",
    "BrokenPipeError",
    "BufferError",
    "BytesWarning",
    "ChildProcessError",
    "ConnectionAbortedError",
    "ConnectionError",
    "ConnectionRefusedError",
    "ConnectionResetError",
    "DeprecationWarning",
    "EOFError",
    "Ellipsis",
    "EnvironmentError",
    "Exception",
    "FileExistsError",
    "FileNotFoundError",
    "FloatingPointError",
    "FutureWarning",
    "GeneratorExit",
    "IOError",
    "ImportError",
    "ImportWarning",
    "IndentationError",
    "IndexError",
    "InterruptedError",
    "IsADirectoryError",
    "KeyError",
    "KeyboardInterrupt",
    "LookupError",
    "MemoryError",
    "ModuleNotFoundError",
    "NameError",
    "NotADirectoryError",
    "NotImplemented",
    "NotImplementedError",
    "OSError",
    "OverflowError",
    "PendingDeprecationError",
    "PermissionError",
    "ProcessLookupError",
    "RecursionError",
    "ReferenceError",
    "ResourceWarning",
    "RuntimeError",
    "RuntimeWarning",
    "StopAsyncIteration",
    "StopIteration",
    "SyntaxError",
    "SyntaxWarning",
    "SystemError",
    "SystemExit",
    "TabError",
    "TimeoutError",
    "TypeError",
    "UnboundLocalError",
    "UnicodeDecodeError",
    "UnicodeEncodeError",
    "UnicodeError",
    "UnicodeTranslationError",
    "UnicodeWarning",
    "UserWarning",
    "ValueError",
    "Warning",
    "ZeroDivisionError",
}


def _resolve_in_workspace(path: str, workspace_location: str) -> str | None:
    """
    Resolve a path relative to workspace_location and verify it stays within.

    Returns the resolved absolute path if valid, None if outside workspace.
    """
    try:
        ws = Path(workspace_location).resolve()
        target = (ws / path).resolve()
        # Ensure target is within workspace (handles .. traversal)
        if not str(target).startswith(str(ws) + os.sep):
            return None
        return str(target)
    except Exception:
        return None


def _make_sandbox_open(workspace_location: str | None):
    """Factory for a sandboxed open() that restricts file access to workspace."""

    _READ_MODES = {'r', 'rb', 'rt'}
    _WRITE_MODES = {'w', 'wb', 'wt', 'a', 'ab', 'at'}
    _ALLOWED_MODES = _READ_MODES | _WRITE_MODES

    def _sandbox_open(path, mode='r', *args, **kwargs):
        if mode not in _ALLOWED_MODES:
            raise PermissionError(
                f"Mode '{mode}' not allowed in sandbox (only read/write/append)"
            )

        if workspace_location is None:
            raise PermissionError(
                "File access not allowed without workspace boundary"
            )

        resolved = _resolve_in_workspace(path, workspace_location)
        if resolved is None:
            raise PermissionError(
                f"Path outside workspace: {path}"
            )
        path = resolved

        # Auto-create parent directories for write operations
        if mode in _WRITE_MODES:
            import os as _os
            parent = _os.path.dirname(resolved)
            if parent:
                _os.makedirs(parent, exist_ok=True)

        return open(path, mode, *args, **kwargs)

    return _sandbox_open


def _safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
    """Restricted __import__ that rejects non-whitelisted modules."""
    top = name.split(".")[0]
    if top not in _ALLOWED_MODULES:
        raise ImportError(f"Import of '{name}' is not allowed in sandbox")
    return __import__(name, *args, **kwargs)


def _build_restricted_globals(workspace_location: str | None = None) -> dict[str, Any]:
    """Build a globals dict with only safe builtins."""
    safe: dict[str, Any] = {}
    for k, v in __builtins__.items():
        if k in _ALLOWED_BUILTIN_NAMES:
            safe[k] = v
    safe["__import__"] = _safe_import
    safe["open"] = _make_sandbox_open(workspace_location)
    return {"__builtins__": safe}


def validate_ast(source: str) -> ast.Module:
    """
    Parse and validate Python source code for dangerous constructs.

    Also verifies that the script defines ``_tinysoul_script(action_input, context)``.

    Args:
        source: Python source code string

    Returns:
        Parsed AST

    Raises:
        ActionInputError: If syntax is invalid or disallowed constructs found
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ActionInputError(f"Script syntax error: {e}") from e

    for node in ast.walk(tree):
        node_type = type(node).__name__
        if node_type in _DISALLOWED_NODES:
            raise ActionInputError(f"Disallowed syntax: {node_type}")

        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _DISALLOWED_BUILTINS:
                raise ActionInputError(f"Disallowed function call: {func.id}")

        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in _ALLOWED_MODULES:
                    raise ActionInputError(f"Disallowed import: {alias.name}")

        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            top = module.split(".")[0]
            if top not in _ALLOWED_MODULES:
                raise ActionInputError(f"Disallowed import from: {module}")

    # Verify _tinysoul_script exists at module level
    found = any(
        isinstance(n, ast.FunctionDef) and n.name == "_tinysoul_script"
        for n in ast.walk(tree)
    )
    if not found:
        raise ActionInputError(
            "Script must define `def _tinysoul_script(action_input, context)`"
        )

    return tree


def _run_script_in_current_process(
    source: str,
    action_input: dict[str, Any],
    context: dict[str, Any],
    script_path: str | None,
) -> dict[str, Any]:
    """Compile and execute a validated script in the current process."""
    tree = validate_ast(source)
    workspace_location = context.get("workspace_location")
    globals_dict = _build_restricted_globals(workspace_location)

    if script_path is not None:
        globals_dict["__file__"] = script_path

    code = compile(tree, script_path or "<temporary_script>", "exec")
    exec(code, globals_dict)

    func = globals_dict.get("_tinysoul_script")
    if not callable(func):
        raise ActionExecutionError(
            "Script defined `_tinysoul_script` but it is not callable"
        )

    old_cwd: str | None = None
    if workspace_location:
        old_cwd = os.getcwd()
        os.chdir(workspace_location)

    stdout_buffer = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = stdout_buffer
    try:
        result = func(action_input, context)
    finally:
        sys.stdout = old_stdout
        if old_cwd is not None:
            os.chdir(old_cwd)

    return {
        "return_value": result,
        "stdout": stdout_buffer.getvalue(),
    }


def _script_worker(
    payload_path: str,
    result_path: str,
) -> None:
    """Process target for sandboxed script execution."""
    try:
        with open(payload_path, "rb") as f:
            payload = pickle.load(f)
        envelope = {
            "ok": True,
            "result": _run_script_in_current_process(
                payload["source"],
                payload["action_input"],
                payload["context"],
                payload["script_path"],
            ),
        }
    except BaseException as exc:
        envelope = {
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }

    with open(result_path, "wb") as f:
        pickle.dump(envelope, f)


def _result_file_path(context: dict[str, Any]) -> Path:
    """Return a writable result file path for script IPC."""
    base = context.get("workspace_location")
    runtime_dir = Path(base) / ".tinysoul_runtime" if base else Path.cwd() / ".tinysoul_runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir / f"script-result-{uuid4().hex}.pkl"


def execute_script(
    source: str,
    action_input: dict[str, Any],
    context: dict[str, Any],
    timeout: float = settings.script_timeout,
    script_path: str | None = None,
    run_config: RunConfig | None = None,
) -> Any:
    """
    Execute validated Python script in a restricted environment.

    The script must define a top-level function::

        def _tinysoul_script(action_input: dict, context: dict) -> Any:
            ...

    Args:
        source: Python source code
        action_input: Parsed action parameters as dict
        context: Runtime context dict (query_events, loop_target, workspace_location, etc.)
        timeout: Maximum execution time in seconds
        script_path: Absolute path of the script file on disk (sets __file__ in sandbox)

    Returns:
        The return value of ``_tinysoul_script``

    Raises:
        ActionInputError: If script fails validation
        ActionExecutionError: If execution fails or times out
    """
    validate_ast(source)

    if run_config is None:
        run_config = RunConfig.create(
            action_name="script",
            turn=0,
            timeout=timeout,
        )
    elif run_config.deadline is None and timeout is not None:
        run_config.apply_timeout(timeout)

    result_path = _result_file_path(context)
    payload_path = result_path.with_suffix(".input.pkl")
    with open(payload_path, "wb") as f:
        pickle.dump(
            {
                "source": source,
                "action_input": action_input,
                "context": context,
                "script_path": script_path,
            },
            f,
        )

    package_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(package_root)
        if not existing_pythonpath
        else str(package_root) + os.pathsep + existing_pythonpath
    )
    try:
        process_result = ManagedProcessRunner().run(
            [
                sys.executable,
                "-m",
                "tinysoul.infra.sandbox_worker",
                str(payload_path),
                str(result_path),
            ],
            run_config=run_config,
            cwd=str(package_root),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout_label=f"{timeout}s" if timeout is not None else None,
        )

        if not result_path.exists():
            raise ActionExecutionError(
                "Script process exited without returning a result "
                f"(exit {process_result.returncode})"
            )

        with open(result_path, "rb") as f:
            envelope = pickle.load(f)
    finally:
        try:
            payload_path.unlink()
        except FileNotFoundError:
            pass
        try:
            result_path.unlink()
        except FileNotFoundError:
            pass

    if envelope.get("ok"):
        return envelope["result"]

    message = envelope.get("error", "unknown script error")
    error_type = envelope.get("error_type")
    if error_type == "ActionInputError":
        raise ActionInputError(message)
    raise ActionExecutionError(f"Script error: {message}")
