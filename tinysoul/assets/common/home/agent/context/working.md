# Working State and Workspace Links

Working is the latest materialized state for this User Turn: milestones, todos, and current Workspace resource Links with summaries. It is rendered after TurnTrace and takes precedence when an earlier task state is stale.

A `workspace:<relative-posix-path>` Link is a resource handle, not file content. Use the exact exposed Link with the owning Workspace action; read-only inputs use `reference_links` and mutation targets use `target_link`.

Update milestones and todos from authoritative results. A successful mutation result establishes its declared commit; inspect content only when the task needs it.
