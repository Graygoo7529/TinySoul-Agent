# Workspace Text Search

Search a non-empty single-line literal query in an explicit scope. File scope uses one exact text Link; directory scope uses a `workspace:path/` prefix; Workspace scope uses an empty locator. Treat `coverage.complete=false` as a partial scan, use returned fragments directly, and use line hints with `workspace.read` when more context is needed.
Use `scope = {kind: "file", locator: "workspace:..."}` for one file, `scope = {kind: "directory", locator: "workspace:path/"}` for a directory prefix, and `scope = {kind: "workspace", locator: ""}` for the whole Workspace.
