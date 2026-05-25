# TinySoul Persistent Event Log and Unified Reference Model

> Date: 2026-05-25
> Status: design draft
> Scope: persistent runtime trace, provenance, resource references, replay, and context selection

---

## 1. Design Intent

TinySoul is moving away from the traditional chat-agent model where the user and
assistant transcript is appended into context as one long text stream. The
project is instead centered on `QueryLoop`: every user request becomes a
bounded loop of action selection, action execution, state update, and control
signals.

Once TinySoul gains session maps, long-term memory, agent-home skills, behavior
drafts, and progressive context loading, the framework needs a durable way to
answer four questions:

1. What happened?
2. Which resource was used?
3. Why was it selected into context?
4. What later changed because of it?

The persistent event log and unified reference model are the foundation for
those answers. They should be implemented before complex memory, semantic maps,
or skill evolution.

The central principle is:

> Every piece of context that affects a QueryLoop should have a stable reference,
> and every meaningful runtime transition should be recorded as an append-only
> event.

---

## 2. Why This Comes First

Memory, session semantic maps, and skill drafts all depend on provenance. If a
memory says "the user prefers structured design documents", TinySoul must know
which queries, action records, and drafts support that claim. If a skill draft
proposes changing an action workflow, TinySoul must know which repeated runtime
pattern caused the proposal.

Without persistent events and stable references:

- memory becomes ungrounded summary text;
- semantic maps cannot be replayed or debugged;
- drafts cannot explain why they exist;
- context loading becomes hidden prompt mutation;
- failures are hard to reproduce;
- daily consolidation has no reliable input.

The first implementation should therefore be deliberately boring: JSONL event
files, typed URIs, source references, and deterministic indexes. More advanced
graph reasoning can come later.

---

## 3. Core Concepts

### 3.1 Event

An event is an append-only fact about the runtime. It does not have to be shown
to the model. It exists for replay, debugging, consolidation, memory extraction,
and context provenance.

Recommended event envelope:

```json
{
  "event_id": "evt_20260525_000001",
  "event_type": "action.completed",
  "timestamp": "2026-05-25T14:35:20.123+08:00",
  "session_id": "session_20260525",
  "query_id": "query_20260525_0003",
  "loop_id": "loop_20260525_0003",
  "turn": 2,
  "step": "execute_action",
  "source": "QueryLoop",
  "refs": [
    "action://query_20260525_0003/exec_abc123",
    "workspace://main/docs/design/chat/20260525_architect.md"
  ],
  "payload": {},
  "parent_event_ids": [
    "evt_20260525_000000"
  ],
  "schema_version": 1
}
```

The envelope should remain stable. Event-specific details belong in `payload`.

### 3.2 Reference

A reference is a typed pointer to a resource, runtime object, memory item, event,
or draft. The reference should be safe to inject into prompts and stable enough
to appear in action records, semantic maps, and memory evidence.

References are not just paths. They also express namespace and ownership.

Examples:

```text
workspace://main/docs/design/core_design_query.md
agent://system/AGENT.md
agent-ref://system/references/agent-behavior/codex.md
skill://workflows/debug-test-failures
draft://skills/debug-test-failures/proposal-1/change.diff
session://2026-05-25/nodes/loop-0003
memory://knowledge/user-pref-structured-design
memory://episode/2026-05-25/query-0003
event://2026-05-25/evt_000123
action://query_20260525_0003/exec_abc123
```

The important distinction is namespace:

- `workspace://` points to user work files.
- `agent://` points to stable agent-home system material.
- `agent-ref://` points to read-only supporting references.
- `skill://` points to active behavior skills.
- `draft://` points to untrusted proposed changes.
- `session://` points to daily semantic-map nodes, edges, or propositions.
- `memory://` points to long-term knowledge or episodic memory.
- `event://` points to raw runtime facts.
- `action://` points to action executions.

### 3.3 Source Ref

A source ref is a reference used as evidence. Memory items, propositions,
semantic edges, and drafts should all keep source refs.

Example:

```json
{
  "proposition": "The user wants TinySoul to use QueryLoop rather than transcript stuffing.",
  "source_refs": [
    "event://2026-05-25/evt_000018",
    "session://2026-05-25/nodes/query-architecture-0001"
  ],
  "confidence": 0.96
}
```

### 3.4 Context Load Record

Progressive disclosure must be observable. Whenever TinySoul loads a resource
into active prompt context, it should record:

```json
{
  "uri": "skill://workflows/debug-test-failures",
  "kind": "skill",
  "load_mode": "SUGGESTED",
  "scope": "turn",
  "owner": "ContextPlanner",
  "reason": "The query asks to diagnose failing tests.",
  "relevance": 0.84,
  "loaded_at_turn": 1,
  "expires_at_turn": 2
}
```

This prevents hidden prompt mutation and gives Step4 context maintenance
something concrete to manage.

---

## 4. Event Taxonomy

The first implementation should keep the taxonomy small but expressive.

### Session and Query

```text
session.started
session.ended
query.started
query.completed
query.suspended
query.aborted
query.exhausted
```

### Context Planning

```text
context.bundle_built
context.resource_suggested
context.resource_loaded
context.resource_unloaded
context.resource_compacted
context.resource_refreshed
```

### LLM Steps

```text
llm.step.started
llm.step.completed
llm.step.failed
llm.output.validated
llm.output.rejected
```

The event payload should avoid storing secrets. It may store prompt summaries,
schema names, model profile, token estimates, and parsed output. Full prompt
capture can be optional and gated by settings.

### Loop Steps

```text
loop.turn_started
loop.turn_ended
loop.step_started
loop.step_completed
loop.step_recovered
```

### Actions and Signals

```text
action.selected
action.parameters_generated
action.started
action.completed
action.failed
action.timeout
action.cancelled
signal.emitted
signal.processed
```

### State and Workspace

```text
state.updated
state.action_record_acknowledged
workspace.scanned
workspace.resource_observed
workspace.resource_read
workspace.resource_written
workspace.resource_deleted
```

### Memory and Drafts

```text
memory.candidate_created
memory.candidate_accepted
memory.item_written
draft.created
draft.tested
draft.promoted
draft.rejected
```

---

## 5. Storage Design

### 5.1 Initial Storage: JSONL

Start with append-only JSONL. It is easy to inspect, easy to test, and does not
force early schema migration work.

Recommended layout:

```text
home/runtime/
  sessions/
    2026-05-25/
      session.json
      events.jsonl
      refs.jsonl
      context_loads.jsonl
      artifacts/
```

If TinySoul later supports multiple users or multiple machines, `home/runtime`
can become configurable through settings.

### 5.2 Indexes

JSONL is the source of truth for the MVP. Lightweight indexes can be generated:

```text
home/runtime/index/
  events.sqlite
  refs.sqlite
```

Suggested SQLite tables:

```text
events(event_id, event_type, timestamp, session_id, query_id, loop_id, turn, step)
event_refs(event_id, uri)
refs(uri, kind, first_seen_event_id, last_seen_event_id, content_hash, summary)
context_loads(uri, query_id, load_mode, scope, owner, relevance, loaded_at_turn)
```

The index can be rebuilt from JSONL, so corruption does not destroy the trace.

---

## 6. Unified URI Rules

### 6.1 General Rules

- URIs are typed; never infer namespace from a raw path.
- Paths are root-relative inside their namespace.
- `..` escapes are invalid.
- Absolute filesystem paths should not be exposed to the model.
- The original local path may exist in resolver metadata, not in prompt-visible
  references.
- URI resolution must be deterministic and testable.

### 6.2 Workspace URI

```text
workspace://<workspace-id>/<relative-path>
```

Examples:

```text
workspace://main/main.py
workspace://main/docs/module/loop.md
```

Resolver:

- authority: workspace id
- path: relative to `Workspace.root`
- access: must pass `Workspace.resolve_access()`

### 6.3 Agent Home URI

```text
agent://system/AGENT.md
agent-ref://system/references/<topic>/<file>.md
skill://workflows/<skill-id>
draft://skills/<skill-id>/<proposal-id>/change.diff
```

Resolver:

- root: `home/agent`
- stable system files are read-only by default
- skills and drafts have separate trust levels
- drafts are never auto-loaded as trusted behavior

### 6.4 Session URI

```text
session://2026-05-25/nodes/<node-id>
session://2026-05-25/edges/<edge-id>
session://2026-05-25/propositions/<prop-id>
```

Session refs should not depend on raw line numbers in transcript. They should
point to semantic-map objects derived from events.

### 6.5 Memory URI

```text
memory://knowledge/<memory-id>
memory://episode/<memory-id>
```

Knowledge memories are structured and relatively stable. Episodic memories are
time-bearing records of what happened.

### 6.6 Event and Action URI

```text
event://2026-05-25/<event-id>
action://<query-id>/<execution-id>
```

Action URIs are runtime objects. They may be used by semantic maps and memory
evidence, but they should resolve back to event records rather than directly to
mutable in-memory objects.

---

## 7. Integration With Current Code

### 7.1 New Modules

Recommended first modules:

```text
tinysoul/runtime/
  ids.py
  event_log.py
  session_store.py

tinysoul/refs/
  uri.py
  model.py
  resolver.py
  registry.py
```

Later modules:

```text
tinysoul/context_bundle/
  model.py
  planner.py
  renderer.py

tinysoul/agent_home/
  model.py
  index.py
  resolver.py
  manager.py
```

### 7.2 QueryLoop Integration

`QueryLoop` should accept an optional runtime recorder:

```python
QueryLoop(
    initial_query=...,
    runtime_recorder=...,
    context_planner=...,
)
```

Minimal instrumentation points:

- constructor: `query.started`
- each turn: `loop.turn_started`, `loop.turn_ended`
- Step1: `action.selected`
- Step2a: `action.parameters_generated`
- Step2b: `action.started`, `action.completed` or failure variants
- signal processing: `signal.processed`
- Step3: `state.updated`, `state.action_record_acknowledged`
- final outcome: `query.completed`, `query.suspended`, etc.

The recorder should be optional so existing tests can remain simple.

### 7.3 PromptBuilder Integration

`PromptBuilder` already supports selected context fields. It should not
automatically inject all new context.

Add optional provider fields:

```text
loaded_context
context_bundle
session_context
memory_context
agent_home_index
```

Step tasks can then choose what they need through `include_context`.

### 7.4 Action Record Integration

`ActionRecord` can either directly gain fields:

```python
source_refs: list[str]
propositions: list[dict]
event_ids: list[str]
```

or it can remain small and point to event log records:

```python
event_id: str
source_refs: list[str]
```

The second approach is cleaner for the MVP because it avoids turning
`QueryState` into a persistence database.

---

## 8. Implementation Plan

### Milestone 1: URI Parser and Resolver

Deliverables:

- `ResourceURI` dataclass
- parse/render/normalize functions
- validation rules for every namespace
- unit tests for invalid escapes and malformed URIs
- resolver registry with mock resolvers

Acceptance criteria:

- all prompt-visible resource identities can be represented as typed URIs;
- workspace and agent-home paths do not leak absolute paths into context;
- invalid `..` paths are rejected.

### Milestone 2: Event Log MVP

Deliverables:

- append-only JSONL writer
- event envelope schema
- deterministic event id generator
- session directory creation
- read/replay helper
- tests for append and replay ordering

Acceptance criteria:

- a QueryLoop run can produce a readable `events.jsonl`;
- tests can assert emitted event types without depending on timestamps;
- the log can be replayed into a simple in-memory timeline.

### Milestone 3: Runtime Instrumentation

Deliverables:

- optional recorder passed into `QueryLoop`
- action and signal events
- query outcome events
- event refs attached to action records where useful

Acceptance criteria:

- existing tests pass without a recorder;
- new tests verify a simple query produces expected event sequence;
- no LLM prompt changes are required yet.

### Milestone 4: Context Load Records

Deliverables:

- `LoadedContextResource`
- `context.resource_loaded` and `context.resource_unloaded`
- basic context load history
- renderer that exposes loaded refs and summaries to prompts

Acceptance criteria:

- any resource injected by Step0 or explicit action has a reason and scope;
- context can be unloaded without deleting the source resource;
- daily consolidation can inspect what context affected a query.

---

## 9. Invariants

- Event logs are append-only. Corrections are new events, not mutation.
- Prompt-visible references use typed URIs, not raw filesystem paths.
- Stable system context, workspace files, skills, drafts, session nodes, and
  memory items live in separate namespaces.
- Every loaded dynamic context resource records `load_mode`, `scope`, `owner`,
  `reason`, and `source_refs`.
- Memory and draft systems must cite event or session refs as evidence.
- The event log is not the prompt. It is the trace from which prompt context can
  be selected.

---

## 10. Open Questions

1. Should event logs live under repository-local `home/runtime`, or a user-level
   TinySoul home directory?
2. Should full prompts and raw LLM responses be recorded by default, or only
   when debug logging is enabled?
3. Should `ActionRecord` store event ids directly, or should events point to
   action execution ids only?
4. How much of context loading should be deterministic before allowing
   LLM-assisted context maintenance?
5. When multiple workspaces are active in one daily session, should
   `workspace-id` be user-assigned or derived from normalized root paths?

The recommended default is conservative: repository-local runtime storage,
summarized prompt traces by default, full prompt capture behind a setting,
deterministic context loading first, and explicit workspace ids.

