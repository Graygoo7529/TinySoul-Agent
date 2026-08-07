# Workspace Action Contract and Stage2 Planning Execution Plan

## Objective

Align Workspace and Script authoring actions with the TinySoul owner model, remove
the `search_text` Tool/schema mismatch, make additive and exact edits distinct,
and give Phase2 concise action-specific planning guidance without introducing
rigid chapter-sized output rules or mandatory planning metadata.

The implementation must preserve the project-wide boundaries in `AGENT.md`:
Workspace owns resource facts and commits, Action owns action contracts and
results, LLM owns model calls, and Runtime owns control flow. Action-specific
configuration may override domain/default configuration. A transient failure may
legitimately be retried with the same parameters; no runtime duplicate-parameter
guard is added.

## Confirmed Semantics

### Search

`workspace.search_text.scope` will use one discriminated shape:

```json
{"kind": "file|directory|workspace", "locator": "..."}
```

`file.locator` is an exact Workspace Link, `directory.locator` is a directory
prefix, and `workspace.locator` is the empty string. The catalog schema and
`_search_scope` runtime parser must accept and reject the same shapes. The
existing restricted schema subset remains unchanged; no `oneOf` extension is
introduced for this action.

### Workspace mutation actions

- `workspace.create` is an LLM-backed create-only action. It rejects an existing
  target and has no `overwrite` or digest parameter.
- `workspace.append` is a native action that appends exact UTF-8 text to an
  existing text resource. The fragment is bounded by Workspace's
  `max_write_chars`; the operation has no automatic newline insertion and no
  unchanged/repeated-parameter guard. An optional `expected_digest` protects
  against stale edits.
- `workspace.patch` remains a native, digest-aware, unique `old_text` to
  `new_text` replacement. It is no longer documented as the default append
  mechanism.
- `workspace.rewrite` remains an LLM-backed complete replacement of an existing,
  fully readable target. Truncated targets still require read plus patch/append.

The low-level Workspace engine write/bundle APIs retain their generic overwrite
support for other owners such as Web fetch, resource conversion, and Endpoint
mutations. The create-only boundary is enforced by the public Workspace action.

### Script authoring actions

`execution.write_script` becomes `execution.create_script` and is create-only;
`execution.rewrite_script` remains the complete overwrite path. Script patch,
promote, and execution actions retain their current ownership and contracts.
The internal resolver may continue to use a generic overwrite flag where needed
by rewrite or promote implementation.

### Timeouts and configuration precedence

The default `[action] llm_action_timeout_seconds`, every concrete `llm_action`
catalog runtime, and `web.search_by_kimi` will use `600` seconds. The concrete
action value still takes precedence over domain/default values; the generic
setting is not a hard constraint. Non-LLM Workspace, Web, conversion, and native
action deadlines remain unchanged.

The 600-second value is the complete action deadline, including nested task
execution, provider switching, cancellation grace, and owner commit. It is not
a per-provider retry budget.

### Stage2 planning guidance

Guidance is added to Workspace and Script domain/action skills and the relevant
catalog descriptions, not to Runtime validation. It remains short and generic:

- choose create, append, patch, or rewrite from the target's current state;
- express the current action's goal, intended scope, approximate artifact or
  changed-text size, and any exact source references when useful;
- use exact read text and the latest digest for patching; use `reference_links`
  for internal LLM authoring actions;
- verify the committed result when the task requires it.

The guidance explicitly allows a complete bounded artifact, a natural fragment,
or several related changes when justified by task context and owner limits. It
does not require every action to produce one independently acceptable chapter,
does not add mandatory `intent`/length fields, and does not add a repeated-call
guard. `workspace.describe` keeps its current `effects` declaration.

## Implementation Steps

1. Add this plan and compare all changes against `AGENT.md` and the current
   Workspace/Action design documents.
2. Update search schema/runtime, add Workspace append engine and executor, and
   migrate Workspace write catalog/executor/prompts to create semantics.
3. Update Script catalog, registration, parameter parsing, executor mode, and
   prompt wording for create/rewrite semantics.
4. Set default/profile/concrete LLM and Kimi deadlines to 600 while preserving
   action-over-domain precedence.
5. Update Workspace/Script skills, catalog descriptions, `AGENT.md`, and design
   documents; remove stale `write`/append and fixed unchanged-retry wording.
6. Update catalog, engine, executor, prompt, migration, and timeout tests; run
   targeted tests and the full suite in the `TinySoul` conda environment.
7. Re-read this plan and the modified design documents, verify every confirmed
   semantic is represented in code/tests/docs, and record any residual risk.

## Acceptance Criteria

- A file/directory/workspace `search_text` call has one schema/runtime contract.
- Append does not require an invented `old_text`; patch rejects missing or
  ambiguous anchors and preserves digest semantics.
- Create cannot overwrite; rewrite is the complete overwrite path; script
  authoring follows the same split.
- All eight LLM actions and Kimi Search resolve to 600 seconds while unrelated
  action deadlines remain unchanged.
- Stage2 guidance is concise, action-specific, reference-aware, and flexible;
  no new hard planning protocol or duplicate-call guard exists.
- Workspace owner limits remain authoritative and no change is made to
  `workspace.describe` effects.
- Targeted and full tests pass, and this plan matches the final implementation.

## Verification

Status: `done` (2026-08-07).

- Re-read `AGENT.md`, Home `agent/AGENT.md`, and the Action/Workspace/Script
  design documents after implementation; the owner boundaries and Phase2/Phase3
  action semantics are consistent with the code.
- `C:\Anaconda3\envs\TinySoul\python.exe -m compileall -q tinysoul` passed.
- Focused catalog, Workspace, Script, Loop, Session, App, and release tests
  passed, including the legacy `search_text` scope rejection case.
- Full local gate passed through `scripts/test.ps1 -Suite Full`: 876 passed,
  2 skipped, and 21 external tests deselected. The first gate attempt hit one
  transient Windows staging-directory `WinError 5`; an immediate retry and the
  final post-audit run both passed.
- `scripts/typecheck.ps1` passed with `All checks passed!`.
- `conda activate TinySoul` could not be used in this shell because Conda
  attempted to read a permission-restricted `C:\Users\Aogo\.config`; the
  direct interpreter above is the same TinySoul environment used for tests.

Residual boundary: low-level `WorkspaceEngine.write_text/write_bundle` keeps
generic overwrite support for non-Workspace-action owners. The public action
surface is create/append/patch/rewrite, and no compatibility alias or duplicate
parameter guard was retained.
