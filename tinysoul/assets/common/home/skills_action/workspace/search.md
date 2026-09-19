# Workspace Search

Search a non-empty single-line query in an explicit scope. The default is literal matching; set `regex=true` for a bounded regular expression. File scope uses one exact text Link; directory scope uses a `workspace:path/` prefix; Workspace scope uses an empty locator. Treat `coverage.complete=false`, including regex timeout, as incomplete coverage rather than evidence of absence. Use returned fragments directly, and line hints with `workspace.read` when more context is needed.
Use `scope = {kind: "file", locator: "workspace:..."}` for one file, `scope = {kind: "directory", locator: "workspace:path/"}` for a directory prefix, and `scope = {kind: "workspace", locator: ""}` for the whole Workspace.
