# Background Context

Background contains information prepared before the current task: completed prior-Turn Session history, available knowledge catalogs, and loaded Home or Memory content. It is not the current Turn's action state.

A Top Link identifies content that can be loaded, not the content body. Automatically loaded entries are already usable; load another exposed Top Link only when its body is needed. Catalog metadata is an index, not loaded knowledge.

Session presents a semantic map followed by chronological interaction text from completed Turns. The map links topics, interpretations and shared history references; the text preserves original inputs, appended constraints, questions, ordered options, replies and confirmed answers once per Turn. Unclassified Turns remain available. Interpretations are source-backed judgments, not changes to recorded facts.

Use `core.context.inspect` with `session:map` or an exposed reference to navigate topics, history and precise evidence. A folded or excerpted Turn retains its reference for complete paginated reading. When new evidence changes your understanding, `core.session.organize` can revise topics and relations in a User Turn. Current accepted inputs and settled actions may support a revision, but the active Turn is not completed history.

Use the later TurnTrace for current-Turn interaction and Working for the latest task and Workspace state.
