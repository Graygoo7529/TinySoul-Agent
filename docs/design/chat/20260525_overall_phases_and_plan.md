# TinySoul Overall Phases and Planning

> Date: 2026-05-25
> Status: design roadmap
> Scope: multi-day design direction for QueryLoop-centered personal Agent runtime

---

## 1. Executive Summary

Recent design discussions point to one coherent direction:

> TinySoul should become a QueryLoop-centered personal Agent runtime, not a
> transcript-centered chatbot.

The current project already has a workable inner loop:

```text
ChooseAction -> TakeAction -> UpdateState -> Signal/Trap -> LoopOutcome
```

The next stage should not replace this loop. It should add an outer context and
memory runtime around it:

```text
Step0 Context Planning
  session + memory + home/agent + workspace + drafts -> ContextBundle

Step1 ChooseAction
Step2 TakeAction
Step3 UpdateState

Step4 Context Maintenance
  loaded context + action records + state -> keep / unload / compact / draft candidate

Daily Consolidation
  event log + session map + drafts -> memory candidates + skill updates
```

The most important sequencing decision is:

> Build traceability and references first; build memory and reasoning on top of
> them later.

---

## 2. Design Premises

### 2.1 QueryLoop Is the Kernel

`QueryLoop` should remain the execution kernel. It coordinates actions, state
updates, signals, and outcomes. It should not become the owner of all memory,
all session graphs, all skill evolution, and all workspace selection.

This keeps the current architecture understandable:

- Loop orchestrates.
- Action executes.
- Context exposes runtime state.
- PromptBuilder renders selected context.
- Trap handles errors and control signals.

Long-term systems should enter through explicit context providers and runtime
hooks, not by turning the loop into a monolithic brain.

### 2.2 Context Is a Resource System

The old model is:

```text
conversation history -> prompt
```

The target model is:

```text
query -> retrieve/select resources -> ContextBundle -> prompt
```

Resources include:

- workspace files;
- session semantic-map nodes;
- knowledge memories;
- episodic memories;
- agent-home system material;
- skills;
- drafts;
- recent action records;
- loaded context summaries.

Each resource should be referenced, loaded, unloaded, compacted, and cited.

### 2.3 Memory Must Be Evidence-Based

Long-term memory should not be a pile of model-generated summaries. Every memory
item should keep source refs, confidence, scope, and time.

Knowledge memory and episodic memory have different roles:

- knowledge memory stores relatively stable facts, preferences, rules, and
  concepts;
- episodic memory stores what happened, when, under which session and task.

Both should be written through candidates first, not blindly committed.

### 2.4 Agent Home Is Not Workspace

`home/agent` is the agent's long-term behavior home. It stores system identity,
skills, references, and drafts. It should not be mixed with user workspace files.

Workspace actions operate on `workspace://`.

Agent-home actions operate on:

```text
agent://
agent-ref://
skill://
draft://
```

This separation is especially important once drafts and skill promotion exist.

### 2.5 Drafts Are the Evolution Surface

The agent should not silently rewrite its stable behavior. Behavior changes
should start as drafts:

```text
runtime observation
-> draft diff
-> test or review
-> promote
-> active skill or policy update
```

This makes self-improvement observable and reversible.

---

## 3. North-Star Architecture

```text
                         Daily Consolidation
              session map + events + drafts + memory candidates
                                  |
                                  v
    +-------------------+   +------------+   +------------------+
    | Long-Term Memory  |   | Agent Home |   | Skill/Draft Store |
    +-------------------+   +------------+   +------------------+
              \                 |                  /
               \                |                 /
                v               v                v
             +--------------------------------------+
             |          Step0 Context Planner        |
             |  query + refs + indexes -> bundle     |
             +--------------------------------------+
                                  |
                                  v
                         +----------------+
                         |   QueryLoop    |
                         | Step1/2/3 core |
                         +----------------+
                                  |
                                  v
             +--------------------------------------+
             |          Step4 Maintenance            |
             | keep / unload / compact / candidates  |
             +--------------------------------------+
                                  |
                                  v
                         Persistent Event Log
```

The event log sits underneath everything. It is the raw trace. The session map,
memory, and drafts are derived and curated layers above it.

---

## 4. Phase Plan

### Phase 0: Stabilize the Current Kernel

Status: mostly complete.

Current strengths:

- clear `QueryLoop` orchestration;
- `ActionRegistry` and action meta/detail separation;
- `QueryState` managers;
- `Workspace` resource boundary;
- `SignalBus` and `ErrorTrap`;
- broad test coverage.

Near-term cleanup:

- keep documentation synchronized with current file paths and signal names;
- avoid expanding the inner loop until external runtime hooks exist;
- keep existing tests passing while adding optional persistence.

Acceptance criteria:

- current test suite remains green;
- existing single-query behavior does not require memory or event-log services;
- new systems can be disabled in tests.

### Phase 1: Context Fabric MVP

Goal:

Build the substrate for traceability, references, and progressive context.

Deliverables:

```text
tinysoul/runtime/event_log.py
tinysoul/runtime/ids.py
tinysoul/refs/uri.py
tinysoul/refs/resolver.py
tinysoul/context_bundle/model.py
```

Capabilities:

- append-only JSONL event log;
- typed resource URIs;
- source refs on important runtime objects;
- optional event recorder in `QueryLoop`;
- `ContextBundle` model that can carry selected refs and summaries;
- initial prompt rendering for loaded context.

Why first:

Every later feature needs to know where information came from. This phase
prevents memory, draft, and semantic-map systems from becoming ungrounded text
generation.

Implementation notes:

- start with JSONL, not a database-first design;
- keep the recorder optional;
- do not inject event logs into prompts by default;
- add tests around event sequence and URI validation.

Acceptance criteria:

- a QueryLoop run produces a readable event trace;
- workspace, agent-home, skill, draft, session, memory, action, and event refs
  can be represented consistently;
- a future consolidation job can use events as input.

### Phase 2: Agent Home Index and Progressive Loading

Goal:

Make `home/agent` a first-class resource namespace.

Deliverables:

```text
tinysoul/agent_home/model.py
tinysoul/agent_home/index.py
tinysoul/agent_home/resolver.py
tinysoul/agent_home/manager.py
```

Capabilities:

- parse `MANIFEST.yaml`;
- parse `SKILL.md` frontmatter;
- scan `system/`, `skills/`, `references/`, and `drafts/`;
- expose lightweight resource summaries to Step0;
- support loaded context records with reason, scope, owner, and load mode.

Recommended directory target:

```text
home/agent/
  system/
    AGENT.md
    IDENTITY.md
    USER.md
    references/
  index/
    MANIFEST.yaml
  skills/
    actions/
    workflows/
    principles/
  drafts/
    skills/
    agent_policy/
```

Why second:

The current helper loads flat `home/agent/AGENT.md`, `IDENTITY.md`, and
`USER.md`. The intended design needs structured resources, but those resources
should be discoverable before they are automatically trusted.

Acceptance criteria:

- stable system files are loaded as system context;
- skills and references are dynamic context, not system context;
- drafts are indexed but not trusted or auto-loaded;
- every loaded resource records why it entered context.

### Phase 3: Step0 Context Planner and Step4 Maintenance

Goal:

Add lifecycle management around the current loop without changing the core
three-step contract.

Step0:

```text
query + current state + workspace index + agent-home index + session summary
-> ContextBundle
```

Step4:

```text
loaded context + state + action records
-> keep / unload / compact / refresh / candidate creation
```

Implementation points:

- `QueryLoop` accepts optional `context_planner` and `context_maintenance`.
- `QueryContext` exposes `get_context_bundle()` and `get_loaded_context()`.
- `PromptBuilder` can include these fields selectively.
- Step4 should not dispatch ordinary actions.

Why now:

Once resource references and agent-home indexes exist, TinySoul needs a bounded
way to choose what enters context and what leaves it. This is the practical form
of progressive disclosure.

Acceptance criteria:

- Step1 sees a compact ContextBundle instead of unbounded resource dumps;
- resource loading is logged;
- expired or low-value loaded context can be compacted or unloaded.

### Phase 4: Daily Session Semantic Map

Goal:

Turn the daily session into a semantic graph instead of a linear transcript.

Core objects:

```text
SessionNode
SessionEdge
Proposition
EvidenceRef
```

Initial edge types:

```text
mentions
depends_on
supports
refutes
resolves
extends
modifies
parallel_to
```

Initial proposition shape:

```json
{
  "id": "prop_0001",
  "kind": "goal",
  "text": "TinySoul should use QueryLoop as its core runtime.",
  "logical_form": null,
  "source_refs": ["event://2026-05-25/evt_000018"],
  "confidence": 0.94,
  "scope": "TinySoul architecture design",
  "created_at": "2026-05-25T15:00:00+08:00"
}
```

Why after Context Fabric:

The map should be built from event refs and action records. If implemented
before traceability, it will become another summary layer with weak evidence.

Implementation notes:

- start with LLM-assisted extraction from action records and query events;
- keep propositions natural-language first;
- add `logical_form` later;
- store `inferred_from` for derived edges and propositions.

Acceptance criteria:

- a daily session can show major goals, decisions, resources, and unresolved
  threads;
- semantic nodes cite events;
- Step0 can retrieve a small relevant subgraph for the next query.

### Phase 5: Memory Candidates

Goal:

Introduce long-term memory without letting the model permanently write every
summary it invents.

Memory layers:

```text
knowledge memory: structured facts, preferences, rules, concepts
episodic memory: time-bearing summaries of what happened
```

Candidate workflow:

```text
session events
-> extracted propositions
-> memory candidates
-> review / confidence threshold / explicit accept
-> committed memory
```

Recommended storage:

- SQLite or JSON for knowledge memory;
- embedding-backed store for episodic memory;
- source refs required for both.

Why candidates:

Personal agents are especially vulnerable to stale or overgeneralized memory.
Candidate review allows the system to improve without silently corrupting its
long-term model.

Acceptance criteria:

- nightly consolidation can produce memory candidates;
- each candidate cites source refs and scope;
- accepted memories can be retrieved into Step0 context;
- rejected candidates remain auditable.

### Phase 6: Behavior Drafts and Skill Evolution

Goal:

Turn repeated successful behavior into reviewable skill diffs.

Draft lifecycle:

```text
proposed -> tested -> accepted -> promoted -> deprecated
```

Draft contents:

```text
base.ref
change.diff
rationale.md
metadata.json
validation.json
```

Draft sources:

- repeated successful workflows;
- repeated user corrections;
- recurring failure recovery;
- useful project-specific procedures;
- stable preferences that should become skills.

Why after memory candidates:

Skill drafts are higher-stakes than memories because they affect future
behavior. They should be grounded in event patterns and session propositions.

Acceptance criteria:

- consolidation can propose a skill draft;
- drafts are never loaded as trusted behavior by default;
- promotion is explicit;
- promoted skills become indexed active resources.

### Phase 7: Capability Expansion

Goal:

Make TinySoul more useful as a local personal Agent.

High-value capabilities:

- stronger shell/subprocess action;
- project file search and batch edit;
- patch/diff action;
- git write workflows;
- background task runner with log tailing;
- project indexer;
- richer workspace snapshots.

Why not first:

These capabilities become more valuable once events, refs, and context bundles
exist. Otherwise, increased tool power creates more untracked behavior.

Acceptance criteria:

- actions emit structured events and refs;
- workspace changes can be tied to action executions;
- long-running tasks can be observed and stopped;
- project work can generate memory and draft candidates.

### Phase 8: Graph Reasoning, Sub-Agents, and MCP

Goal:

Add advanced intelligence and ecosystem integration after the runtime substrate
is stable.

Possible directions:

- light graph inference over propositions;
- conflict detection;
- sub-agent delegation with read-only context snapshots;
- skill graph compilation;
- MCP adapter for external tool servers.

Recommended order:

1. light graph inference;
2. sub-agent snapshots;
3. skill graph;
4. MCP adapter.

Why last:

Sub-agents and MCP expand the system boundary. They need stable refs, events,
context provenance, and workspace/session separation to remain debuggable.

---

## 5. Recommended First Implementation Slice

The first practical slice should fit in a small sequence of pull requests:

### PR 1: URI Model

- add `tinysoul/refs/uri.py`;
- parse and render typed URIs;
- validate workspace and agent-home path rules;
- add unit tests.

### PR 2: Event Log

- add `tinysoul/runtime/event_log.py`;
- implement append and replay;
- add session directory layout;
- add unit tests.

### PR 3: QueryLoop Recorder Hook

- add optional recorder argument to `QueryLoop`;
- emit query, turn, step, action, signal, and outcome events;
- keep existing behavior unchanged when recorder is absent.

### PR 4: ContextBundle Skeleton

- add model only;
- add `QueryContext.get_context_bundle()`;
- add optional prompt field;
- no retrieval yet.

### PR 5: AgentHome Index MVP

- scan current `home/agent`;
- parse future structured layout if present;
- expose summaries as candidates;
- record context load events when injected.

This sequence gives immediate value without forcing a premature memory system.

---

## 6. What Not to Do Yet

Avoid these early:

- full theorem prover;
- automatic skill promotion;
- memory writes without source refs;
- loading all skills into every prompt;
- making Step4 dispatch ordinary user-visible actions;
- implementing sub-agents before context snapshots are stable;
- database-first architecture before JSONL trace is working;
- mixing `home/agent` files with workspace actions.

These are not bad ideas in general. They are just too early before the trace and
reference substrate exists.

---

## 7. Planning Matrix

| Phase | Priority | Main Value | Main Modules | Depends On |
|---|---:|---|---|---|
| 0 Kernel stability | P0 | keep current loop reliable | existing loop/action/context | none |
| 1 Context Fabric | P0 | traceability and refs | runtime, refs, context_bundle | current kernel |
| 2 Agent Home Index | P0 | progressive behavior resources | agent_home | refs |
| 3 Step0/Step4 | P0 | context planning and lifecycle | loop hooks, context manager | refs, agent_home |
| 4 Session Map | P1 | non-linear daily understanding | session | event log |
| 5 Memory Candidates | P1 | long-term learning | memory | session map, event log |
| 6 Draft/Skill Evolution | P1 | behavior improvement | drafts, skills | memory candidates, agent_home |
| 7 Capability Expansion | P1 | stronger local agency | actions, workspace | event log, refs |
| 8 Graph/Sub-Agent/MCP | P2 | advanced orchestration | graph, mcp, delegation | stable context fabric |

---

## 8. Success Criteria

TinySoul has reached the intended next stage when:

1. A query can be replayed from its event trace.
2. Every prompt-injected resource has a typed URI and load reason.
3. A daily session can be summarized as a semantic map, not just transcript text.
4. Memory candidates cite events and session propositions.
5. Skill drafts are diffs with rationale and validation records.
6. Step0 can build a compact ContextBundle before QueryLoop starts.
7. Step4 can keep context healthy without performing business actions.
8. Long-term behavior changes require draft promotion, not hidden mutation.

---

## 9. Final Recommendation

The next phase should be framed as:

> Build TinySoul's Context Fabric.

This means implementing persistent events, unified refs, context bundles,
agent-home indexing, and observable context loading before building a rich
memory system.

Once Context Fabric exists, the rest of the design becomes much easier:

- session semantic maps are derived from events;
- memories are grounded in source refs;
- drafts explain their origin;
- skills can be loaded progressively;
- sub-agents can receive clean snapshots;
- MCP tools can be audited through the same event model.

This is the shortest path from the current prototype to a capable personal
Agent runtime.

