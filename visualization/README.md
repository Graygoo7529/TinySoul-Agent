# TinySoul Desktop Frontend

A Tauri 2 + React + TypeScript + Vite desktop interface for TinySoul. It connects to the local Endpoint backend, presents agent interactions as a conversation with full runtime transparency, and provides a workspace file manager that never touches the local filesystem directly.

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

Build the production bundle:

```bash
pnpm tauri build
```

Checks:

```bash
pnpm test    # vitest
pnpm build   # tsc + vite build
```

## Architecture

- `src-tauri/src/lib.rs` — Tauri Rust boundary that locates and validates the App-owned project connection record.
- `src/api/` — Endpoint HTTP client and WebSocket event stream (exponential-backoff reconnect, gap detection).
- `src/derive/` — Derives the conversation model from the flat event stream: turns → cycles → phases, Phase1 control operations, working-state projection, activity feed, token usage, and turn trace export.
- `src/store/appStore.ts` — Zustand store for connection, events, workspace cache, UI state (theme, drawer, toasts); persists project root / theme / tab only.
- `src/components/ui/` + `src/components/markdown/` — design-system primitives and the shared Markdown renderer.
- `src/components/chat/ | trace/ | workspace/ | monitor/ | shell/` — feature surfaces.

## Features

### Chat

- Conversation of user turns: user bubbles on the right, agent rows on the left.
- Final answers rendered as Markdown (GFM).
- **Live status disclosure** while a turn runs: current phase and model/action activity, a 3-stage phase stepper, the todo/milestone working snapshot, and a rolling semantic activity feed (context loading, domain selection, action execution, workspace changes…).

### Turn Trace Drawer

- Every turn opens a right-side detail drawer (live while running): overview stats, final working context, the full activity list, and per-cycle phase cards.
- Phase1 shows semantic control operations — selected action domains, todo/milestone maintenance, background load/evict.
- Phase2 shows planned actions with generated parameters; Phase3 shows executed actions with status, typed failures, and domain-aware output rendering (documents, terminal stdout/stderr with exit codes, web results), plus raw JSON fallbacks.
- Every LLM call expands to its full constructed **message stack**, grouped into semantic sections (identity / user inputs / background / turn trace / working / task prompt) with per-message roles, labels, parts, tool calls and reasoning.
- **Trace export**: pick a directory and the app writes a folder per turn — `turn.json` + `trace.md` at the root and one `cycle-N/phaseM-llm-K-<profile>.json` per LLM call (full request message stack + response). In browser dev mode it falls back to a single JSON download.

### Monitor

- Raw observation event stream with level filtering (normal/verbose/model), text search, scope frames and expandable payloads.

### Workspace

- Directory tree derived from the manifest, search filter, trash list with restore.
- Text editor with live Markdown preview (source / split / preview), digest+revision CAS, and explicit conflict resolution (keep draft, Overwrite / Reload).
- Binary resources preview (images render) and download.

### Global

- Background Context panel: the currently loaded top-level links with rendered content.
- Maintenance dialog: daily / home / memory requests with availability hints.
- Light/dark themes, toast notifications, connection status bar with day/revision/turn state.

## Notes

- The frontend only communicates through the authenticated loopback Endpoint. It does not read `runtime/`, Session, Home, or Memory directly.
- The backend is owned by the visible Terminal that ran `tinysoul start`; closing the frontend only disconnects it.
- Design documents are in `docs/design/`; completed plans and active execution plans are in `docs/plans/`.
