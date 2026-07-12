from __future__ import annotations

from pathlib import Path

from tinysoul.app import AppSettings, OutputSettings
from tinysoul.app import cli
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


class _FakeApp:
    def __init__(self) -> None:
        self.once_inputs: list[str] = []

    def run_once(self, user_input: str) -> None:
        self.once_inputs.append(user_input)


class _FakeBuilder:
    def __init__(self, root: Path, app: _FakeApp) -> None:
        self.root = root
        self.app = app
        self.sink_max_chars = 0

    def with_config_environment(self, config):
        return self

    def with_app_settings(self, settings: AppSettings):
        return self

    def with_output_sink(self, sink):
        self.sink_max_chars = sink.max_chars
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

    result = cli.main(
        [
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
