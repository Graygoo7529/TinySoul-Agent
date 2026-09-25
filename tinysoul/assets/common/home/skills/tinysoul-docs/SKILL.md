---
title: TinySoul Documentation
description: Navigate TinySoul Context and Link semantics and load the right top-level knowledge or progressive resource for the current task.
---

# TinySoul Documentation

Use this skill when the current task depends on TinySoul's Context structure, Link ownership, progressive loading, or persistence boundaries.

## Workflow

1. Inspect the current Context for relevant Top Links and general skill metadata.
2. Use the Phase1 `load_background` control with one or more exposed Top Links when their full bodies are needed.
3. Use `home.search` when a relevant Home Link has not already been exposed; use `home.inspect` to read a selected top or resource progressively.
4. Treat progressive Home resources, Memory documents, Session history, and Workspace files according to their owning search/inspect actions instead of loading them as Home Background.
5. Keep task-local action results in TurnTrace and durable cross-Turn facts in their owning persistent module.

Detailed reference: <home:skills/tinysoul-docs/references/use-tinysoul-context-and-link.md>.
