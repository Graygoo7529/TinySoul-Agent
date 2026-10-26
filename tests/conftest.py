"""One pytest entry contract for scripts/test.py, PowerShell and direct pytest."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from time import perf_counter
from uuid import uuid4

import pytest


_SUITES = {
    "fast": "not integration and not packaging and not external",
    "integration": "integration and not external",
    "packaging": "packaging and not external",
    "full": "not external",
    "external": "external",
}
_RUN = pytest.StashKey["TestRun"]()


class TestRun:
    """Own one run's environment, reports and disposable resources."""

    def __init__(self, config: pytest.Config) -> None:
        self.started = perf_counter()
        self.suite: str = config.getoption("suite")
        repository = Path(__file__).resolve().parents[1]
        artifact_root = Path(config.getoption("artifact_root"))
        if not artifact_root.is_absolute():
            artifact_root = repository / artifact_root
        self.artifact_root = artifact_root.resolve()
        self.id = uuid4().hex
        self.root = self.artifact_root / "runs" / self.id
        self.report_root = self.artifact_root / "reports" / self.id
        self.report_root.mkdir(parents=True)
        self.keep = config.getoption("keep_artifacts")
        self.success = False
        self.reports: list[pytest.TestReport] = []
        self.collection_failures: list[pytest.CollectReport] = []
        self.environment = {
            "PYTEST_TINYSOUL_RUN_ROOT": str(self.root),
            "TINYSOUL_INSTANCE_DIR": str(self.root / "instances"),
            "LOCALAPPDATA": str(self.root / "local-app-data"),
            **{name: str(self.root / "temp") for name in ("TEMP", "TMP", "TMPDIR")},
        }
        inherited_config = (
            {name for name in os.environ if name.upper().startswith("TINYSOUL_")}
            if self.suite != "external"
            else set()
        )
        self.previous = {
            name: os.environ.get(name)
            for name in self.environment.keys() | inherited_config
        }
        self.previous_tempdir = tempfile.tempdir
        for path in set(self.environment.values()):
            Path(path).mkdir(parents=True, exist_ok=True)
        for name in inherited_config:
            os.environ.pop(name)
        os.environ.update(self.environment)
        tempfile.tempdir = self.environment["TEMP"]
        if config.option.basetemp is None:
            config.option.basetemp = str(self.root / "pytest")
        config.inicfg["cache_dir"] = str(self.root / "pytest-cache")
        if config.option.xmlpath is None:
            config.option.xmlpath = str(self.report_root / "results.xml")

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.reports.append(report)

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            self.collection_failures.append(report)

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        self.success = exitstatus == 0
        durations: dict[str, float] = {}
        for report in self.reports:
            durations[report.nodeid] = durations.get(report.nodeid, 0) + report.duration
        summary = {
            "suite": self.suite,
            "python": sys.executable,
            "python_version": sys.version.split()[0],
            "exit_code": int(exitstatus),
            "seconds": round(perf_counter() - self.started, 3),
            "collected": session.testscollected,
            "passed": sum(r.when == "call" and r.passed for r in self.reports),
            "failed": sum(r.failed for r in self.reports),
            "collection_errors": len(self.collection_failures),
            "skipped": sum(r.skipped for r in self.reports),
            "run_root": str(self.root),
            "report_root": str(self.report_root),
            "durations": dict(sorted(durations.items(), key=lambda item: -item[1])),
        }
        encoded = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
        (self.report_root / "summary.json").write_text(encoded, encoding="utf-8")
        latest = self.artifact_root / "reports" / f"latest-{self.suite}.json"
        temporary = latest.with_suffix(f".{self.id}.tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(latest)
        failures = [
            f"{r.nodeid} [{r.when}]\n{r.longrepr}" for r in self.reports if r.failed
        ]
        failures.extend(
            f"{r.nodeid} [collection]\n{r.longrepr}" for r in self.collection_failures
        )
        if failures:
            (self.report_root / "failures.txt").write_text(
                "\n\n".join(failures) + "\n", encoding="utf-8"
            )

    def pytest_terminal_summary(self, terminalreporter: object) -> None:
        from _pytest.terminal import TerminalReporter

        assert isinstance(terminalreporter, TerminalReporter)
        terminalreporter.write_line(f"TinySoul reports: {self.report_root}")
        if not self.reports and not self.collection_failures:
            terminalreporter.write_line(
                "No tests executed. Check --suite and path/-k/-m filters; use --suite full for all local tests."
            )
        if not self.success or self.keep:
            terminalreporter.write_line(f"TinySoul artifacts retained: {self.root}")

    def close(self) -> None:
        for name, value in self.previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        tempfile.tempdir = self.previous_tempdir
        if self.success and not self.keep:
            shutil.rmtree(self.root)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("tinysoul")
    group.addoption("--suite", type=str.lower, choices=tuple(_SUITES), default="fast")
    group.addoption("--artifact-root", default=".local-test")
    group.addoption("--keep-artifacts", action="store_true")


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    # Real-provider modules may parameterize from credentials during collection.
    # Local suites must remain independent of those opt-in environment switches.
    if (
        collection_path.name.startswith("test_real_")
        and config.getoption("suite") != "external"
    ):
        return True
    return None


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    suite = _SUITES[config.getoption("suite")]
    config.option.markexpr = (
        f"({suite}) and ({config.option.markexpr})" if config.option.markexpr else suite
    )
    run = TestRun(config)
    config.stash[_RUN] = run
    config.pluginmanager.register(run, "tinysoul-run")


def pytest_sessionstart(session: pytest.Session) -> None:
    from _pytest.terminal import TerminalReporter

    reporter = session.config.pluginmanager.getplugin("terminalreporter")
    if isinstance(reporter, TerminalReporter):
        run = session.config.stash[_RUN]
        reporter.write_line(f"TinySoul suite: {run.suite} | Python: {sys.executable}")
        reporter.write_line(f"TinySoul run: {run.root}")


def pytest_unconfigure(config: pytest.Config) -> None:
    run = config.stash.get(_RUN, None)
    if run is not None:
        run.close()


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """TinySoul's root scheduler is asyncio on every supported host."""
    return "asyncio"
