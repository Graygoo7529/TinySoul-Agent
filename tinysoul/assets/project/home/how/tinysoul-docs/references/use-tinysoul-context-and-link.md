# Use TinySoul Context and Link

## Read the Current Context

Start with the Context already constructed for the current model task. UserInputs state the current request. Background contains automatically loaded core and user knowledge, optional automatic Memory, general HOW metadata, and any Top content loaded during this Turn. WorkingContext describes milestones, todos, and Workspace resources. TurnTrace records current-Turn decisions and action feedback.

## Follow Link Ownership

- `home:agent@<path>`, `home:what@entity|concept/<path>`, `home:why@<path>`, and `home:how@<skill>` are extensionless Top identities mapped to Markdown entry files. Load one or more currently exposed Top Links with `load_background` when their bodies are relevant.
- `home:<space>/<relative-path.ext>` is a progressive Home resource. Read it with `home.resource.read`; its result belongs in TurnTrace.
- `memory:YYYY-MM-DD` identifies one date Memory. Use `memory.recall` for an exposed exact Link or `memory.search` to discover candidate dates.
- `workspace:<relative-path.ext>` is a current-day resource handle. Pass it to the owning Workspace or LLM action instead of treating the Link as file content.
- `home:how_domain:<domain>` and `home:how_action:<domain>/<action>` are framework prompt mounts. They are injected into their owning task and are not loaded through `load_background` or `home.resource.read`.

## Discover Before Loading

Do not guess that a Link exists. Prefer a Link already present in core, user facts, HOW metadata, Session or Memory context, WorkingContext, or TurnTrace. Use `home.top.search` for undisclosed WHAT, WHY, or general HOW knowledge. A successful search exposes candidate Top Links but does not load their bodies; load the selected Link in a later Phase1 step.

Related concept: <home:what@concept/context-and-links>.
