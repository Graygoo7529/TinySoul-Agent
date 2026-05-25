"""
Structured event logging for TinySoul.

Replaces scattered `print()` calls with a level/category-filtered,
multi-sink event logger.  Business code emits events; sinks decide
how (and whether) to format and display them.

Environment variables (read via tinysoul.infra.config.settings):
  TINYSOUL_LOG_LEVEL=quiet|normal|verbose|debug   (default: normal)
  TINYSOUL_LOG_CATEGORIES=loop,action,state,...   (default: all)
  TINYSOUL_LOG_COLOR=1|0                          (default: 1)
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import textwrap
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Callable

from .config import settings


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LINE = "═" * 70


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EventLevel(StrEnum):
    QUIET = "quiet"
    NORMAL = "normal"
    VERBOSE = "verbose"
    DEBUG = "debug"

    @property
    def priority(self) -> int:
        return {
            EventLevel.QUIET: 0,
            EventLevel.NORMAL: 1,
            EventLevel.VERBOSE: 2,
            EventLevel.DEBUG: 3,
        }[self]


class EventCategory(StrEnum):
    LOOP = "loop"
    ACTION = "action"
    STATE = "state"
    PROMPT = "prompt"
    WARN = "warn"
    ERROR = "error"
    LLM = "llm"


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Event:
    category: EventCategory
    level: EventLevel
    title: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Sinks
# ---------------------------------------------------------------------------

class Sink(ABC):
    """Abstract sink for event output."""

    @abstractmethod
    def emit(self, event: Event) -> None:
        ...


class NullSink(Sink):
    """Sink that discards all events (useful in tests)."""

    def emit(self, event: Event) -> None:
        pass


class CaptureSink(Sink):
    """Sink that records all events to a list (useful in tests)."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)

    def clear(self) -> None:
        self.events.clear()


class ConsoleSink(Sink):
    """Pretty-print events to stdout with optional ANSI colours."""

    # ANSI codes
    _RESET = "\033[0m"
    _BOLD = "\033[1m"
    _DIM = "\033[2m"
    _GREEN = "\033[32m"
    _YELLOW = "\033[33m"
    _RED = "\033[31m"
    _BLUE = "\033[34m"
    _CYAN = "\033[36m"
    _MAGENTA = "\033[35m"
    _WHITE = "\033[37m"

    def __init__(self, use_color: bool = True) -> None:
        self.use_color = use_color and sys.stdout.isatty()
        self.term_width = shutil.get_terminal_size().columns
        self._formatters: dict[str, Callable[[Event], list[str]]] = {
            "loop_ready": self._fmt_loop_ready,
            "turn_started": self._fmt_turn_started,
            "turn_ended": self._fmt_turn_ended,
            "turn_ended_early": self._fmt_turn_ended_early,
            "action_selected": self._fmt_action_selected,
            "action_args": self._fmt_action_args,
            "action_result": self._fmt_action_result,
            "state_updated": self._fmt_state_updated,
            "todo_added": self._fmt_todo_added,
            "todo_completed": self._fmt_todo_completed,
            "todo_cancelled": self._fmt_todo_cancelled,
            "milestone_added": self._fmt_milestone_added,
            "step_failed": self._fmt_step_failed,
            "step_failed_detail": self._fmt_step_failed_detail,
            "step_recovered": self._fmt_step_recovered,
            "loop_complete": self._fmt_loop_complete,
            "loop_interrupted": self._fmt_loop_interrupted,
            "debug_state": self._fmt_debug_state,
            "debug_action_meta": self._fmt_debug_action_meta,
            "debug_action_detail": self._fmt_debug_action_detail,
            "debug_prompt": self._fmt_debug_prompt,
            "workspace_scanned": self._fmt_workspace_scanned,
            "llm_ready": self._fmt_llm_ready,
            "llm_retry": self._fmt_llm_retry,
            "llm_failover": self._fmt_llm_failover,
            "warn": self._fmt_warn,
            "error": self._fmt_error,
        }

    # -- helpers -----------------------------------------------------------

    def _c(self, text: str, code: str) -> str:
        if not self.use_color:
            return text
        return f"{code}{text}{self._RESET}"

    def _strip_ansi(self, text: str) -> str:
        """Remove ANSI escape codes for length calculation."""
        import re
        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    def _kv(self, label: str, key: str, value: str, label_color: str = "", key_color: str = "", value_color: str = "") -> list[str]:
        prefix_plain = f"{label:<10}{key:<6}  "
        avail = self.term_width - len(prefix_plain)
        if avail < 20:
            avail = 80

        # Build ANSI prefix with *visual* alignment (ANSI codes don't count)
        label_part = self._c(label, label_color) if label_color else label
        label_pad = " " * (10 - len(label))
        key_part = self._c(key, key_color) if key_color else key
        key_pad = " " * (6 - len(key))
        prefix_ansi = label_part + label_pad + key_part + key_pad + "  "
        indent = " " * len(prefix_plain)

        def _wrap_text(text: str, width: int) -> list[str]:
            """Wrap text, preserving explicit newlines."""
            out: list[str] = []
            for para in text.split("\n"):
                if not para:
                    out.append("")
                elif len(para) <= width:
                    out.append(para)
                else:
                    out.extend(textwrap.wrap(para, width=width, break_long_words=True, replace_whitespace=False))
            return out

        vc_plain = str(value)
        if len(vc_plain) <= avail and "\n" not in vc_plain:
            if value_color:
                return [prefix_ansi + self._c(vc_plain, value_color)]
            return [prefix_ansi + vc_plain]

        wrapped = _wrap_text(vc_plain, avail)
        if value_color:
            return [
                prefix_ansi + self._c(wrapped[0], value_color),
                *[indent + self._c(line, value_color) for line in wrapped[1:]],
            ]
        return [
            prefix_ansi + wrapped[0],
            *[indent + line for line in wrapped[1:]],
        ]

    def _kv_sub(self, key: str, value: str, key_color: str = "", value_color: str = "") -> list[str]:
        return self._kv("          ", key, value, key_color=key_color, value_color=value_color)

    def _kv_cont(self, value: str, value_color: str = "") -> list[str]:
        prefix_plain = " " * 18
        avail = self.term_width - len(prefix_plain)
        if avail < 20:
            avail = 80

        def _wrap_text(text: str, width: int) -> list[str]:
            out: list[str] = []
            for para in text.split("\n"):
                if not para:
                    out.append("")
                elif len(para) <= width:
                    out.append(para)
                else:
                    out.extend(textwrap.wrap(para, width=width, break_long_words=True, replace_whitespace=False))
            return out

        vc_plain = str(value)
        if len(vc_plain) <= avail and "\n" not in vc_plain:
            if value_color:
                return [prefix_plain + self._c(vc_plain, value_color)]
            return [prefix_plain + vc_plain]

        wrapped = _wrap_text(vc_plain, avail)
        if value_color:
            return [
                prefix_plain + self._c(wrapped[0], value_color),
                *[prefix_plain + self._c(line, value_color) for line in wrapped[1:]],
            ]
        return [
            prefix_plain + wrapped[0],
            *[prefix_plain + line for line in wrapped[1:]],
        ]

    # -- formatters --------------------------------------------------------

    def _fmt_loop_ready(self, e: Event) -> list[str]:
        d = e.data
        return [
            "",
            self._c(_LINE, self._BOLD),
            self._c(f"  Query : {d.get('query', '')}", self._BOLD),
            self._c(f"  Target: {d.get('target', '')}", self._BOLD),
            self._c(f"  Actions available: {d.get('action_count', '?')}", self._BOLD),
            self._c(_LINE, self._BOLD),
        ]

    def _fmt_turn_started(self, e: Event) -> list[str]:
        d = e.data
        return [
            "",
            self._c(_LINE, self._BOLD),
            self._c(f"  Turn {d['turn']} / {d['max_turns']}", self._BOLD),
            self._c(_LINE, self._BOLD),
        ]

    def _fmt_turn_ended(self, e: Event) -> list[str]:
        return [self._c(_LINE, self._BOLD)]

    def _fmt_turn_ended_early(self, e: Event) -> list[str]:
        d = e.data
        return [
            *self._kv_sub("Early", d['reason'], value_color=self._YELLOW),
            self._c(_LINE, self._BOLD),
        ]

    def _fmt_action_selected(self, e: Event) -> list[str]:
        d = e.data
        return [
            *self._kv("[Step 1]", "Action", d['name'], label_color=self._BLUE, key_color=self._CYAN, value_color=self._GREEN),
            *self._kv_sub("Reason", d['reason'], key_color=self._CYAN),
        ]

    def _fmt_action_args(self, e: Event) -> list[str]:
        d = e.data
        args = d.get("args", {})
        action_name = d.get("action_name", "")

        if not args:
            label = "[Step 2]"
            if action_name:
                label = f"[Step 2]  {action_name}"
            return self._kv(label, "Args", "(none)", label_color=self._BLUE, key_color=self._CYAN)

        lines: list[str] = []

        # Header line: [Step 2]  action_name Args
        label_text = "[Step 2]"
        if action_name:
            label_text = f"[Step 2]  {action_name}"

        label_part = self._c(label_text, self._BLUE) if self.use_color else label_text
        key_part = self._c(" Args", self._CYAN) if self.use_color else " Args"
        lines.append(label_part + key_part)

        # Each param on its own indented line
        for k, v in args.items():
            if isinstance(v, str):
                val = f"{k}: {v}"
            else:
                val = f"{k}: {json.dumps(v, ensure_ascii=False)}"
            lines.extend(self._kv_cont(val))

        return lines

    def _fmt_action_result(self, e: Event) -> list[str]:
        d = e.data
        result = d.get("result", {})
        action_name = d.get("action_name", "")

        # Detect batch summary from ParallelDispatcher
        if isinstance(result, dict) and set(result.keys()) == {"total", "completed", "failed", "timed_out"}:
            text = (
                f"{result['total']} total, {result['completed']} completed, "
                f"{result['failed']} failed, {result['timed_out']} timed out"
            )
            header_text = "          Batch"
            header = self._c(header_text, self._CYAN) if self.use_color else header_text
            lines = [header]
            lines.extend(self._kv_cont(text))
            return lines

        # Build header with optional action_name: action_name in blue, " Result" in cyan
        if action_name:
            action_part = self._c(action_name, self._BLUE) if self.use_color else action_name
            result_part = self._c(" Result", self._CYAN) if self.use_color else " Result"
            header = "          " + action_part + result_part
        else:
            header_text = "          Result"
            header = self._c(header_text, self._CYAN) if self.use_color else header_text

        if not d.get("verbose"):
            summary = d.get("summary", "")
            text = summary if summary else "OK"
            lines = [header]
            lines.extend(self._kv_cont(text))
            return lines

        # Verbose mode
        s = json.dumps(result, ensure_ascii=False, indent=2)
        lines_json = s.splitlines()
        if len(lines_json) > 20:
            lines_json = lines_json[:20] + ["... (truncated)"]
        lines = [header]
        for line in lines_json:
            lines.extend(self._kv_cont(line))
        return lines

    def _fmt_state_updated(self, e: Event) -> list[str]:
        d = e.data
        return self._kv(
            "[Step 3]",
            "State",
            f"TODO: {d.get('todo', 'no-change')} | "
            f"MILESTONE: {d.get('milestone', 'no-change')} | "
            f"FINISHED: {d.get('finished', 'no')}",
            label_color=self._BLUE,
            key_color=self._CYAN,
        )

    def _fmt_todo_added(self, e: Event) -> list[str]:
        d = e.data
        op = "<add>"
        desc = d['desc']
        key = d.get('key') or ''
        if d.get('verbose') and key:
            val = f"{op}  {key}  {desc}"
        else:
            val = f"{op}  {desc}"
        return self._kv_sub("Todo", val, key_color=self._CYAN)

    def _fmt_todo_completed(self, e: Event) -> list[str]:
        d = e.data
        op = "<complete>"
        desc = d['desc']
        key = d.get('key') or ''
        if d.get('verbose') and key:
            val = f"{op}  {key}  {desc}"
        else:
            val = f"{op}  {desc}"
        return self._kv_sub("Todo", val, key_color=self._CYAN)

    def _fmt_todo_cancelled(self, e: Event) -> list[str]:
        d = e.data
        op = "<cancel>"
        desc = d['desc']
        key = d.get('key') or ''
        if d.get('verbose') and key:
            val = f"{op}  {key}  {desc}"
        else:
            val = f"{op}  {desc}"
        return self._kv_sub("Todo", val, key_color=self._CYAN)

    def _fmt_milestone_added(self, e: Event) -> list[str]:
        return self._kv_sub("Mile", e.data['text'], key_color=self._CYAN, value_color=self._CYAN)

    def _fmt_step_failed(self, e: Event) -> list[str]:
        d = e.data
        disp = d.get("disposition", "CONTINUE")
        color = self._RED if disp == "ABORT" else self._YELLOW
        return [
            *self._kv("[Error]  ", "Step", f"{d['step']} ({disp})", label_color=self._RED, key_color=self._CYAN),
            *self._kv_sub("Detail", d['error'], key_color=self._CYAN, value_color=color),
        ]

    def _fmt_step_failed_detail(self, e: Event) -> list[str]:
        d = e.data
        lines: list[str] = []
        lines.extend(self._kv_sub("Type", d.get("error_type", ""), key_color=self._CYAN))
        lines.extend(self._kv_sub("Msg", d.get("message", ""), key_color=self._CYAN))
        tb = d.get("raw_traceback", "")
        if tb:
            lines.extend(self._kv_sub("Trace", "", key_color=self._CYAN))
            for line in tb.splitlines()[:5]:
                lines.extend(self._kv_sub("", line))
        return lines

    def _fmt_step_recovered(self, e: Event) -> list[str]:
        d = e.data
        info = d.get("model_info", "")
        msg = f"Step '{d['step']}' failed; loop continues"
        if info:
            msg += f" -> {info}"
        return [f"[Recovery]         {msg}"]

    def _fmt_loop_complete(self, e: Event) -> list[str]:
        d = e.data
        finished = "yes" if d.get("finished") else "no"
        return [
            "",
            self._c(_LINE, self._BOLD),
            self._c(
                f"  Completed: {d['turns']} turns | Finished: {finished} | "
                f"Todos: {d.get('todo_summary', '?')} | Milestones: {d.get('milestones', '?')}",
                self._BOLD,
            ),
            self._c(_LINE, self._BOLD),
        ]

    def _fmt_loop_interrupted(self, e: Event) -> list[str]:
        return [
            "",
            self._c(_LINE, self._BOLD),
            self._c("  Interrupted by user", self._YELLOW),
            self._c(_LINE, self._BOLD),
        ]

    def _fmt_debug_state(self, e: Event) -> list[str]:
        d = e.data
        return [
            "",
            f"[State Debug — {d['step']}]",
            d.get("state_json", ""),
        ]

    def _fmt_debug_action_meta(self, e: Event) -> list[str]:
        d = e.data
        return [
            "",
            "[Action Meta]",
            json.dumps(d.get("meta_list", []), ensure_ascii=False, indent=2),
        ]

    def _fmt_debug_action_detail(self, e: Event) -> list[str]:
        d = e.data
        return [
            "",
            "[Action Detail]",
            json.dumps(d.get("detail", {}), ensure_ascii=False, indent=2),
        ]

    def _fmt_debug_prompt(self, e: Event) -> list[str]:
        d = e.data
        source = d.get("source", "loop_step")
        tag = "[Prompt Debug — loop_step]" if source == "loop_step" else "[Prompt Debug — action_internal]"
        system = d.get("system", [])
        user = d.get("user", "")
        return [
            "",
            tag,
            "─" * 70 + " SYSTEM " + "─" * 70,
            json.dumps(system, ensure_ascii=False, indent=2),
            "─" * 70 + " USER " + "─" * 70,
            user,
            "─" * 128,
        ]

    def _fmt_workspace_scanned(self, e: Event) -> list[str]:
        d = e.data
        names = d.get("resource_names", [])
        names_str = ", ".join(names[:5])
        if len(names) > 5:
            names_str += f" ... ({len(names) - 5} more)"
        return [f"[Workspace] Scanned {d['resource_count']} resource(s): {names_str}"]

    def _fmt_llm_ready(self, e: Event) -> list[str]:
        d = e.data
        provider = d.get("provider", "")
        profile = d.get("profile", "")
        prefix = f"[LLM]     Ready   {d['model']}"
        if provider:
            prefix += f" (provider={provider})"
        if profile:
            prefix += f" [{profile}]"
        return [prefix]

    def _fmt_llm_retry(self, e: Event) -> list[str]:
        d = e.data
        provider = d.get("provider", "")
        profile = d.get("profile", "")
        suffix = ""
        if provider:
            suffix += f" provider={provider}"
        if profile:
            suffix += f" profile={profile}"
        return [f"[LLM]     Retry   {d['model']} (attempt {d['attempt']}/{d['max_attempts']}{suffix})"]

    def _fmt_llm_failover(self, e: Event) -> list[str]:
        d = e.data
        profile = d.get("profile", "")
        from_provider = d.get("from_provider", "")
        to_provider = d.get("to_provider", "")
        left = d["from_model"]
        right = d["to_model"]
        if from_provider:
            left = f"{left} ({from_provider})"
        if to_provider:
            right = f"{right} ({to_provider})"
        suffix = f" [{profile}]" if profile else ""
        return [f"[LLM]     Switch  {left} -> {right}{suffix}"]

    def _fmt_warn(self, e: Event) -> list[str]:
        d = e.data
        msg = d.get("message", "")
        return [self._c(f"[Warning] {msg}", self._YELLOW)]

    def _fmt_error(self, e: Event) -> list[str]:
        d = e.data
        return [self._c(f"[Error]   {d['message']}", self._RED)]

    # -- public API --------------------------------------------------------

    def emit(self, event: Event) -> None:
        formatter = self._formatters.get(event.title, self._fmt_default)
        for line in formatter(event):
            print(line)

    def _fmt_default(self, e: Event) -> list[str]:
        return [f"  [{e.category.value}/{e.title}] {json.dumps(e.data, ensure_ascii=False)[:120]}"]


# ---------------------------------------------------------------------------
# EventLogger
# ---------------------------------------------------------------------------

class EventLogger:
    """Central event logger with level/category filtering and multi-sink support."""

    def __init__(
        self,
        level: EventLevel = EventLevel.NORMAL,
        categories: set[EventCategory] | None = None,
        sinks: list[Sink] | None = None,
    ):
        self.level = level
        self.categories = categories if categories is not None else set(EventCategory)
        self._sinks = list(sinks or [])

    def add_sink(self, sink: Sink) -> None:
        self._sinks.append(sink)

    def emit(self, event: Event) -> None:
        if event.level.priority > self.level.priority:
            return
        if event.category not in self.categories:
            return
        for sink in self._sinks:
            sink.emit(event)

    # -- convenience emitters ----------------------------------------------

    def loop_ready(self, query: str, target: str, action_count: int) -> None:
        self.emit(
            Event(
                EventCategory.LOOP,
                EventLevel.NORMAL,
                "loop_ready",
                {"query": query, "target": target, "action_count": action_count},
            )
        )

    def turn_started(self, turn: int, max_turns: int) -> None:
        self.emit(
            Event(
                EventCategory.LOOP,
                EventLevel.NORMAL,
                "turn_started",
                {"turn": turn, "max_turns": max_turns},
            )
        )

    def turn_ended(self, turn: int) -> None:
        self.emit(
            Event(
                EventCategory.LOOP,
                EventLevel.NORMAL,
                "turn_ended",
                {"turn": turn},
            )
        )

    def turn_ended_early(self, turn: int, reason: str) -> None:
        self.emit(
            Event(
                EventCategory.LOOP,
                EventLevel.NORMAL,
                "turn_ended_early",
                {"turn": turn, "reason": reason},
            )
        )

    def action_selected(self, name: str, reason: str) -> None:
        self.emit(
            Event(
                EventCategory.ACTION,
                EventLevel.NORMAL,
                "action_selected",
                {"name": name, "reason": reason},
            )
        )

    def action_args(self, args: dict[str, Any], summary_only: bool = False, action_name: str = "") -> None:
        data: dict[str, Any] = {"args": args, "summary_only": summary_only, "action_name": action_name}
        if summary_only:
            data["keys"] = list(args.keys())
        self.emit(
            Event(
                EventCategory.ACTION,
                EventLevel.NORMAL,
                "action_args",
                data,
            )
        )

    def action_result(self, result: dict[str, Any], success: bool = True, verbose: bool = False, action_name: str = "") -> None:
        data: dict[str, Any] = {"result": result, "success": success, "verbose": verbose, "action_name": action_name}
        if not verbose:
            summary = ""
            if action_name and "stdout" in result:
                stdout = str(result.get("stdout", "")).strip()
                if stdout:
                    summary = stdout
            if not summary and action_name and "workspace_changes" in result:
                summary = json.dumps(result["workspace_changes"], ensure_ascii=False)
            # Try common business keys first (post-refactor unified schema)
            if not summary:
                for key in ("answer", "question", "message", "value", "output", "status", "average_weight"):
                    if key in result:
                        val = result[key]
                        summary = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
                        break
                else:
                    if result:
                        first = next(iter(result.values()))
                        summary = first if isinstance(first, str) else json.dumps(first, ensure_ascii=False)
            data["summary"] = summary
        self.emit(
            Event(
                EventCategory.ACTION,
                EventLevel.NORMAL,
                "action_result",
                data,
            )
        )

    def state_updated(self, todo: str, milestone: str) -> None:
        self.emit(
            Event(
                EventCategory.STATE,
                EventLevel.NORMAL,
                "state_updated",
                {"todo": todo, "milestone": milestone},
            )
        )

    def todo_added(self, key: str, desc: str) -> None:
        self.emit(
            Event(
                EventCategory.STATE,
                EventLevel.NORMAL,
                "todo_added",
                {"key": key, "desc": desc, "verbose": self.level.priority >= EventLevel.VERBOSE.priority},
            )
        )

    def todo_completed(self, key: str, desc: str) -> None:
        self.emit(
            Event(
                EventCategory.STATE,
                EventLevel.NORMAL,
                "todo_completed",
                {"key": key, "desc": desc, "verbose": self.level.priority >= EventLevel.VERBOSE.priority},
            )
        )

    def todo_cancelled(self, key: str, desc: str) -> None:
        self.emit(
            Event(
                EventCategory.STATE,
                EventLevel.NORMAL,
                "todo_cancelled",
                {"key": key, "desc": desc, "verbose": self.level.priority >= EventLevel.VERBOSE.priority},
            )
        )

    def milestone_added(self, text: str) -> None:
        self.emit(
            Event(
                EventCategory.STATE,
                EventLevel.NORMAL,
                "milestone_added",
                {"text": text},
            )
        )

    def step_failed(self, turn: int, step: str, error: str, disposition: str) -> None:
        self.emit(
            Event(
                EventCategory.ERROR,
                EventLevel.NORMAL,
                "step_failed",
                {"turn": turn, "step": step, "error": error, "disposition": disposition},
            )
        )

    def step_failed_detail(self, turn: int, step: str, error_type: str, message: str, raw_traceback: str) -> None:
        self.emit(
            Event(
                EventCategory.ERROR,
                EventLevel.VERBOSE,
                "step_failed_detail",
                {"turn": turn, "step": step, "error_type": error_type, "message": message, "raw_traceback": raw_traceback},
            )
        )

    def step_recovered(self, step: str, model_info: str = "") -> None:
        self.emit(
            Event(
                EventCategory.LLM,
                EventLevel.VERBOSE,
                "step_recovered",
                {"step": step, "model_info": model_info},
            )
        )

    def loop_complete(self, turns: int, todo_summary: str = "?", milestones: int = 0) -> None:
        self.emit(
            Event(
                EventCategory.LOOP,
                EventLevel.NORMAL,
                "loop_complete",
                {
                    "turns": turns,
                    "todo_summary": todo_summary,
                    "milestones": milestones,
                },
            )
        )

    def loop_interrupted(self) -> None:
        self.emit(
            Event(
                EventCategory.LOOP,
                EventLevel.NORMAL,
                "loop_interrupted",
                {},
            )
        )

    def debug_state(self, state_json: str, step: str) -> None:
        self.emit(
            Event(
                EventCategory.STATE,
                EventLevel.DEBUG,
                "debug_state",
                {"state_json": state_json, "step": step},
            )
        )

    def debug_action_meta(self, meta_list: list[dict[str, Any]]) -> None:
        self.emit(
            Event(
                EventCategory.ACTION,
                EventLevel.DEBUG,
                "debug_action_meta",
                {"meta_list": meta_list},
            )
        )

    def debug_action_detail(self, detail: dict[str, Any]) -> None:
        self.emit(
            Event(
                EventCategory.ACTION,
                EventLevel.DEBUG,
                "debug_action_detail",
                {"detail": detail},
            )
        )

    def debug_prompt(self, system: list[dict[str, str]] | None, user: str, source: str = "loop_step") -> None:
        self.emit(
            Event(
                EventCategory.PROMPT,
                EventLevel.DEBUG,
                "debug_prompt",
                {"system": system or [], "user": user, "source": source},
            )
        )

    def workspace_scanned(self, location: str, resource_count: int, resource_names: list[str]) -> None:
        self.emit(
            Event(
                EventCategory.STATE,
                EventLevel.VERBOSE,
                "workspace_scanned",
                {
                    "location": location,
                    "resource_count": resource_count,
                    "resource_names": resource_names,
                },
            )
        )

    def llm_ready(self, model: str, provider: str = "", profile: str = "") -> None:
        self.emit(
            Event(
                EventCategory.LLM,
                EventLevel.NORMAL,
                "llm_ready",
                {"model": model, "provider": provider, "profile": profile},
            )
        )

    def llm_retry(
        self,
        step: str,
        model: str,
        attempt: int,
        max_attempts: int,
        provider: str = "",
        profile: str = "",
    ) -> None:
        self.emit(
            Event(
                EventCategory.LLM,
                EventLevel.VERBOSE,
                "llm_retry",
                {
                    "step": step,
                    "model": model,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "provider": provider,
                    "profile": profile,
                },
            )
        )

    def llm_failover(
        self,
        from_model: str,
        to_model: str,
        from_provider: str = "",
        to_provider: str = "",
        profile: str = "",
    ) -> None:
        self.emit(
            Event(
                EventCategory.LLM,
                EventLevel.NORMAL,
                "llm_failover",
                {
                    "from_model": from_model,
                    "to_model": to_model,
                    "from_provider": from_provider,
                    "to_provider": to_provider,
                    "profile": profile,
                },
            )
        )

    def warn(self, title: str, message: str, **data: Any) -> None:
        self.emit(
            Event(
                EventCategory.WARN,
                EventLevel.NORMAL,
                "warn",
                {"title": title, "message": message, **data},
            )
        )

    def error(self, title: str, message: str, **data: Any) -> None:
        self.emit(
            Event(
                EventCategory.ERROR,
                EventLevel.NORMAL,
                "error",
                {"title": title, "message": message, **data},
            )
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def default_logger() -> EventLogger:
    """Create a logger from global settings."""
    level = EventLevel(settings.log_level.lower())

    cat_str = settings.log_categories.lower()
    if cat_str == "all":
        categories = set(EventCategory)
    else:
        categories = {EventCategory(c.strip()) for c in cat_str.split(",")}

    use_color = settings.log_color.lower() in ("1", "true", "yes")
    return EventLogger(
        level=level,
        categories=categories,
        sinks=[ConsoleSink(use_color=use_color)],
    )
