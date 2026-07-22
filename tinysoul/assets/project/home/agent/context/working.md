# Working Context

WorkingContext is the current materialized workbench for this User Turn. It contains milestones, todos, the current Workspace resource projection, and the Workspace manifest revision. It does not contain file bodies.

WorkingContext is rendered after TurnTrace. Its `as_of_trace` object identifies the canonical Trace head and revision observed at the same composition boundary. This is an `as_of` relationship, not a claim that every Working change originated in Trace: Phase1 controls, Workspace synchronization, and external mutations can update Working state through their owning boundaries.

When an earlier Trace entry conflicts with the current milestone, todo, or Workspace projection, use WorkingContext as the current state. Continue to treat an authoritative successful mutation ActionResult as evidence that its declared commit occurred.

Reconcile milestones and todos from authoritative results during Phase1. Do not mark attempted or failed work done, and do not leave completed work pending or in progress.
