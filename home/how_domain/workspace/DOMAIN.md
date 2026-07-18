# Workspace

Use `workspace.read` when an exact text Link and relevant 1-based line range are known. Use `workspace.search_text` to locate a literal term in an explicit file, directory prefix, or the current Workspace before reading a narrower range. Use `workspace.analyze` only after selecting the exact text Links whose complete contents fit the analysis budget. Workspace inspection is read-only; use write, patch, rewrite, delete, or restore actions for mutations.
