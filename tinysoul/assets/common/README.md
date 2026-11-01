# TinySoul Project

This is an editable TinySoul project created from a packaged config profile. Its configuration, Home, Memory, runtime state, and archives are project-owned.

`presentation/configs/interface.toml` stores shared interface preferences;
`presentation/assets/` holds optional shared presentation files. See
[project presentation](presentation/README.md) for saving, reading, and reset behavior.

`init` also creates `.auth`, the project-local stable bearer token for the
Endpoint. Keep it on the backend host and do not commit it. `.env` is a separate
backend configuration file for provider credentials and optional Endpoint
socket settings:

```dotenv
TINYSOUL_ENDPOINT__BIND_HOST=127.0.0.1
TINYSOUL_ENDPOINT__PORT=1430
```

For a trusted remote host, set `BIND_HOST=0.0.0.0` and connect from the
frontend using the host's reachable IP, port 1430, and the token from `.auth`.

## Standard

The standard profile starts with every LLM provider disabled, so the backend and frontend can run before credentials are configured:

```powershell
tinysoul start --root . --mode normal
```

The frontend uses the same address-plus-token form for local and remote
connections. It remembers the pair on the client; **Log out** clears it and
returns to the login form. `tinysoul start --once "..."` runs one CLI turn and
does not require or open the Endpoint.

Use the frontend settings to add a credential and enable its provider, or edit `.env` and `configs/llm/providers.toml`. Enabling a provider without any non-empty declared credential is invalid and startup or configuration activation will fail with a configuration error.

For one non-interactive turn:

```powershell
tinysoul start --root . --once "Summarize today's work"
```

## Development

The development profile enables the repository maintainer's providers and capability settings, including Kimi search, but contains no credentials. Its enabled providers must have their declared credentials before the backend starts.

### Backend

Add the required credentials to `.env` and install any enabled optional dependencies or host executables, then start the backend:

```powershell
tinysoul start --root . --mode normal
```

To rebuild this disposable development project, stop the backend and run the following command from its parent directory:

```powershell
tinysoul reset my-agent-dev
```

`reset` preserves `.env` and `.auth` and replaces everything else, including
runtime data, conversations, Memory, archives, and `.git`. If either local file
is absent, reset leaves it absent; a normal Endpoint start then fails clearly
when `.auth` is missing.

### Frontend

Keep the backend running. In another terminal, open the TinySoul source checkout and run:

```powershell
cd visualization
pnpm install
pnpm tauri dev
```

The frontend requires Node.js 20+, pnpm, and Rust 1.97+. Enter the running
backend's `IP:Port` and `.auth` token once; it does not discover a project path
or manage the backend process.
