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
        print(result.status)
    finally:
        await agent.shutdown()

asyncio.run(main())
```

SDK creation does not open a terminal or HTTP listener. Question replies, Cycle grants, cancellation and observations use the same Turn identity; see [Agent design](docs/design/agent.md). Configuration PATCH saves a candidate; call reload explicitly to activate it when idle.

Session presents a topic map with source references and chronological interaction text. The Agent can organize earlier conversation through `core.session.organize` during a User Turn; SDK Session access remains read-only. Facts stay immutable, annotations share their day archive, and a new day starts with an empty map. See [Session design](docs/design/session.md).

The architecture refactor is complete within its agreed scope. See the [main plan](docs/analysis/done/20260915-done-agent-architecture-refactor-plan.md) and [R7 implementation and acceptance record](docs/analysis/done/20260921-done-Agent重构第七轮子计划-会话整理与架构收口.md#13-实施结果与最终核对).

R7 keeps the R6 Turn/manifest format and adds optional `runtime/session/map.json`; a missing map means no annotations. Existing projects must explicitly add the new `core/actions/session_organize.toml` catalog document from an initialized project's `configs/action/catalog` before using this version. Do not use `reset` to update a project with data.

Use `agent.services.get(WorkspaceService)` to obtain a scoped owner service and await its I/O methods. Reacquire services after reload/restart or a CalendarDay switch; writes are not retried automatically. A `ReflectionRequest` authorizes one independent Home or dated Memory Reflection Turn on the same Agent.

Projects use `configs/agent.toml`, `configs/reflection.toml`, and `configs/execution.toml`. Domain/action TOML files live under `configs/action/catalog`; scenario visibility is editable, while service permissions are enforced by assembly. The R3 changes also update Workspace and Session formats and the [Endpoint protocol](docs/endpoint/index.md). Existing projects require explicit migration into a separately initialized project; `reset` is not a data migration tool. See the [R3 implementation record](docs/analysis/done/20260917-done-Agent重构第三轮子计划-领域语义与能力组织.md#133-格式变化与部署边界).

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
.\scripts\test.ps1 -TestPath tests/kernel/action/execution
.\scripts\test.ps1 -Suite Full
.\scripts\test.ps1 -Suite Generation
$env:TINYSOUL_PYTHON=(Get-Command python).Source
.\scripts\typecheck.ps1
```

`test.ps1` runs the Fast local business-logic suite by default and creates a unique isolated run root under `.local-test/runs/`. Use `-TestPath` for focused feedback, `-Suite Generation` for the small set of package-owned project/resource generation contracts, and `-Suite Full` for the completion gate, which includes both local suites plus wheel build and isolated-install checks. Real-provider and opt-in network tests are excluded from Fast and Full and can only be selected with `-Suite External` plus their existing environment switches. If PowerShell blocks local script execution, invoke the same script with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1`. `typecheck.ps1` runs `ty` with the selected Python environment.

If repository-local file operations are disrupted by the host environment, use `-ArtifactRoot <scratch-directory>` to place isolated runs elsewhere. Relative paths resolve against the repository. The script creates and cleans only its own `runs/<uuid>` directory; failed runs retain their artifacts. The selected suite and its assertions remain the same.

Real model API checks load models and credentials from an initialized project's TOML and `.env`:

```powershell
$env:TINYSOUL_RUN_REAL_LLM_API = "1"
$env:TINYSOUL_REAL_PROJECT_ROOT = "C:\TinySoul\my-project"
$env:TINYSOUL_REAL_MODELS = "claude-opus,claude-sonnet,claude-fable"
$env:TINYSOUL_REAL_PROVIDER = "token-advant"
.\scripts\test.ps1 -Suite External -TestPath tests/llm/adapter/test_real_provider_api.py
```

`TINYSOUL_REAL_MODELS` is optional; omitting it selects all models in that project. `TINYSOUL_REAL_PROVIDER` is also optional: by default each model uses its first enabled binding with credentials. An explicit provider selects only its existing bindings and enables it within the test process, without editing TOML. Remove that environment variable to return to normal binding selection. Missing bindings/credentials and undeclared capabilities are reported as skipped; request failures remain failures and do not trigger provider switching. To see safe route and usage summaries for passing tests, set `PYTEST_ADDOPTS="-s -ra --tb=short"` for the invocation.

The checks validate JSON values, image content, tool arguments and returned results, non-empty native reasoning actually sent in a continuation, and cache hits from repeated long prefixes. Anthropic explicit/automatic caching also checks creation counts. Missing cache-read telemetry is reported as unverified, not a successful hit; these checks do not establish cache expiry or Google cache-resource lifecycle behavior. The optional `token-advant` provider uses `TOKEN_ADVANT_API_KEY` and binds Claude Opus, Sonnet and Fable; Haiku is not bound to that provider. Existing projects need these provider/model TOML entries before selecting it.

Architecture and module contracts are under `docs/design/`; the desktop frontend is documented in `visualization/README.md`.

LLM providers declare API-mode endpoints with shared credentials; models choose one generic or specialized adapter and use stable IDs. OpenAI Chat/Responses, Anthropic Messages and Google GenerateContent have executable SDK adapters; remote model availability depends on the configured binding and credentials. See [LLM configuration and adapters](docs/design/llm.md#api-模式与-adapter).
