# Agent Home Design

`home/agent/` is TinySoul's long-term agent behavior home. It is not the user
workspace. It stores stable system identity, read-only reference material,
evolvable skills, and draft changes that can shape future QueryLoop runs.

The design goal is:

- stable agent identity enters the loop as **system messages**
- skills and references are loaded **progressively** as dynamic user context
- agent-home files and workspace files stay in separate namespaces
- agent behavior can evolve through skills and drafts without silently changing
  trusted system sources

---

## 1. Directory Layout

Recommended structure:

```
home/agent/
├── system/
│   ├── AGENT.md
│   ├── IDENTITY.md
│   ├── USER.md
│   └── references/
│       └── <topic>/
│           └── *.md
├── index/
│   └── MANIFEST.yaml
├── skills/
│   ├── actions/
│   │   └── <action-name>/SKILL.md
│   ├── workflows/
│   │   └── <workflow-name>/SKILL.md
│   └── principles/
│       └── <principle-name>/SKILL.md
└── drafts/
    ├── skills/
    │   └── <skill-id>/
    │       ├── base.ref
    │       ├── change.diff
    │       └── rationale.md
    └── agent_policy/
        └── <proposal-id>/
            ├── base.ref
            ├── change.diff
            └── rationale.md
```

### system/AGENT.md

Stable operating contract for the agent. It describes how the agent should
behave, how to use actions, how to treat workspace files, and how to interpret
its agent home.

`AGENT.md` is written for the LLM and is loaded as loop-level system context.
It should contain high-level rules and routing policy, not large knowledge
documents. It should describe how to use the skill system, but should not
directly include skill files.

The agent should not directly modify `AGENT.md`. Proposed changes should be
written as diffs under `drafts/agent_policy/`.

### system/IDENTITY.md

Stable identity and communication style. It is loaded as loop-level system
context. Direct edits should be rare and review-oriented.

### system/USER.md

Long-term user preferences. It is loaded as loop-level system context, but its
content is preference guidance. It must not override the current user request,
the QueryLoop contract, action schemas, or framework safety constraints.

### system/references/

Read-only supporting material for `AGENT.md`, `IDENTITY.md`, and `USER.md`.
References store provenance, examples, external notes, and design background.
They are not behavior rules and should not directly drive action selection
unless a skill or stable system source distills them into operational guidance.

The agent may read references, but should not modify them. If a reference
suggests a behavioral improvement, the agent should create a skill draft or an
agent-policy draft.

### index/MANIFEST.yaml

Agent-home resource map for the framework. It is not the source of truth for
each skill's metadata. It declares collection-level defaults and index policy.

Example:

```yaml
system_sources:
  - system/AGENT.md
  - system/IDENTITY.md
  - system/USER.md

collections:
  - path: skills/actions
    kind: skill
    default_scope: action_bound
    default_load_policy: auto
  - path: skills/workflows
    kind: skill
    default_scope: workflow
    default_load_policy: retrieval
  - path: skills/principles
    kind: skill
    default_scope: principle
    default_load_policy: referenced
  - path: system/references
    kind: system_reference
    default_load_policy: on_demand
  - path: drafts/skills
    kind: skill_draft
    default_load_policy: explicit
  - path: drafts/agent_policy
    kind: policy_draft
    default_load_policy: explicit
```

### skills/

Reusable behavioral knowledge. A skill is a refined operational unit with its
own `SKILL.md` frontmatter. The frontmatter is the source of truth for that
skill's metadata.

Example:

```yaml
---
id: debug-test-failures
kind: skill
category: workflow
status: active
trust: reviewed
summary: Debug failing tests by narrowing failure scope and patching the minimal cause.
tags: [testing, debugging]
applies_to_actions: [read_file, edit_file]
load_policy: retrieval
---
```

Skill categories:

- `skills/actions/`: action-bound operational hints. These can be loaded
  automatically after an action is selected.
- `skills/workflows/`: multi-action procedures. These are usually loaded by
  retrieval or explicit context request.
- `skills/principles/`: reusable engineering principles. They remain skills,
  not stable system policy. `AGENT.md` may describe how to consult them, but
  should not include them directly.

### drafts/

Drafts are proposed changes to skills or stable agent policy. They are not
trusted instructions.

Drafts can be represented as diffs against active skills:

```
drafts/skills/debug-test-failures/
├── base.ref       # e.g. skills/workflows/debug-test-failures/SKILL.md
├── change.diff    # proposed patch
└── rationale.md   # why the change exists, source query, observed outcome
```

Agent-policy drafts follow the same pattern against stable system files:

```
drafts/agent_policy/tighten-workspace-boundary/
├── base.ref       # e.g. system/AGENT.md
├── change.diff
└── rationale.md
```

Draft status belongs to the draft metadata, not to the active skill or system
source. A draft can be inspected or tested, then promoted by an explicit review
workflow. Unreviewed drafts are never loaded automatically.

---

## 2. Namespaces and Boundaries

Agent-home resources and workspace files use different namespaces:

```
agent://system/AGENT.md
agent-ref://system/references/agent-behavior/codex.md
skill://workflows/debug-test-failures
draft://skills/debug-test-failures/proposal-1
workspace://docs/design.md
```

Rules:

- workspace actions only resolve paths inside the user workspace
- agent-home actions only resolve paths inside `home/agent`
- stable system sources and system references are read-only by default
- skills and drafts are the normal writable long-term evolution surface
- writing or promoting agent-home resources requires explicit actions such as
  `write_skill_draft`, `promote_skill`, or `propose_agent_policy`
- dynamic context should show agent resources under `loaded_agent_context`, not
  inside workspace state

This separation prevents the model from confusing long-term agent behavior
files with user task files.

---

## 3. Prompt Placement

### Stable System

Loaded at QueryLoop startup:

```
system/AGENT.md
system/IDENTITY.md
system/USER.md
builtin query_loop.system.md
```

These are assembled through `home_loop_system_sources()` and
`build_loop_system()`. The currently implemented helper still points to the
flat `home/agent/AGENT.md`, `IDENTITY.md`, and `USER.md` layout; the structured
`system/` layout is the intended next evolution.

### Dynamic User Context

Loaded progressively into the user prompt context:

```
agent_resource_index
loaded_agent_context
loaded_skill_snippets
loaded_system_references
```

These are not system messages. They should be injected by `PromptBuilder`
through context fields or extra context.

---

## 4. Resource Selection and Loading Timing

Progressive loading is a strategy, not a resource type.

The loading pipeline:

```
discover -> shortlist -> load snippet -> load full -> retain or unload
```

Important distinction:

- loading to cache/index is not prompt injection
- loading to system is stable instruction injection
- loading to dynamic context is user-prompt context injection
- loading as an action result is observable task execution output

Every resource that enters dynamic prompt context should record:

```python
load_mode: str
scope: str
reason: str
owner: str
relevance: float | None
```

### Loading Modes

Recommended loading modes:

```python
PRELOAD          # outside the loop, into cache/index only
FIXED_SYSTEM     # startup system messages
FIXED_INDEX      # startup resource index context
SUGGESTED        # Step0 deterministic retrieval before Step1
CONTEXT_REQUEST  # Step1 context_requests, resolved before Step2a
ACTION_BATCH     # explicit search/read/load actions
REFERENCE_EXPAND # include/require/reference graph expansion
```

#### 1. PRELOAD

Loop-external preparation. This does not enter the prompt by itself.

Typical work:

- scan `home/agent`
- parse `index/MANIFEST.yaml`
- parse `SKILL.md` frontmatter
- build keyword or embedding index
- validate references
- detect broken links

Output:

```text
AgentHomeIndex
ResourceMetadata
EmbeddingIndex
ReferenceGraph
```

#### 2a. FIXED_SYSTEM

Loaded at QueryLoop startup as system messages:

```
system/AGENT.md
system/IDENTITY.md
system/USER.md
builtin query_loop.system.md
```

This is the only loading mode that enters system context by default.

#### 2b. FIXED_INDEX

Loaded at QueryLoop startup as lightweight dynamic context, not system:

```
index/MANIFEST.yaml summary
SKILL.md frontmatter summaries
resource collection summaries
```

Do not load all skills or references. The goal is discoverability, not full
knowledge injection.

#### 3. SUGGESTED

Before Step 1, the framework may run lightweight retrieval over the agent-home
index using:

- current query
- loop target
- current state summary
- available action metadata

It may inject a small set of relevant resource summaries or snippets into
Step 1 context. This is useful when the loaded material can affect action
selection.

This mode should use deterministic or non-generative tools when possible:

- tag matching
- action name matching
- keyword/BM25
- embedding search
- reference graph expansion

#### 4. CONTEXT_REQUEST

Step 1 may request additional context:

```json
{
  "actions": [...],
  "context_requests": [
    {
      "query": "safe git workflow for local changes",
      "kind": "skill",
      "reason": "The selected plan may modify version-controlled files."
    }
  ]
}
```

The framework resolves these requests before Step 2a. This keeps loading
observable and prevents hidden prompt mutation.

Context requests are not ordinary actions and should not create business action
records.

#### Action-Bound Submode

After Step 1 selects an action, the framework may load action-bound skills
declared by the action or indexed skill metadata.

Example:

```
selected action: git
auto load: skill://actions/git
scope: action
```

Action-bound loading should be small, deterministic, and bounded.

It can be modeled as `SUGGESTED` or `CONTEXT_REQUEST` depending on whether it is
framework-driven or requested by Step 1.

#### 5. ACTION_BATCH

Large workflow skills and references should be loaded through explicit actions:

- `scan_agent_home`
- `search_agent_home`
- `load_agent_resource`
- `read_agent_resource`

These actions record what was loaded and why. They are appropriate when the
model is unsure or when the resource is too large for automatic loading.

Example action parameters:

```json
{
  "query": "debug failing tests",
  "load_to_context": true,
  "scope": "turn"
}
```

#### 6. REFERENCE_EXPAND

Reference expansion is a resolver capability that can support any of the above
modes.

Default behavior:

- `@include`: strong dependency, may automatically load with strict depth and
  budget
- `@require`: must be loaded before using the current resource
- `@reference` / `@see`: add candidate metadata, do not load full content
- `@influenced_by`: provenance only, do not load by default
- `@supersedes` / `@conflicts_with`: retrieval and ranking signals

Recommended dependency candidates should appear in context as candidates rather
than being loaded blindly:

```json
{
  "candidate_references": [
    {
      "uri": "agent-ref://system/references/codex/debugging.md",
      "relation": "reference",
      "summary": "...",
      "load_hint": "use load_agent_resource if needed"
    }
  ]
}
```

### Step4 Context Maintenance

After Step 3, the framework may run a context-maintenance phase before the next
turn:

```
Step1 choose
Step2a generate parameters
Step2b execute actions
Step3 update state
Step4 context maintenance
```

This phase is not task solving. It keeps the dynamic context healthy:

- unload expired or low-value resources
- compact oversized resources into summaries
- refresh resources whose source changed
- reload resources still needed by open todos
- reselect top-k context when the current set is stale or over budget

The maintenance phase can be deterministic or use a lightweight LLM call over
summaries only. If an LLM is used, it should output maintenance operations such
as `keep`, `unload`, `compact`, and `reload_candidates`.

Maintenance may use restricted internal LLM tasks or maintenance-only tools, but
it should not dispatch ordinary user-visible actions. These internal tools must
be bounded, read-only with respect to workspace files, and limited to context
runtime operations such as retrieval, ranking, summarization, and compaction.

Examples:

- `retrieve_agent_context`
- `rank_loaded_context`
- `summarize_loaded_context`
- `compact_context_resource`

The output of any maintenance LLM task should be a `ContextMaintenancePlan`.
The framework then applies the plan by executing context operations such as
`unload`, `compact`, `refresh`, `reload`, or `reselect`. Maintenance-only tools
must not recursively trigger normal action dispatch or create Step3-visible
business action records.

---

## 5. References and Includes

`AGENT.md` and `SKILL.md` may contain controlled references. References use
typed URIs or root-relative paths that resolve to typed URIs.

Recommended syntax:

```md
@include agent://system/references/small-required-policy.md
@reference agent-ref://system/references/agent-behavior/codex-notes.md
@see skill://workflows/debug-test-failures
@require skill://actions/git
@influenced_by agent-ref://system/references/codex-debugging.md
@supersedes skill://workflows/old-debug-tests
@conflicts_with skill://principles/aggressive-refactor
```

Semantics:

- `@include`: load together with the current file; only for small, stable,
  required material
- `@reference` / `@see`: add to candidate index, do not load full content
- `@require`: if this skill is used, the referenced resource must be loaded
- `@influenced_by`: provenance only; do not load by default
- `@supersedes`: replacement relation
- `@conflicts_with`: conflict relation to consider during retrieval

Expansion rules:

- all paths resolve under `home/agent`
- no `..` escape
- maximum include depth
- maximum total character budget
- cycle detection
- references default to discovery, not full loading

Loading timing:

- `AGENT.md @include`: startup system expansion, strict budget, references only
- `AGENT.md @reference`: startup index enrichment for system references
- `SKILL.md @include`: load with that skill
- `SKILL.md @reference`: add candidates after that skill is loaded
- provenance references such as `@influenced_by` are audit links, not load
  dependencies

---

## 6. Loaded Context Lifecycle

Loaded agent resources are runtime context, not state mutations.

Suggested structure:

```python
LoadedContextResource:
    id: str
    uri: str                  # skill://..., agent-ref://..., draft://...
    kind: str                 # skill | system_reference | draft
    content: str
    summary: str
    load_mode: str            # SUGGESTED | CONTEXT_REQUEST | ACTION_BATCH | ...
    loaded_at_turn: int
    last_used_turn: int
    scope: str                # call | step | turn | action | loop
    owner: str                # step name | action name | execution_id | user
    priority: int
    relevance: float
    pinned: bool
    expires_at_turn: int | None
    reason: str
```

Scopes:

- `call`: one LLM call
- `step`: one loop step
- `turn`: current turn
- `action`: selected action or execution id
- `loop`: entire query loop
- `pinned`: explicitly retained until unloaded

Maintenance operations:

- `unload`: remove full content from active context
- `compact`: replace content with a summary
- `refresh`: reload because the source changed
- `reload`: load again because it remains relevant after prior unloading
- `reselect`: drop stale resources and retrieve a new top-k set

Unload order under budget pressure:

```
expired
-> action-scoped resources whose action completed
-> low relevance
-> old last_used_turn
-> large system references
-> workflow skills
-> pinned resources last
```

Unloading removes content from active context, not from disk. The framework may
keep a small history:

```python
UnloadedContextResource:
    uri: str
    summary: str
    loaded_reason: str
    unload_reason: str
    last_used_turn: int
```

This preserves observability without continuing to spend prompt budget.

---

## 7. Skill Evolution

Active skills and drafts share a metadata model, but not trust.

Recommended statuses:

```
draft
active
deprecated
```

Recommended trust levels:

```
untrusted
reviewed
trusted
```

Loading policy:

- active + trusted + action-bound: can auto-load
- active + reviewed + retrieval: can be loaded by Step0 retrieval
- draft + untrusted: summary may appear in index; full content requires explicit
  load or review
- deprecated: not loaded by default

Draft workflow:

```
runtime observation
-> write skill draft diff
-> review or test
-> promote_skill
-> active SKILL.md updated
```

Drafts as diffs are preferred when improving existing skills. They preserve the
base skill, make review easier, and avoid silently mutating long-term behavior.

Agent-policy evolution uses the same draft pattern:

```
runtime observation
-> write agent_policy draft diff
-> user or review action approves
-> update system/AGENT.md, system/IDENTITY.md, or system/USER.md
```

The agent should not modify stable system sources directly.

---

## 8. TinySoul Integration

Current implemented foundation:

- `home_loop_system_sources(home/agent)` builds system source declarations for
  stable system markdown files
- `build_loop_system()` appends builtin `query_loop.system.md`
- `tinysoul.infra.resources` loads filesystem/package/inline text resources
- `tinysoul.prompt.loop` and `tinysoul.prompt.action` separate system assembly
  from user prompt construction
- `PromptBuilder` owns user prompt context assembly

Future modules:

```
tinysoul/agent_home/
├── model.py       AgentResource, LoadedContextResource
├── index.py       scan MANIFEST + SKILL frontmatter
├── resolver.py    agent://, agent-ref://, skill://, draft:// URI resolution
├── manager.py     ContextResourceManager
├── maintenance.py post-turn context maintenance
└── actions.py     scan/search/load/read/promote/propose
```

Integration points:

- `QueryLoop` owns an optional `AgentHome`
- `QueryContext` exposes `agent_home_index` and `loaded_agent_context`
- `PromptBuilder` can include these fields per step
- `ParallelDispatcher` remains unrelated; loading is either pre-step enrichment
  or explicit action execution
- Action metadata may declare action-bound `skill_refs`
- a future Step4 context-maintenance phase may compact, unload, refresh, reload,
  or reselect dynamic context between turns
- Step4 maintenance may use restricted internal LLM tasks or maintenance-only
  tools, but must not dispatch ordinary actions

---

## 9. Invariants

- `system/AGENT.md`, `system/IDENTITY.md`, `system/USER.md` are stable
  loop-level system sources
- skills, system references, and drafts are dynamic context unless explicitly
  promoted into stable system policy
- `MANIFEST.yaml` defines collection-level routing, not duplicated per-skill
  metadata
- each `SKILL.md` frontmatter is the source of truth for that skill
- system references are read-only supporting material, not behavior rules
- `AGENT.md` describes how to use the skill system, not specific skill content
- agent-home resources use typed URIs (`agent://`, `agent-ref://`, `skill://`,
  `draft://`); workspace files use `workspace://`
- agent-home loading never bypasses root boundary checks
- stable system sources are not modified directly by the agent; proposed changes
  go through `drafts/agent_policy`
- drafts are never trusted or auto-loaded by default
- progressive loading is observable: loaded resource, reason, scope, and unload
  reason should be recorded
- dynamic context resources record their loading mode so maintenance can reason
  about why they are active
- unloading removes active prompt content, not source files
- context maintenance outputs plans and context operations; it must not trigger
  ordinary action dispatch or create user-task side effects
