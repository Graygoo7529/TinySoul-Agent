# Workspace Search

Use source + steps + page. Query finds original-text literal matches by default; regex=true enables a bounded regular expression. A query must be a non-empty single line. Scope is {kind: "file", locator: "workspace:..."} for one file, {kind: "directory", locator: "workspace:path/"} for a directory, or {kind: "workspace", locator: ""} for the daily Workspace.

Use directory to discover resources, refs for exact known entries or line fragments, backlinks for real incoming Markdown links, and result to reuse a complete previous result. Optional filter, select and rerank steps constrain or order these candidates; directory → select supports semantic discovery without requiring literal overlap. Each model step has its own criterion and declared Context option. Models and providers are configured internally.

Results include links and real content previews with locations and coverage. A page contains only some members; continuation reads the remaining frozen members, while result_ref refers to the complete result. Use workspace.read for deeper text. Metadata for a non-text resource does not mean its body was read. A scope_required failure calls for a narrower scope or simpler pattern and is not evidence of absence. Explicit exclude_refs and source.where apply before content reading; a later filter only constrains the current snapshot.
