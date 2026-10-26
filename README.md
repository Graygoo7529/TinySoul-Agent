# TinySoul

TinySoul is a personal agent backend with explicit Context, Actions, Session, Home, Memory, Workspace and daily lifecycle boundaries. Use it through the desktop frontend, terminal or Python SDK.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), clone this repository and run the commands below from its root. Conda is not required. uv uses `.python-version` to select Python 3.13 and creates the project's isolated `.venv`.

```sh
uv python install
```

`uv.lock` is committed so each machine installs the same resolved dependencies for its platform. The commands below use `--locked`: changes to dependency declarations require an explicit `uv lock` before installation. No environment activation is needed.

## Standard installation

Install the base runtime as a non-editable package and initialize a separate Agent data directory:

```sh
uv sync --locked --no-editable
uv run --locked --no-editable tinysoul init ../my-agent
uv run --locked --no-editable tinysoul start --root ../my-agent --mode normal
```

The standard profile starts with LLM providers disabled. Configure credentials and enable providers in the frontend settings, or edit `../my-agent/.env` and its `configs/llm/providers.toml`. Every enabled provider needs its declared credentials.

For one non-interactive turn, replace `--mode normal` with `--once "Summarize today's work"`. Optional capabilities use the `external-tools` and `web-crawl` extras; add the required `--extra` flags to both sync and run commands.

## Source development

Install the development extra, including tests, type checking and optional Python capabilities:

```sh
uv sync --locked --extra dev
uv run --locked --extra dev tinysoul init ../my-agent-dev --config-profile development
```

The development profile enables maintainer provider/capability settings and a local proxy. Adjust its configuration for your machine and fill in the required credentials in `../my-agent-dev/.env`, then start:

```sh
uv run --locked --extra dev tinysoul start --root ../my-agent-dev --mode normal
```

Installation and initialization profiles are independent: the same development environment can use `tinysoul init ../my-agent` to start with standard configuration. The `dev` extra is an optional dependency set, not a uv dependency group.

uv installs the checkout in editable mode by default. Python source edits are available to the next process without reinstalling; restart a running backend to load them. This also supports running a source checkout on a separate host. For the non-editable standard installation, rebuild after source changes with `uv sync --locked --no-editable --reinstall-package tinysoul`.

After changing dependencies, run `uv lock`, review and commit the lockfile, then sync the chosen environment. Use `uv lock --upgrade-package <package>` for an intentional dependency upgrade. Do not commit `.venv` or copy it between machines; recreate it with uv.

### Checks

```sh
uv run --locked --extra dev python scripts/test.py                         # fast
uv run --locked --extra dev python scripts/test.py --suite full            # all local tests
uv run --locked --extra dev python scripts/test.py tests/kernel/action     # focused fast
uv run --locked --extra dev python scripts/test.py --suite full tests/agent
uv run --locked --extra dev ty check
```

Fast excludes integration, packaging and external tests. Full includes all local tests and is required with type checking before completing a change. A focused path still follows the selected suite. On Windows, `scripts/test.ps1 -Suite Fast/Full` and `scripts/typecheck.ps1` invoke these same uv commands.

Local tests need no model credentials. Reports and temporary files stay under the ignored `.local-test/` directory. See [test conventions, diagnostics and external checks](tests/README.md).

### Reset a disposable project

```sh
uv run --locked --extra dev tinysoul reset ../my-agent-dev
```

Run this from outside the target directory. **Reset preserves `.env` and replaces everything else**, including conversations, Memory, runtime data, archives and `.git`. Updating source code does not replace an initialized project's configuration or Home; reset is not a data migration command.

## Desktop frontend

The frontend uses Node.js 20+, pnpm and Rust 1.97+. Start the backend separately, then:

```sh
cd visualization
pnpm install
pnpm tauri dev
```

The frontend connects to a backend and does not own its process. See [frontend setup and connection details](visualization/README.md).

## SDK and design

The Python SDK uses `Agent.create(...)`, `Agent.start()`, `Agent.submit_turn(UserTurnRequest(...))` and `Agent.shutdown()`. SDK creation does not open a terminal or HTTP listener. See [Agent design](docs/design/agent.md) for lifecycle and service ownership.

- [Architecture and module contracts](docs/design/)
- [LLM configuration and adapters](docs/design/llm.md)
- [Endpoint protocol](docs/endpoint/index.md)
- [Contribution rules](AGENTS.md)
