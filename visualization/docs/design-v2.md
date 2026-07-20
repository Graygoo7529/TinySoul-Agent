# TinySoul Desktop Frontend V2 Design

## Goal

Move from a debug-oriented panel (normal/verbose/model toggles, raw event boxes) to a user-level conversation application that still exposes the agent's internal reasoning on demand.

## Core Principles

1. **Conversation first**: the main surface looks like a chat history between the user and the agent.
2. **Progressive disclosure**: internal execution details (cycles, phases, actions, model calls) are hidden by default and revealed through nested, clickable expansions.
3. **No observation mode switch**: the event stream always runs at `model` level; the UI decides how much to surface.
4. **Backend is the source of truth**: all workspace mutations go through the Endpoint; the frontend never reads the local filesystem directly.
5. **Calm, focused aesthetic**: dark theme, generous whitespace, clear typography, subtle motion.

## Visual System

- Dark background `#0a0c0f`
- Surface cards `#111318`
- Elevated hover `#181b21`
- Borders `#23262d`
- Primary text `#f0f2f5`
- Secondary text `#8b949e`
- Accent `#58a6ff`
- Success `#3fb950`
- Warning `#d29922`
- Danger `#f85149`
- Radius `12px` for cards, `8px` for inline elements
- Font: system sans + JetBrains Mono for code

## Layout

- Fixed left sidebar (64px icon + labels) for Chat / Workspace / Session.
- Main content area fills the rest.
- Bottom status bar for connection, active day, turn state.

## Chat Experience

- User messages align right with accent background.
- Assistant messages align left with surface background.
- Each assistant message contains:
  - Final rendered answer.
  - A discreet "Thinking" / "Steps" affordance.
  - When expanded: a vertical timeline of cycles.
  - Each cycle expands to show Phase 1 → Phase 2 → Phase 3.
  - Phase 2/3 expand to show action calls and results.
  - Each phase or action can jump to the underlying LLM task / model request.

## Derived Data

`useDerivedChat` consumes the raw `EndpointEvent[]` stream and builds:

- `ChatTurn[]` with user inputs, assistant output, terminal status, cycles, model tasks, background events.
- `Cycle[]` grouping phase and action events by `cycle` scope.
- `PhaseStep[]` mapping `loop.phase.*` events.
- `ActionRecord[]` pairing `action.call` with `action.result` by `call_id`.
- `ModelTask[]` grouping `llm.*` events by `task_id`.

## Workspace Experience

- Sidebar manifest summary (file count, size, kind breakdown).
- Resource list with inline summary and retention badge.
- Editor pane with digest/revision status and save state.
- Trash as a secondary list with restore action.

## Session Experience

- List of today's turns with status and summary.
- Recall pane for canonical trace text.
