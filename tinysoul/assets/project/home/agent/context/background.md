# Background Context

Background contains information prepared before the current task: completed prior-Turn Session history, available knowledge catalogs, and loaded Home or Memory content. It is not the current Turn's action state.

A Top Link identifies content that can be loaded, not the content body. Automatically loaded entries are already usable; load another exposed Top Link only when its body is needed. Catalog metadata is an index, not loaded knowledge.

Session summaries and Turns are a compact history heap. When a needed prior-Turn detail is hidden behind an exposed Session ref, inspect only that path with `core.session.inspect`.

Use the later TurnTrace for current-Turn interaction and Working for the latest task and Workspace state.
