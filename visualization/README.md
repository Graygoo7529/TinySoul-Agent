# TinySoul Desktop Frontend

A polished Tauri 2 + React + TypeScript + Vite desktop interface for TinySoul. It connects to the local Endpoint backend, presents agent interactions as a conversation, and provides a workspace file manager that never touches the local filesystem directly.

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

The frontend window will open first; confirm the project root and click **Start Backend** to spawn `tinysoul serve`.

> The backend executable must be on PATH as `tinysoul` (or `tinysoul.exe` on Windows). For this project you can install it with `pip install -e .` from the repository root.

Build the production bundle:

```bash
pnpm tauri build
```

## Architecture

- `src-tauri/src/lib.rs` — Tauri Rust shell. Spawns `tinysoul serve`, captures the `endpoint.ready` handshake, and exposes `start_backend` / `stop_backend` commands.
- `src/api/tinysoul.ts` — HTTP client for the Endpoint API.
- `src/api/events.ts` — WebSocket event stream manager with reconnection and gap detection.
- `src/store/appStore.ts` — Zustand store for connection state, events, workspace cache, and UI selections.
- `src/hooks/useDerivedChat.ts` — Derives conversation turns, cycles, phases, actions, and model tasks from the raw event stream.
- `src/components/` — React UI components.

## Design

The UI follows a "conversation first, progressive disclosure" pattern:

- Chat is a single message history between the user and the agent.
- Each assistant message can expand to reveal its internal execution.
- Cycles, phases, action calls/results, and full model message stacks are nested behind clickable sections.
- The event stream always runs at `model` level; the frontend decides how much to surface.

## Features

### Chat

- Conversation-style history with user and assistant bubbles.
- Expandable "Show thinking" section per assistant message with tabs for:
  - **Cycles** — Phase 1/2/3 stepper and action details.
  - **Model calls** — Full LLM task message stack, tools, and provider responses.
  - **Context** — Loaded top links and workspace events for the turn.

### Workspace

- Manifest summary (file count, size, kind breakdown).
- Browse resources, read text, edit in place, and save with digest CAS.
- Create new resources.
- Move resources to trash and restore them.

### Session

- List today’s turns with status and summary.
- Recall canonical turn traces.

## Notes

- The frontend only communicates through the authenticated loopback Endpoint. It does not read `runtime/workspace`, Session, Home, or Memory directly.
- The backend executable name is `tinysoul` (or `tinysoul.exe` on Windows). For production distribution it should be bundled as a Tauri sidecar.
- Assumed or missing backend capabilities that could extend the UI are recorded in `docs/missing-capabilities.md` and `docs/design-v2.md`.
