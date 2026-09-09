# TinySoul Project

This is an editable TinySoul project created from a packaged config profile. Its configuration, Home, Memory, runtime state, and archives are project-owned.

## Standard

The standard profile starts with every LLM provider disabled, so the backend and frontend can run before credentials are configured:

```powershell
tinysoul start --root . --mode normal
```

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

`reset` preserves `.env` and replaces everything else, including runtime data, conversations, Memory, archives, and `.git`.

### Frontend

Keep the backend running. In another terminal, open the TinySoul source checkout and run:

```powershell
cd visualization
pnpm install
pnpm tauri dev
```

The frontend requires Node.js 20+, pnpm, and Rust 1.97+. It discovers the running project automatically and does not manage the backend process.
