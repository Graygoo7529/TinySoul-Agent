# Use TinySoul Context and Link

## Read the Current Context

Start with the Context already constructed for the current model task. Background presents identity, prior Session facts, current UserInputs, and loaded Home/Memory guidance. TurnTrace then records current-Turn decisions and action feedback. In the later Working section, plan describes milestones and todos, while workspace presents current resource Links and summaries. Resource bodies remain inside explicit reads or Action-local task input.

## Follow Link Ownership

- `home:agent@<path>` and `home:skills@<skill>` are extensionless Top identities mapped to Markdown entry files. Load one or more currently exposed Top Links with `load_background` when their bodies are relevant.
- `home:<space>/<relative-path.ext>` is a progressive Home resource. Use `home.inspect` for a known top or resource; use `home.search` to discover candidates. The result belongs in TurnTrace.
- `memory:current`, `memory:latest`, and `memory:target` are Context-only references. Persistent Markdown uses `memory:daily/YYYY-MM-DD`, `memory:entity/<name>`, `memory:concept/<name>`, `memory:fact/<cite>`, or `memory:note/<cite>`. Use `memory.search` to discover candidates and `memory.inspect` for one exact document and its direct refs; use `memory.memorize` only to patch current active memory.
- `workspace:<relative-path.ext>` is a current-day resource handle. Pass it to the owning Workspace or LLM action instead of treating the Link as file content. Prefer the current Working projection over an older Trace entry when availability differs.
- `home:skills_domain:<domain>` and `home:skills_action:<domain>/<action>` are framework prompt mounts. They are injected into their owning task and are not loaded through `load_background` or `home.inspect`.

## Discover Before Loading

Do not guess that a Link exists. Prefer a Link already present in core, user facts, skill metadata, Session or Memory context, WorkingContext, or TurnTrace. Use `home.search` for undisclosed Home content. A successful search exposes candidate Links but does not load their bodies; inspect the selected Link in a later action.
