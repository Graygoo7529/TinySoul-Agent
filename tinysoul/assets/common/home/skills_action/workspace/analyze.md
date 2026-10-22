# Workspace Analyze

Select all `references` in Phase2 and pass only exact Workspace text references plus one bounded intent. This action does not accept directories, expand scopes, or choose additional files in Phase3. If a reference budget failure is returned, reduce the reference set or first locate narrower evidence with `workspace.search` and `workspace.read`.

**Use when**: Asking a semantic question across curated reference materials; determining consistency, contradiction, or coverage in known documents; or obtaining a synthetic judgment that requires reading multiple bounded texts together.

**Avoid when**: The intent is open-ended code generation, arbitrary mutations, or exploratory directory traversal that cannot be constrained to a known reference set. For discovery, use workspace.search with directory source and select; for code generation or editing, use workspace.compose or direct edit/append after reading.
