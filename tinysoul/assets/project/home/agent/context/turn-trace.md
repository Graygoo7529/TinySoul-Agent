# Turn Trace Context

TurnTrace records current-Turn decisions and Action feedback in occurrence order. Current UserInputs are rendered separately.

Recent entries are visible. Older entries may be represented by a `turn:trace@...` heap reference; use the Context actions only when their detail is needed. Inspect and recall results return to the current Trace, not Background.

Trace entries describe what was known or attempted at that point. Use the later Working state when an earlier task or Workspace state is stale. Links remain resource handles rather than inline content.
