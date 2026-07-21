# TinySoul

TinySoul is a local, provider-neutral LLM agent runtime built around explicit Context, Action, Session, Workspace, Agent Home, Memory, and daily lifecycle boundaries.

## Install And Initialize

TinySoul requires Python 3.13 or newer.

```powershell
python -m pip install .
tinysoul init my-agent
cd my-agent
```

`tinysoul init` copies editable configuration and Home templates into a new or empty directory. It does not select a provider and never overwrites a non-empty directory. Enable at least one provider in `configs/llm.providers.toml`, put its key in `.env`, and run:

```powershell
tinysoul start --root . --mode normal
```

The default `standard` config profile keeps every provider disabled and host-sensitive optional capabilities off. Repository maintainers can initialize the packaged development configuration explicitly:

```powershell
tinysoul init my-agent-dev --config-profile development
```

The development profile contains enabled provider/capability settings but no credentials and does not install optional distributions or host executables. After initialization, the selected configuration and the shared Home copy are owned entirely by that project.

The source checkout is not itself an initialized TinySoul project. Keep runtime development and real-provider smoke tests in an external directory created by `tinysoul init`, and pass that directory through `--root` or `TINYSOUL_REAL_PROJECT_ROOT` as appropriate.

For one non-interactive turn:

```powershell
tinysoul start --root . --once "Summarize today's work"
```

The Action Catalog is versioned package data and is not copied into projects. Project configuration, Agent Home, Memory, runtime state, and archives remain project-owned.

## Development

```powershell
python -m pip install -e ".[dev]"
python -m pytest tests -q
$env:TINYSOUL_PYTHON=(Get-Command python).Source
.\scripts\typecheck.ps1
```

Architecture and module contracts are documented under `docs/design/`; the active lifecycle execution plan is under `docs/analysis/`.
