from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tinysoul.app import AppSettings, OutputSettings
from tinysoul.app import cli
from tinysoul.loop import TurnOutcomeStatus
from tinysoul.runtime import ObservationLevel


class _FakeConfig:
    def parse_section(self, section, parser):
        assert section == "app"
        return AppSettings(
            interactive=False,
            output=OutputSettings(
                mode=ObservationLevel.MODEL,
                model_max_chars=321,
            ),
        )


class _FakeGateway:
    active_turn_scope = None

    def request_control(self, kind, *, source, text="", metadata=None):
        return SimpleNamespace(accepted=True)


class _FakeApp:
    def __init__(
        self,
        status: TurnOutcomeStatus = TurnOutcomeStatus.ANSWERED,
    ) -> None:
        self.once_inputs: list[str] = []
        self.status = status
        self.run_count = 0
        self.gateway = _FakeGateway()

    def run_once(self, user_input: str):
        self.once_inputs.append(user_input)
        return SimpleNamespace(status=self.status)

    def run(self):
        self.run_count += 1
        return SimpleNamespace()


class _FakeLease:
    def __init__(self, root: Path) -> None:
        self.identity = SimpleNamespace(
            instance_id="instance_test",
            project_identity="project_test",
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def publish(self, _ready):
        return None


class _FakeBuilder:
    def __init__(self, root: Path, app: _FakeApp) -> None:
        self.root = root
        self.app = app
        self.sink_max_chars = 0
        self.endpoint_settings = None
        self.endpoint_ready = None
        self.input_sources: list[object] = []

    def with_config_environment(self, config):
        return self

    def with_app_settings(self, settings: AppSettings):
        return self

    def with_output_sink(self, sink):
        self.sink_max_chars = sink.max_chars
        return self

    def with_endpoint(self, settings, *, ready=None):
        self.endpoint_settings = settings
        self.endpoint_ready = ready
        return self

    def with_input_source(self, source):
        self.input_sources.append(source)
        return self

    def build(self) -> _FakeApp:
        return self.app


def test_cli_once_uses_config_overrides_and_console_sink(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    app = _FakeApp()
    builder = _FakeBuilder(tmp_path, app)

    def from_project_root(root: Path, *, overrides):
        captured["root"] = root
        captured["overrides"] = overrides
        return _FakeConfig()

    monkeypatch.setattr(cli.ConfigEnvironment, "from_project_root", from_project_root)
    monkeypatch.setattr(cli, "TinySoulAppBuilder", lambda root: builder)
    monkeypatch.setattr(cli, "ProjectInstanceLease", _FakeLease)

    result = cli.main(
        [
            "start",
            "--root",
            str(tmp_path),
            "--mode",
            "model",
            "--once",
            "hello",
        ]
    )

    assert result == 0
    assert captured["root"] == tmp_path.resolve()
    assert captured["overrides"] == {
        "app.interactive": False,
        "app.output.mode": "model",
    }
    assert builder.sink_max_chars == 321
    assert app.once_inputs == ["hello"]


def test_cli_once_returns_nonzero_without_final_answer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _FakeApp(TurnOutcomeStatus.EXHAUSTED)
    builder = _FakeBuilder(tmp_path, app)
    monkeypatch.setattr(
        cli.ConfigEnvironment,
        "from_project_root",
        lambda root, *, overrides: _FakeConfig(),
    )
    monkeypatch.setattr(cli, "TinySoulAppBuilder", lambda root: builder)

    monkeypatch.setattr(cli, "ProjectInstanceLease", _FakeLease)
    assert cli.main(["start", "--root", str(tmp_path), "--once", "hello"]) == 1


def test_cli_start_attaches_terminal_and_model_endpoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    app = _FakeApp()
    builder = _FakeBuilder(tmp_path, app)

    def from_project_root(root: Path, *, overrides):
        captured["overrides"] = overrides
        return _FakeConfig()

    monkeypatch.setattr(cli.ConfigEnvironment, "from_project_root", from_project_root)
    monkeypatch.setattr(cli, "TinySoulAppBuilder", lambda root: builder)
    monkeypatch.setattr(cli, "ProjectInstanceLease", _FakeLease)

    result = cli.main(
        [
            "start",
            "--root",
            str(tmp_path),
            "--mode",
            "verbose",
        ]
    )

    assert result == 0
    assert captured["overrides"] == {
        "app.interactive": True,
        "app.output.mode": "verbose",
    }
    assert builder.endpoint_settings is not None
    assert builder.endpoint_settings.instance_id == "instance_test"
    assert builder.endpoint_settings.project_identity == "project_test"
    assert len(builder.input_sources) == 1
    assert builder.sink_max_chars == 321
    assert app.run_count == 1
