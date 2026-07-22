# Turn Trace Context

TurnTrace records current-Turn decisions, action feedback, and framework phase notes in occurrence order. Current UserInputs are rendered separately and are not copied into the Trace.

Older canonical entries may be represented by a `turn:trace@...` heap head. Use the Context trace inspection and recall actions only when those earlier details are needed. A recalled or inspected result returns to the current Trace and does not become Background.

Trace entries are evidence of what was decided, attempted, committed, or returned at that point in the Turn. They may mention earlier todo states or Workspace revisions. The later WorkingContext message is the current materialized state at the composition boundary and takes precedence when an earlier Trace state is stale.

Links in Trace remain references owned by their modules. A `workspace:` Link does not inline file content, and a Home or Memory Link does not imply that its body has been loaded.
