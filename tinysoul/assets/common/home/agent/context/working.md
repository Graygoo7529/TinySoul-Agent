# Working State and Workspace references

Working is the latest state projection for this User Turn. It contains plan milestones and todos, plus current plugin projections such as Workspace references and summaries, Job snapshots, and subagent connection state when present. It is rendered after TurnTrace and takes precedence when an earlier task state is stale.

A `workspace:<relative-posix-path>` reference is a resource handle, not file content. Use the exact exposed reference with the owning Workspace action; read-only inputs use `references` and mutation targets use `target_ref`.

Update milestones and todos from authoritative results. A successful mutation result establishes its declared commit; inspect content only when the task needs it.
