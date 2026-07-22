# Context and Links

Context is the model-facing projection of current facts and work; it is not a persistence root. It is reconstructed from UserInputs, BackgroundContext, TurnTraceContext, WorkingContext, and a task-specific prompt. TurnTrace presents current-Turn interaction history before the later WorkingContext presents current materialized state.

A Link identifies content or a resource without automatically embedding its body. Home Top Links can be loaded into Background. Home progressive resources and Memory search or recall results enter TurnTrace through their owning actions. Workspace Links remain handles for action-local file access. Domain and action HOW mounts enter only the task prompts owned by their framework phase.

Top Link syntax indicates Background eligibility, not automatic loading. The Agent core and effective allowlisted Context/user Agent Tops are automatic; other Top Links are loaded when they have been exposed in the current Context and are relevant to the task. All general HOW metadata is exposed automatically so Phase1 can decide which skill body to load.

The effective allowlisted Agent Context pages are also automatic Background defaults: <home:agent@context/background>, <home:agent@context/turn-trace>, and <home:agent@context/working>. They explain stable visibility and Link semantics; domain/action HOW continues to own operational action guidance.

Related entity: <home:what@entity/tiny-soul>. Usage guidance: <home:how@tinysoul-docs>.
