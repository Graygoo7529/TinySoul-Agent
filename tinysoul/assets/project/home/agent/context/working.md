# Working State and Workspace Links

## Working State

WorkingContext is the current materialized workbench for this User Turn. It contains milestones, todos, the current Workspace resource projection, and the Workspace manifest revision. It does not contain file bodies.

WorkingContext is rendered after TurnTrace. Its `as_of_trace` object identifies the canonical Trace head and revision observed at the same composition boundary. This is an `as_of` relationship, not a claim that every Working change originated in Trace: Phase1 controls, Workspace synchronization, and external mutations can update Working state through their owning boundaries.

When an earlier Trace entry conflicts with the current milestone, todo, or Workspace projection, use WorkingContext as the current state. Continue to treat an authoritative successful mutation ActionResult as evidence that its declared commit occurred.

Reconcile milestones and todos from authoritative results during Phase1. Do not mark attempted or failed work done, and do not leave completed work pending or in progress.

## Workspace Links

A `workspace:<relative-posix-path>` Link identifies a resource in the current Business Day Workspace. It is a resource handle, not embedded file content, and it does not guarantee that an earlier referenced resource still exists.

The WorkingContext resource list and `workspace_revision` are the current materialized projection of the Workspace manifest. The Workspace module remains the authority for path validation, manifest reconciliation, and file operations.

Resolve content only through the owning Workspace action or an action-local task prompt. Use exact Links exposed by WorkingContext, TurnTrace, or another authoritative result instead of guessing paths. Read-only references use `reference_links`; mutation targets use `target_link` at the Action boundary.

Successful authoritative mutation results prove their declared commit. Additional content verification is needed only when the user requests it or correctness cannot be established from the result.
