# Background Context

BackgroundContext contains information prepared before the current model task. Session history is rendered first, followed by provider catalogs and loaded Background entries from Agent Home, Memory, or other registered owners.

A Home Top Link such as `home:agent@...`, `home:what@...`, `home:why@...`, or `home:how@...` identifies content eligible for Background. The Link is not its body. Automatically loaded defaults are already visible; another exposed Top Link must be loaded through the Phase1 `load_background` control before its content can be used as Background.

Catalog metadata advertises available knowledge but is not loaded knowledge. Progressive Home resources, Memory search or recall results, Workspace content, and ActionResults belong in TurnTrace or an action-local task prompt rather than Background.

Background entries provide durable rules, knowledge, and prior-session facts. They do not describe the latest current-Turn action state; consult the later TurnTrace and WorkingContext sections for that.
