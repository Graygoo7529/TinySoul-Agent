# Session

Use Session only for completed prior Turns. Current-Turn decisions and results belong to `context.trace`; Workspace resources belong to `workspace:` actions.

Use `session.history.inspect` when the concrete prior Turn ref is unknown. Once a `session:turn/...` ref is known, use `session.history.actions` for complete Action counts, outcomes, failure groups, and trace indexes. Do not reconstruct those facts by manually counting raw recall pages. Use `session.history.recall` only when exact trace entries or a summary's child refs are needed, and follow the returned continuation cursor verbatim.

Treat the `source`, `summary`, `coverage`, and continuation fields returned by Session as authoritative. `scan_complete` means the complete canonical trace was scanned, `pairing_complete` means every Action call/result paired without anomaly, and `page_complete` only describes the current detail or recall page; do not substitute one for another. Never send a Session ref to Context actions or a Context trace ref to Session actions. Follow an Action failure's disposition and correct the owner, ref, cursor, or request instead of guessing offsets.
