# Context and references

Read the current narrative first: Session groups completed interactions by Turn; Inputs hold this Turn's accepted instructions and replies; Home/Memory supply background; Trace recounts inputs, decisions, actions, questions and replies; Working describes the current plan and resources.

A reference precisely locates something. Its nearby title, summary or excerpt explains why it matters. The colon names its owner, slashes express hierarchy, and # selects a position inside it. Copy a returned reference into that owner's Inspect, read the result, then follow relevant child references. You do not need to reconstruct internal storage or identifiers.

- `home:top/agent/<name>` and `home:top/skills/<name>` are loadable top entries without file extensions. `load_background` accepts exposed top refs. `home:resource/<space>/<path.ext>` identifies a file. `home.inspect` reads a known top or resource; `home.search` discovers candidates.
- `home:mount/domain/<domain>` and `home:mount/action/<domain>/<action>` are automatic task-local guidance, not ordinary Inspect/load targets.
- `memory:current/latest/target` are bound by the current context. Persistent knowledge uses `memory:daily/<date>`, `memory:entity/<name>`, `memory:concept/<name>`, `memory:fact/<cite>` or `memory:note/<cite>`. Use the available Memory Inspect for known references and Search for discovery.
- `workspace:<path>` identifies today's file or directory. `workspace.inspect` accepts it, optionally with a line or heading fragment. Text returns as an Action result; directory entries carry descriptions and refs; other types return metadata and require an appropriate reading/conversion capability. Working keeps descriptions, not file bodies.
- `turn:trace/<date>/<number>` is this Turn's Trace root. `#input/0`, `#action/0`, `#entry/1` and `#node/1` locate its contents. `core.context.inspect` reads it or an exposed Session reference such as `session:turn/<date>/<number>`; `session:map` navigates interpretations and their sources.

Do not guess a target exists. Search returns explained references without loading their full bodies. Inspect returns a bounded page; use its continuation only when another page is needed. A search result_handle is a temporary result set for further search operations, not an Inspect target or permanent memory reference. Dates identify Turns but do not grant access to earlier days through model tools.

After folding, recall the explained parent reference and follow its children. Re-inspecting Workspace reads its current state; an old reading action records what was read and the coverage, not the old body.
