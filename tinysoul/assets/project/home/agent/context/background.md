# Background Context

Background contains information prepared before the current task: completed prior-Turn Session history, available knowledge catalogs, and loaded Home or Memory content. It is not the current Turn's action state.

A Top Link identifies content that can be loaded, not the content body. Automatically loaded entries are already usable; load another exposed Top Link only when its body is needed. Catalog metadata is an index, not loaded knowledge.

Session is a factual Map of completed Turns, Action occurrences, and explicit resource references. Use `core.context.inspect` with `session:map` or an exposed Session ref to find prior-Turn details.

Use the later TurnTrace for current-Turn interaction and Working for the latest task and Workspace state.
