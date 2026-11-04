# TinySoul Desktop Frontend

A Tauri 2 + React + TypeScript + Vite desktop interface for TinySoul. It connects to a running Endpoint backend over the same address-plus-token flow for local and remote use, presents agent interactions as a conversation with full runtime transparency, and provides a workspace file manager that never touches the local filesystem directly.

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

In the frontend, enter `<host>:1430` (or an explicit HTTP URL) and the token
from the backend project's `.auth` file. The client stores `{address, token}`
locally and automatically reconnects to that target after restart. **Log out**
clears the target so another host can be entered. The frontend never reads the
backend project path and never starts or stops the backend.

Build the production bundle:

```bash
pnpm tauri build
```

Checks:

```bash
pnpm test    # vitest
pnpm build   # tsc + vite build
```

For browser checks against the real backend, first run `uv sync --locked --extra dev` at the repository root. Then, from `visualization/`:

```bash
node node_modules/playwright/cli.js install chromium  # once, if needed
node node_modules/playwright/cli.js test --config test/e2e/backend.config.ts
```

The harness uses the repository `.venv`, an isolated project under `.local-test/`, and scripted model responses. It needs no model credentials. Logs and screenshots also stay under `.local-test/`.

## Architecture

- `src-tauri/src/lib.rs` — Tauri Rust boundary for frontend-only capabilities such as trace export; connection credentials stay in the client storage module.
- `src/api/` — Endpoint HTTP client and WebSocket event stream (exponential-backoff reconnect, gap detection).
- `src/features/` — Feature owners for chat, trace, runtime, settings, workspace, history, context, resources, Home and Memory; each surface reads the typed Endpoint projections.
- `src/store/` — Zustand stores for application, connection, turn, settings draft and interface preference state. Endpoint connection and credential persistence are coordinated by `src/app/connection.ts` and the connection store.
- `src/components/ui/` + `src/components/markdown/` — design-system primitives and the shared Markdown renderer.

## Features

### Chat

- Conversation of user turns: user bubbles on the right, agent rows on the left.
- Final answers rendered as Markdown (GFM).
- **Live status disclosure** while a turn runs: current phase and model/action activity, a three-phase stepper, the todo/milestone working snapshot, and a rolling semantic activity feed (context loading, domain selection, action execution, workspace changes…).

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
- Text editor with live Markdown preview (source / split / preview). Saves update the active Workspace file; external concurrent edits are not protected by a revision/CAS protocol.
- Binary resources preview (images render) and download.

### Global

- Background Context panel: the currently loaded top-level links with rendered content.
- Maintenance dialog: daily / home / memory requests with availability hints.
- Light/dark themes, shared Chinese/English interface language, toast notifications, connection status bar with day/revision/turn state.

### Interface language

The Settings → Interface page stores the project-shared `locale` in the backend Presentation configuration. `zh-CN` is the fixed default; connected controls use stable frontend message IDs and update immediately. Other clients see the change after they reconnect or refresh project presentation settings. Catalog entries use stable backend identities and fall back to source text when no frontend translation exists; user input, files, Agent/model text, configuration values, and diagnostics remain as received. See [frontend localization design](docs/design/i18n.md) for the ownership and dynamic content rules.

To add fixed interface copy, add the same stable ID to both locale modules under `src/i18n/messages/`. Mounted components can read it through `useI18n`; long-lived displayed messages use `message()` and `LocalizedText`. Keep user/model/catalog values out of the UI dictionaries. Run `pnpm test` and `pnpm build` after changing copy or translation projection.

## Notes

- The frontend only communicates through the authenticated Endpoint at the address entered by the user. It does not read `runtime/`, Session, Home, or Memory directly.
- The backend is owned by the visible Terminal that ran `tinysoul start`; closing the frontend only disconnects it.
- Frontend design documents are in `docs/design/`; completed analysis and execution plans are in the repository's `../docs/analysis/done/` directory.
