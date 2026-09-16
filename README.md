# TinySoul

TinySoul is a local, provider-neutral LLM agent runtime built around explicit Context, Action, Session, Workspace, Agent Home, Memory, and daily lifecycle boundaries.

Python 3.13 or newer is required.

## Standard

Install TinySoul and create a backend project:

```powershell
python -m pip install .
tinysoul init my-agent
```

The standard profile starts with every LLM provider disabled, so the backend and frontend can run before credentials are configured:

```powershell
tinysoul start --root my-agent --mode normal
```

Use the frontend settings to add a credential and enable its provider, or edit `my-agent/.env` and `my-agent/configs/llm/providers.toml`. Enabling a provider without any non-empty declared credential is invalid and startup or configuration activation will fail with a configuration error.

For one non-interactive turn:

```powershell
tinysoul start --root my-agent --once "Summarize today's work"
```

## SDK

The same project can be embedded through the asynchronous SDK:

```python
import asyncio
from tinysoul.agent import Agent, UserTurnRequest

async def main():
    agent = await Agent.create("my-agent")
    try:
        await agent.start()
        handle = await agent.submit_turn(UserTurnRequest("Summarize today's work"))
        result = await handle.wait()
        print(result.state)
    finally:
        await agent.shutdown()

asyncio.run(main())
```

SDK creation does not open a terminal or HTTP listener. Question replies, Cycle grants, cancellation and observations use the same Turn identity; see [Agent design](docs/design/agent.md). Configuration PATCH saves a candidate; call reload explicitly to activate it when idle.

## Development

The development profile enables the repository maintainer's providers and capability settings, including Kimi search, but contains no credentials. Its enabled providers must have their declared credentials before the backend starts.

### Backend

Install TinySoul and create a development project:

```powershell
python -m pip install -e ".[dev]"
tinysoul init my-agent-dev --config-profile development
```

Add the required credentials to `my-agent-dev/.env`, then start the backend:

```powershell
tinysoul start --root my-agent-dev --mode normal
```

To rebuild the development project from the packaged Home and configuration templates:

```powershell
tinysoul reset my-agent-dev
```

Run `reset` from outside the target directory. It preserves `.env` and replaces everything else, including runtime data, conversations, Memory, archives, and `.git`.

### Frontend

Keep the backend running, then start the desktop frontend in another terminal. The frontend requires Node.js 20+, pnpm, and Rust 1.97+.

```powershell
cd visualization
pnpm install
pnpm tauri dev
```

The frontend discovers the running TinySoul project automatically and does not manage the backend process.

### Checks

```powershell
.\scripts\test.ps1
.\scripts\test.ps1 -TestPath tests/kernel/action/test_backends_engine.py
.\scripts\test.ps1 -Suite Full
.\scripts\test.ps1 -Suite Generation
$env:TINYSOUL_PYTHON=(Get-Command python).Source
.\scripts\typecheck.ps1
```

`test.ps1` runs the Fast local business-logic suite by default and creates a unique isolated run root under `.local-test/runs/`. Use `-TestPath` for focused feedback, `-Suite Generation` for the small set of package-owned project/resource generation contracts, and `-Suite Full` for the completion gate, which includes both local suites plus wheel build and isolated-install checks. Real-provider and opt-in network tests are excluded from Fast and Full and can only be selected with `-Suite External` plus their existing environment switches. If PowerShell blocks local script execution, invoke the same script with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1`. `typecheck.ps1` runs `ty` with the selected Python environment.

Architecture and module contracts are under `docs/design/`; the desktop frontend is documented in `visualization/README.md`.


## Provider popularization

https://www.orcarouter.ai/ is now supported as built-in provider.

orcarouter new user link：
https://www.orcarouter.ai/ref/ref_5fac47f4440f623d372b
