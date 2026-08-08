# Use TinySoul Context and Link

## Read the Current Context

Start with the Context already constructed for the current model task. UserInputs state the current request. Background contains automatically loaded Agent defaults, optional automatic Memory, general skill metadata, and any Top content loaded during this Turn. TurnTrace then records current-Turn decisions and action feedback. The later WorkingContext describes the current milestones, todos, and Workspace resource projection and carries the Trace boundary at which that state is valid.

## Follow Link Ownership

- `home:agent@<path>` and `home:skills@<skill>` are extensionless Top identities mapped to Markdown entry files. Load one or more currently exposed Top Links with `load_background` when their bodies are relevant.
- `home:<space>/<relative-path.ext>` is a progressive Home resource. Read it with `home.resource.read`; its result belongs in TurnTrace.
- `memory:current`, `memory:latest`, and `memory:target` are Context-only references. Persistent Markdown uses `memory:daily/YYYY-MM-DD`, `memory:entity/<name>`, `memory:concept/<name>`, `memory:fact/<cite>`, or `memory:note/<cite>`. Use `core.memory.inspect` to discover or traverse links and `core.memory.recall` for one exact full document; use `core.memory.memorize` only to patch current active memory.
- `workspace:<relative-path.ext>` is a current-day resource handle. Pass it to the owning Workspace or LLM action instead of treating the Link as file content. Prefer the current Working projection over an older Trace entry when availability differs.
- `home:skills_domain:<domain>` and `home:skills_action:<domain>/<action>` are framework prompt mounts. They are injected into their owning task and are not loaded through `load_background` or `home.resource.read`.

## Discover Before Loading

Do not guess that a Link exists. Prefer a Link already present in core, user facts, skill metadata, Session or Memory context, WorkingContext, or TurnTrace. Use `home.top.search` for undisclosed skills. A successful search exposes candidate Top Links but does not load their bodies; load the selected Link in a later Phase1 step.
