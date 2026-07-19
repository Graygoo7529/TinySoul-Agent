# TinySoul Desktop Frontend

A Tauri 2 + React + TypeScript + Vite desktop interface for TinySoul. It connects to the local Endpoint backend, visualizes agent execution in three observation modes, and provides a workspace file manager that never touches the local filesystem directly.

## Development

Requirements:

- Node.js 20+
- pnpm
- Rust 1.77+ (for Tauri)
- `tinysoul` on PATH (the backend sidecar)

Install dependencies:

```bash
pnpm install
```

Run in development mode:

```bash
pnpm tauri dev
```

The frontend window will open first; enter or confirm the project root and click **Start Backend** to spawn `tinysoul serve`.

> The backend executable must be on PATH as `tinysoul` (or `tinysoul.exe` on Windows). For this project you can install it with `pip install -e .` from the repository root.

Build the production bundle:

```bash
pnpm tauri build
```

## Architecture

- `src-tauri/src/lib.rs` — Tauri Rust shell. Spawns `tinysoul serve` as a child process, captures the `endpoint.ready` handshake, and exposes `start_backend` / `stop_backend` commands.
- `src/api/tinysoul.ts` — HTTP client for the Endpoint API.
- `src/api/events.ts` — WebSocket event stream manager with reconnection and gap detection.
- `src/store/appStore.ts` — Zustand store for connection state, events, workspace cache, and UI selections.
- `src/components/` — React UI components.

## Features

### Chat

- **Normal mode**: user inputs, assistant outputs, workspace changes, program work, and turn terminal events.
- **Verbose mode**: adds cycle/phase cards, LLM task lifecycle, action calls, action results, and background context snapshots.
- **Model mode**: streams `llm.model.request` / `llm.model.response` events and renders the full message stack, tools, and usage for each task.
- **Top Links panel**: shows the currently loaded top-level background entries from `context.background.snapshot` / `changed` events.

### Workspace

- Reconciles the workspace manifest via `GET /v1/workspace/manifest`.
- Browse resources, read text, edit in place, and save with digest CAS.
- Create new resources.
- Move resources to trash (`POST /v1/workspace/trash`).

### Session

- Lists today’s turn history.
- Recalls canonical turn traces.

## Notes

- The frontend only communicates through the authenticated loopback Endpoint. It does not read `runtime/workspace`, Session, Home, or Memory directly.
- The backend executable name is `tinysoul` (or `tinysoul.exe` on Windows). For production distribution it should be bundled as a Tauri sidecar.
- Assumed or missing backend capabilities that could extend the UI are recorded in `docs/missing-capabilities.md`.
