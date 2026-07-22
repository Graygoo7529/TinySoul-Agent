# Workspace Context

A `workspace:<relative-posix-path>` Link identifies a resource in the current Business Day Workspace. It is a resource handle, not embedded file content, and it does not guarantee that an earlier referenced resource still exists.

The WorkingContext resource list and `workspace_revision` are the current materialized projection of the Workspace manifest. Earlier TurnTrace entries can refer to older revisions. When availability or summary information conflicts, use the later WorkingContext projection as current; the Workspace module remains the authority for path validation, manifest reconciliation, and file operations.

Resolve content only through the owning Workspace action or an action-local task prompt. Use exact Links exposed by WorkingContext, TurnTrace, or another authoritative result instead of guessing paths. Read-only references use `reference_links`; mutation targets use `target_link` at the Action boundary.

Successful authoritative mutation results prove their declared commit. Additional content verification is needed only when the user requests it or correctness cannot be established from the result.
