# Workspace Text Search

Search a non-empty single-line literal query in an explicit scope. File scope requires one exact text Link; directory scope requires a `workspace:path/` prefix; Workspace scope has no locator. Treat `coverage.complete=false` as a partial scan, use returned fragments directly, and use line hints with `workspace.read` when more context is needed.
