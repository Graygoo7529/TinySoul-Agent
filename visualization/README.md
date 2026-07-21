# TinySoul Desktop Frontend

A polished Tauri 2 + React + TypeScript + Vite desktop interface for TinySoul. It connects to the local Endpoint backend, presents agent interactions as a conversation, and provides a workspace file manager that never touches the local filesystem directly.

## Development

Requirements:

- Node.js 20+
- pnpm
- Rust 1.97+ (for Tauri)
- `tinysoul` on PATH

Install dependencies:

```bash
pnpm install
```

Run in development mode:

```bash
pnpm tauri dev
```

Start TinySoul in a visible Terminal, then open the frontend:

```bash
tinysoul start --root <project-root> --mode normal
```

The frontend discovers that project instance automatically. When no instance is available it shows the recommended command and a retry action; it never starts or stops the backend.

> The backend executable must be on PATH as `tinysoul` (or `tinysoul.exe` on Windows). For this project you can install it with `pip install -e .` from the repository root.

Build the production bundle:

```bash
pnpm tauri build
```

## Architecture

- `src-tauri/src/lib.rs` — Tauri Rust boundary that locates and validates the App-owned project connection record.
- `src/api/tinysoul.ts` — HTTP client for the Endpoint API.
- `src/api/events.ts` — WebSocket event stream manager with reconnection and gap detection.
- `src/store/appStore.ts` — Zustand store for connection state, events, workspace cache, UI selections, and persisted project root.
- `src/hooks/useDerivedChat.ts` — Derives conversation turns, cycles, phases, actions, and model tasks from the raw event stream following AGENT.md semantics.
- `src/components/` — React UI components.

## Design

The UI follows a "conversation first, progressive disclosure" pattern:

- Chat is a single message history between the user and the agent.
- Each assistant message can expand to reveal its internal execution.
- Execution details follow AGENT.md semantics: **Turn → Cycle → Phase → Action/Result → LLM Context**.
- The event stream always runs at `model` level; the frontend decides how much to surface.

## Features

### Chat

- Conversation-style history with user and assistant bubbles.
- Live activity indicator while a turn is running (current phase and action).
- Expandable execution details per assistant message with tabs for:
  - **Cycles** — Agent cycles with Phase 1/2/3 cards.
  - **Model calls** — Full LLM task message stack grouped by semantic context section, tools, and provider responses.
  - **Turn context** — Loaded top links and workspace events for the turn.
- Robust status normalization so `success`, `completed`, `failed`, `timeout`, and pending states render correctly.

### Action Execution Cards

Phase 3 action results are rendered as mock computer UIs:

- **Document editing** — `workspace.write`, `workspace.rewrite`, `workspace.patch`, and `script.write` show a file preview with line count and save status.
- **Script execution** — `script.run_*` actions render a code-terminal view with language, arguments, stdout, stderr, and exit code.
- **Shell commands** — `shell.run_*` actions render a terminal window with the command, working directory, output, and exit code.
- **Long-running processes** — supervised process results show job state, elapsed time, execution id, stdout/stderr, and candidate changes.
- Each card still exposes the raw action payload and result JSON for advanced debugging.

### Background Context

- A global **Background Context** side panel shows the currently loaded top links independent of any turn.
- Links are updated from `context.background.snapshot` / `context.background.changed` events and are evicted as the backend decides.

### Workspace

- Manifest summary (file count, size, kind breakdown).
- Browse resources, read text, edit in place, and save with digest CAS.
- Create new resources.
- Move resources to trash and restore them.

### Session

- List today’s turns with status and summary.
- Recall canonical turn traces.

### Settings

- Project root directory is persisted across restarts.
- The root can be changed from the Settings dialog and reconnects to that project's running instance.

## Notes

- The frontend only communicates through the authenticated loopback Endpoint. It does not read `runtime/workspace`, Session, Home, or Memory directly.
- The backend is owned by the visible Terminal that ran `tinysoul start`; closing the frontend only disconnects it.
- The default window is intentionally compact (720×520) for a user-level desktop assistant.
- Assumed or missing backend capabilities that could extend the UI are recorded in `docs/missing-capabilities.md` and `docs/design-v2.md`.
